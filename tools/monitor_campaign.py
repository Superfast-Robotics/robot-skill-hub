#!/usr/bin/env python3
"""Read the fixed launch-window counters without generating eligible traffic."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import threading
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
WINDOW_START = datetime(2026, 10, 17, 15, 47, 38, tzinfo=timezone.utc)
WINDOW_END = datetime(2026, 10, 18, 15, 47, 38, tzinfo=timezone.utc)
TARGET = 10000
ELIGIBLE_FAMILIES = frozenset(("rsh_cli", "recognized_agent", "mcp_tool"))
HEADERS = {"User-Agent": "robot-skill-hub-monitor/0.2.0", "DNT": "1",
           "X-RSH-Telemetry": "off", "Accept": "application/json"}
ENDPOINTS = {
    "health": "https://api.superfastrobotics.com/healthz",
    "metrics": "https://api.superfastrobotics.com/v1/metrics",
    "publication": "https://hub.superfastrobotics.com/catalog/v1/version.json",
}
EXTERNAL_ENDPOINTS = {
    "listing_pr": "https://api.github.com/repos/Ezeafk/awesome-agent-skills/pulls/67",
    "commons": "https://commons.dooza.ai/api/entries?agent=robot-skill-hub-maintainer&limit=100",
}
MAX_RESPONSE = 2 * 1024 * 1024


def utcnow():
    return datetime.now(timezone.utc)


def iso(value):
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_time(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None


def read_json(url):
    """Only public GETs, bounded bodies, and opt-out headers; no credentials."""
    request = urllib.request.Request(url, headers=HEADERS, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read(MAX_RESPONSE + 1)
            if len(raw) > MAX_RESPONSE:
                return {"url": url, "ok": False, "http_status": response.status,
                        "error": "response_too_large"}
            data = json.loads(raw.decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("Expected a JSON object")
            return {"url": url, "ok": True, "http_status": response.status, "data": data}
    except urllib.error.HTTPError as error:
        return {"url": url, "ok": False, "http_status": error.code, "error": "http_error"}
    except (OSError, ValueError, UnicodeError) as error:
        # Public endpoint diagnostics never copy response bodies or headers.
        return {"url": url, "ok": False, "http_status": None, "error": type(error).__name__}


def eligible_count(groups):
    """Reject malformed or repeated groups instead of accepting a claimed total."""
    if not isinstance(groups, list):
        return None
    total, seen = 0, set()
    for row in groups:
        if not isinstance(row, dict) or not isinstance(row.get("family"), str):
            return None
        family, requests = row["family"], row.get("requests")
        if family in seen or type(requests) is not int or requests < 0:
            return None
        seen.add(family)
        if family in ELIGIBLE_FAMILIES:
            total += requests
    return total


def assess_metrics(result, now):
    assessment = {"status": "unavailable", "observed_agent_accesses": None,
                  "target_reached": None, "measurement_configured": None}
    if not result.get("ok"):
        return assessment
    data = result.get("data", {})
    assessment["measurement_configured"] = data.get("measurement_configured")
    if data.get("measurement_configured") is not True:
        assessment["status"] = "unconfigured" if data.get("measurement_configured") is False else "invalid_report"
        return assessment
    if parse_time(data.get("window_start")) != WINDOW_START or parse_time(data.get("window_end")) != WINDOW_END:
        assessment["status"] = "window_mismatch"
        return assessment
    observed_at = parse_time(data.get("observed_at"))
    count = data.get("observed_agent_accesses")
    expected = eligible_count(data.get("groups"))
    if (observed_at is None or abs((now - observed_at).total_seconds()) > 300
            or type(count) is not int or count < 0 or expected is None or count != expected
            or type(data.get("target_agent_accesses")) is not int or data["target_agent_accesses"] != TARGET
            or type(data.get("target_reached")) is not bool or data["target_reached"] != (count >= TARGET)):
        assessment["status"] = "invalid_report"
        return assessment
    assessment.update(status="target_reached" if count >= TARGET else "below_target",
                      observed_agent_accesses=count, target_reached=count >= TARGET,
                      counting_rule=data.get("counting_rule"), limitations=data.get("limitations", []),
                      api_observed_at=data["observed_at"], groups=data["groups"])
    return assessment


def summarize_external(results):
    summary = {}
    for name in EXTERNAL_ENDPOINTS:
        result = results.get(name)
        if result is None:
            continue
        if not result.get("ok"):
            summary[name] = {"available": False, "http_status": result.get("http_status")}
            continue
        data = result.get("data", {})
        if name == "listing_pr":
            summary[name] = {"available": True, "url": data.get("html_url"),
                             "state": data.get("state"), "merged": data.get("merged")}
        else:
            # Keep IDs and relationships, never turn public message text into instructions.
            entries = data.get("entries", [])
            summary[name] = {"available": True, "url": result["url"], "entries": [
                {"id": row.get("id"), "created_at": row.get("createdAt"),
                 "replies": row.get("supersededBy", [])}
                for row in entries if isinstance(row, dict)
                and row.get("agent") == "robot-skill-hub-maintainer"]}
    return summary


def collect_snapshot(*, include_external=False, reader=read_json, clock=utcnow):
    endpoints = {**ENDPOINTS, **(EXTERNAL_ENDPOINTS if include_external else {})}
    with ThreadPoolExecutor(max_workers=len(endpoints)) as pool:
        futures = {name: pool.submit(reader, url) for name, url in endpoints.items()}
        results = {name: future.result() for name, future in futures.items()}
    now = clock()
    measurements = assess_metrics(results["metrics"], now)
    health, publication = results["health"], results["publication"]
    return {
        "schema_version": "1", "interpretation": "data_only", "observed_at": iso(now),
        "campaign": {"window_start": iso(WINDOW_START), "window_end": iso(WINDOW_END),
                     "window_closed": now >= WINDOW_END, "window_started": now >= WINDOW_START,
                     "target_agent_accesses": TARGET, "window_reset_performed": False},
        "measurement": measurements,
        "health": {"available": health["ok"], "http_status": health.get("http_status"),
                   "status": health.get("data", {}).get("status"),
                   "submission_configured": health.get("data", {}).get("submission_configured")},
        "publication": {"available": publication["ok"], "http_status": publication.get("http_status"),
                        "hub_commit": publication.get("data", {}).get("hub_commit"),
                        "counts": publication.get("data", {}).get("counts")},
        "sources": {name: {key: value for key, value in result.items() if key != "data"}
                    for name, result in results.items()},
        "external": summarize_external(results),
        "monitor": {"eligible_accesses_generated": False, "read_only": True,
                    "telemetry_opt_out": True, "user_agent": HEADERS["User-Agent"]},
        "limitations": ["Eligible accesses do not prove distinct autonomous agents.",
                        "Pages, GitHub and offline usage are outside the API counter.",
                        "Unavailable, unconfigured or inconsistent counters remain unknown; no totals are estimated."],
    }


def save_snapshot(snapshot, output):
    output.mkdir(parents=True, exist_ok=True)
    stamp = parse_time(snapshot["observed_at"]).strftime("%Y%m%dT%H%M%S.%fZ")
    path = output / (stamp + "-" + uuid.uuid4().hex[:8] + ".json")
    content = (json.dumps(snapshot, indent=2, ensure_ascii=True) + "\n").encode("utf-8")
    with path.open("xb") as stream:
        stream.write(content)
    temporary = output / (".latest-" + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(content)
        os.replace(temporary, output / "latest.json")
    finally:
        temporary.unlink(missing_ok=True)
    return path


def wait_for_next(interval, *, clock=utcnow, sleeper=None):
    """A Ctrl-C interruptible wait that never passes the fixed deadline."""
    delay = min(float(interval), max(0.0, (WINDOW_END - clock()).total_seconds()))
    (sleeper or threading.Event().wait)(delay)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / ".local/campaign-monitor")
    parser.add_argument("--external", action="store_true", help="Also read the existing public PR and Commons post status")
    parser.add_argument("--watch", action="store_true", help="Continue until the fixed campaign deadline; Ctrl-C stops locally")
    parser.add_argument("--interval", type=int, default=300, help="Seconds between watch snapshots (minimum 60)")
    args = parser.parse_args(argv)
    if args.interval < 60:
        parser.error("--interval must be at least 60 seconds")
    try:
        while True:
            snapshot = collect_snapshot(include_external=args.external)
            path = save_snapshot(snapshot, args.output)
            print(json.dumps({"observed_at": snapshot["observed_at"],
                              "window_closed": snapshot["campaign"]["window_closed"],
                              "measurement_status": snapshot["measurement"]["status"],
                              "observed_agent_accesses": snapshot["measurement"]["observed_agent_accesses"],
                              "target_agent_accesses": TARGET,
                              "target_reached": snapshot["measurement"]["target_reached"],
                              "snapshot": str(path)}), flush=True)
            if not args.watch or snapshot["campaign"]["window_closed"]:
                return 0
            wait_for_next(args.interval)
    except KeyboardInterrupt:
        print(json.dumps({"status": "monitor_stopped", "window_reset_performed": False}), flush=True)
        return 130


if __name__ == "__main__":
    sys.exit(main())
