"""Activate one reviewed catalog generation through the fixed owned sync API.

CATALOG_SYNC_KEY is read only from the process environment. Requests never
follow redirects, change the expected commit, or reset server-side progress.
All internal traffic opts out of access measurements.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

ENDPOINT = "https://api.superfastrobotics.com/internal/catalog-sync"
MAX_RESPONSE_BYTES = 16 * 1024
MAX_REQUEST_SECONDS = 20
MAX_TIMEOUT_SECONDS = 540
MAX_RETRIES = 4
MAX_CALLS = 4096
PROPAGATION_SECONDS = 45
MAX_STALLED_CALLS = 5
COMMIT = re.compile(r"[a-f0-9]{40}")
RETRY_STATUSES = {408, 429, 500, 502, 503, 504}
FAILURE_CODES = {"invalid_commit", "invalid_timeout", "missing_sync_key", "invalid_response", "invalid_progress",
                 "invalid_conflict", "progress_changed", "sync_stalled", "sync_rejected", "retry_exhausted",
                 "sync_timeout", "call_limit", "catalog_write_limit"}


class SyncFailure(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _post(expected_commit, key, timeout):
    request = urllib.request.Request(ENDPOINT, method="POST",
        data=json.dumps({"hub_commit": expected_commit}, separators=(",", ":")).encode("ascii"),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json", "Accept": "application/json",
                 "User-Agent": "robot-skill-hub-internal-catalog-sync", "DNT": "1", "X-RSH-Telemetry": "off",
                 "Cache-Control": "no-cache"})
    try:
        response = urllib.request.build_opener(NoRedirect()).open(request, timeout=timeout)
    except urllib.error.HTTPError as error:
        response = error
    try:
        status = response.code
        retry_after = response.headers.get("Retry-After")
        # Read only a bounded JSON quota classification on 503. Never retain or
        # report arbitrary provider text or reflected request fields.
        if status == 503 and response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() == "application/json":
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) <= MAX_RESPONSE_BYTES:
                try:
                    value = json.loads(raw.decode("utf-8"))
                    if isinstance(value, dict) and value.get("reason_code") == "catalog_write_limit":
                        return status, {"reason_code": "catalog_write_limit"}, retry_after
                except (ValueError, UnicodeError):
                    pass
            return status, None, retry_after
        if status not in (200, 409):
            return status, None, retry_after
        declared = response.headers.get("Content-Length")
        if declared is not None and (not declared.isdigit() or int(declared) > MAX_RESPONSE_BYTES):
            raise SyncFailure("invalid_response", "The sync response exceeds its bounded JSON contract.")
        raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise SyncFailure("invalid_response", "The sync response exceeds its bounded JSON contract.")
        try:
            value = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeError):
            raise SyncFailure("invalid_response", "The sync response is not valid UTF-8 JSON.") from None
        return status, value, retry_after
    finally:
        response.close()


def _progress(value, expected_commit):
    fields = {"hub_commit", "status", "next_page", "total_pages", "records", "memories"}
    if (not isinstance(value, dict) or set(value) - fields or value.get("hub_commit") != expected_commit
            or value.get("status") not in {"syncing", "active"}
            or any(type(value.get(key)) is not int or value[key] < 0 for key in ("next_page", "total_pages", "records"))
            or ("memories" in value and (type(value["memories"]) is not int or value["memories"] < 0))
            or value["next_page"] > value["total_pages"]
            or (value["status"] == "active") != (value["next_page"] == value["total_pages"])):
        raise SyncFailure("invalid_progress", "The sync response has inconsistent generation or page progress.")
    return {key: value[key] for key in ("hub_commit", "status", "next_page", "total_pages", "records", "memories") if key in value}


def sync_catalog(expected_commit, *, timeout_seconds=MAX_TIMEOUT_SECONDS, request_fn=None,
                 clock=None, sleeper=None, report=None):
    """Resume one page per call, tolerating bounded transport and Pages delays."""
    if not isinstance(expected_commit, str) or not COMMIT.fullmatch(expected_commit):
        raise SyncFailure("invalid_commit", "An exact lowercase 40-hex Hub commit is required.")
    if (not isinstance(timeout_seconds, (int, float)) or isinstance(timeout_seconds, bool)
            or not 0 < timeout_seconds <= MAX_TIMEOUT_SECONDS):
        raise SyncFailure("invalid_timeout", "The sync deadline must be positive and at most 540 seconds.")
    key = os.environ.get("CATALOG_SYNC_KEY", "")
    if not key or key != key.strip() or len(key) > 4096 or not key.isascii() or any(ord(c) < 33 or ord(c) > 126 for c in key):
        raise SyncFailure("missing_sync_key", "Configure a valid CATALOG_SYNC_KEY environment value.")
    request_fn, clock, sleeper = request_fn or _post, clock or time.monotonic, sleeper or time.sleep
    emit = report or (lambda value: None)
    started = clock()
    deadline, propagation_deadline = started + timeout_seconds, started + min(PROPAGATION_SECONDS, timeout_seconds)
    previous, conflict = None, None
    failures, stalled, calls = 0, 0, 0

    def superseded():
        return {"status": "superseded", "expected_hub_commit": expected_commit, "hub_commit": conflict,
                "next_action": "allow_the_published_generation_sync_job_to_continue"}

    def pause(seconds):
        remaining = deadline - clock()
        if remaining <= 0:
            raise SyncFailure("sync_timeout", "The bounded sync deadline was reached; server progress was preserved.")
        sleeper(min(seconds, remaining))

    while calls < MAX_CALLS:
        now = clock()
        if conflict is not None and previous is None and now >= propagation_deadline:
            return superseded()
        if now >= deadline:
            raise SyncFailure("sync_timeout", "The bounded sync deadline was reached; server progress was preserved.")
        request_timeout = min(MAX_REQUEST_SECONDS, deadline - now)
        if conflict is not None and previous is None:
            request_timeout = min(request_timeout, propagation_deadline - now)
        calls += 1
        retry_after = None
        try:
            status, value, retry_after = request_fn(expected_commit, key, request_timeout)
        except (urllib.error.URLError, TimeoutError, OSError):
            status, value = 0, None
        if status == 503 and isinstance(value, dict) and value.get("reason_code") == "catalog_write_limit":
            # Daily free-tier limits cannot recover within this short job.
            # Preserve the same server cursor for the scheduled resume.
            raise SyncFailure("catalog_write_limit", "The free daily write limit was reached; resume after UTC midnight.")
        if status == 409:
            if (not isinstance(value, dict) or value.get("reason_code") != "catalog_changed"
                    or not isinstance(value.get("hub_commit"), str) or not COMMIT.fullmatch(value["hub_commit"])
                    or value["hub_commit"] == expected_commit):
                raise SyncFailure("invalid_conflict", "The sync generation-conflict response is invalid.")
            conflict = value["hub_commit"]
            if previous is not None or clock() >= propagation_deadline:
                return superseded()
            emit({"status": "waiting_for_publication", "expected_hub_commit": expected_commit, "hub_commit": conflict})
            remaining_propagation = propagation_deadline - clock()
            if remaining_propagation <= 0:
                return superseded()
            pause(min(5, remaining_propagation))
            continue
        if status == 200:
            progress = _progress(value, expected_commit)
            if previous is not None:
                if (progress["next_page"] < previous["next_page"]
                        or any(progress.get(k) != previous.get(k) for k in ("total_pages", "records", "memories"))):
                    raise SyncFailure("progress_changed", "The pinned sync generation changed its recorded progress.")
                stalled = stalled + 1 if progress["next_page"] == previous["next_page"] else 0
                if stalled >= MAX_STALLED_CALLS:
                    raise SyncFailure("sync_stalled", "The sync endpoint stopped advancing; server progress was preserved.")
            previous, failures, conflict = progress, 0, None
            emit(progress)
            if progress["status"] == "active":
                return progress
            continue
        # A later transport failure does not establish that the previously
        # observed different publication is still current.
        conflict = None
        if status not in RETRY_STATUSES and status != 0:
            raise SyncFailure("sync_rejected", "The sync endpoint rejected this request; inspect its configuration.")
        failures += 1
        if failures > MAX_RETRIES:
            raise SyncFailure("retry_exhausted", "Bounded sync retries were exhausted; server progress was preserved.")
        delay = min(5, 2 ** (failures - 1))
        if isinstance(retry_after, str) and re.fullmatch(r"\d{1,6}", retry_after):
            delay = min(5, max(delay, int(retry_after)))
        emit({"status": "retrying", "attempt": failures, "http_status": status})
        pause(delay)
    raise SyncFailure("call_limit", "The bounded sync call limit was reached; server progress was preserved.")


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, "Invalid command line; use --help.\n")


def main(argv=None):
    parser = SafeParser(description=__doc__)
    parser.add_argument("--hub-commit", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=MAX_TIMEOUT_SECONDS)
    args = parser.parse_args(argv)
    try:
        result = sync_catalog(args.hub_commit, timeout_seconds=args.timeout_seconds,
                              report=lambda value: print(json.dumps(value), flush=True))
        if result["status"] == "superseded":
            print(json.dumps(result), flush=True)
        return 0
    except SyncFailure as error:
        code = error.code if isinstance(error.code, str) and error.code in FAILURE_CODES else "sync_failed"
        print(json.dumps({"status": "deferred" if code == "catalog_write_limit" else "failed", "reason_code": code}), file=sys.stderr)
        if code == "catalog_write_limit":
            return 75
    except Exception:
        # Never print raw exceptions: transports can include request headers.
        print(json.dumps({"status": "failed", "reason_code": "unexpected_sync_failure"}), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
