"""Local minimal patches and the two scoped contribution API operations."""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .core import COMMIT, RshError, lookup, read_json, require_url, safe_relative, write_json

CHANGE_KINDS = {"dependency_fix", "invocation_fix", "docs_fix", "compatibility_fix", "test_fix"}
MAX_BUNDLE_BYTES = 64 * 1024


def patch_paths(patch):
    if not isinstance(patch, str) or not patch.strip():
        raise RshError("no_changes", "There is no patch to preserve or submit.", status="blocked", next_action="continue_user_task")
    paths = []
    previous = None
    saw_hunk = False
    for line in patch.splitlines():
        if line.startswith(("GIT binary patch", "Binary files ", "rename from ", "rename to ", "new file mode 120", "old mode ", "new mode ")):
            raise RshError("unsupported_patch", "Only ordinary text unified diffs are accepted.")
        if line.startswith("--- "):
            previous = line[4:].split("\t", 1)[0]
        elif line.startswith("+++ "):
            after = line[4:].split("\t", 1)[0]
            if previous is None:
                raise RshError("invalid_patch", "A unified diff needs paired file headers.")
            old = previous[2:] if previous.startswith("a/") else previous
            new = after[2:] if after.startswith("b/") else after
            if old == "/dev/null" or new == "/dev/null":
                raise RshError("unsupported_patch", "The pilot accepts modifications to existing files only.")
            target = old if new == "/dev/null" else new
            if not safe_relative(target) or (old != "/dev/null" and old != target):
                raise RshError("unsafe_patch_path", "Patch paths must be safe and cannot rename files.")
            if new != "/dev/null" and not safe_relative(new):
                raise RshError("unsafe_patch_path", "Patch target path is invalid.")
            paths.append(target)
            previous = None
        elif line.startswith("@@ "):
            saw_hunk = True
    if not paths or previous is not None or not saw_hunk:
        raise RshError("invalid_patch", "Expected a unified diff with file headers and a changed hunk.")
    return sorted(set(paths))


def reject_obvious_secrets(value):
    serialized = json.dumps(value, ensure_ascii=False)
    patterns = [r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
                r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b",
                r"\bsk-[A-Za-z0-9_-]{24,}\b", r"\bAKIA[A-Z0-9]{16}\b"]
    if any(re.search(pattern, serialized) for pattern in patterns):
        raise RshError("potential_secret", "Bundle contains a recognizable secret pattern; keep it local and remove credentials.",
                       status="blocked", next_action="remove_secrets_from_minimal_patch")


def validate_bundle(bundle, record=None):
    if not isinstance(bundle, dict) or bundle.get("schema_version") != "1":
        raise RshError("invalid_bundle", "Contribution schema_version must be 1.")
    required = ("skill_id", "base", "change_kind", "summary", "patch", "environment", "evidence", "attribution", "publication")
    for key in required:
        if key not in bundle:
            raise RshError("missing_bundle_field", f"Contribution lacks {key}.", field=key)
    if bundle["change_kind"] not in CHANGE_KINDS:
        raise RshError("invalid_change_kind", "Unsupported contribution change kind.")
    if not isinstance(bundle["summary"], str) or not 5 <= len(bundle["summary"]) <= 500:
        raise RshError("invalid_summary", "Summary must contain 5 to 500 characters.")
    base = bundle["base"]
    if not isinstance(base, dict) or not COMMIT.fullmatch(str(base.get("hub_commit", ""))) or not COMMIT.fullmatch(str(base.get("source_commit", ""))):
        raise RshError("invalid_base", "Contribution needs exact hub and source commit hashes.")
    if not isinstance(base.get("record_version"), str) or not base["record_version"]:
        raise RshError("invalid_base", "Contribution needs its base record version.")
    if not isinstance(bundle["environment"], dict) or not all(key in bundle["environment"] for key in ("runtime", "robot")):
        raise RshError("invalid_environment", "Environment must identify runtime and robot, using unknown when unverified.")
    evidence = bundle["evidence"]
    if not isinstance(evidence, dict) or evidence.get("level") not in ("not_run", "contributor_reported"):
        raise RshError("invalid_evidence", "Client evidence must be not_run or contributor_reported, never hub verification.")
    if evidence.get("reported_by") != "submitter" or not isinstance(evidence.get("result"), str) or not evidence["result"].strip():
        raise RshError("invalid_evidence", "Evidence needs a result and reported_by=submitter.")
    if evidence.get("command") is not None and not isinstance(evidence["command"], str):
        raise RshError("invalid_evidence", "Evidence command must be a string or null.")
    attribution = bundle["attribution"]
    if not isinstance(attribution, dict) or attribution.get("preserve_upstream_attribution") is not True or not isinstance(attribution.get("contributor_label"), str):
        raise RshError("invalid_attribution", "Preserved upstream attribution and a self-reported contributor label are required.")
    if not isinstance(bundle["publication"], dict) or not isinstance(bundle["publication"].get("public_submission_allowed"), bool):
        raise RshError("invalid_publication", "Publication declaration must be an explicit boolean.")
    paths = patch_paths(bundle["patch"])
    if record:
        if record["id"] != bundle["skill_id"]:
            raise RshError("base_conflict", "Bundle does not match this source record.", status="blocked", next_action="inspect_current_record")
        allowed = record.get("contribution", {}).get("allowed_paths", [])
        if any(path not in allowed for path in paths):
            raise RshError("path_not_allowed", "Patch changes files outside the recipe's contribution scope.", paths=paths)
    reject_obvious_secrets(bundle)
    if len(canonical_bytes(bundle)) > MAX_BUNDLE_BYTES:
        raise RshError("bundle_too_large", "Contribution exceeds 64 KiB; preserve only the relevant minimal change.")
    return paths


def canonical_bytes(bundle):
    return json.dumps(bundle, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def read_policy(project, policy_path=None):
    path = Path(policy_path) if policy_path else Path(project) / ".robot-skill-hub.json"
    return read_json(path) if path.is_file() else {}


def sharing_allowed(policy, skill_id, paths):
    publication = policy.get("publication", {})
    if publication.get("public_submission_allowed") is not True:
        return False
    skill_ids = publication.get("allowed_skill_ids")
    if skill_ids is not None and (not isinstance(skill_ids, list) or skill_id not in skill_ids):
        return False
    allowed_paths = publication.get("allowed_paths")
    if allowed_paths is not None:
        if not isinstance(allowed_paths, list) or not all(isinstance(pattern, str) for pattern in allowed_paths):
            return False
        if any(not any(fnmatch.fnmatchcase(path, pattern) for pattern in allowed_paths) for path in paths):
            return False
    return True


def create_bundle(catalog, skill_id, patch_file, metadata_file, output, project, *, policy_path=None, hub_commit=None):
    record = lookup(catalog, skill_id)
    try:
        patch = Path(patch_file).read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise RshError("patch_unavailable", "Cannot read the explicit patch file.") from exc
    paths = patch_paths(patch)
    metadata = read_json(metadata_file)
    policy = read_policy(project, policy_path)
    allowed = sharing_allowed(policy, skill_id, paths)
    lock_file = Path(project) / ".robot-skill-hub/locks" / (skill_id + ".json")
    lock = read_json(lock_file) if lock_file.is_file() else {}
    base = {"record_version": lock.get("record_version", record["maintenance"]["record_version"]),
            "hub_commit": hub_commit or lock.get("hub_commit") or catalog.get("hub_commit"),
            "source_commit": lock.get("source_commit", record["source"]["commit"])}
    bundle = {"schema_version": "1", "skill_id": skill_id, "base": base,
              "change_kind": metadata.get("change_kind"), "summary": metadata.get("summary"), "patch": patch,
              "environment": metadata.get("environment", {"runtime": "unknown", "robot": "unknown"}),
              "evidence": metadata.get("evidence", {"level": "not_run", "command": None,
                            "result": "No runtime verification performed.", "reported_by": "submitter"}),
              "attribution": metadata.get("attribution"),
              "publication": {"public_submission_allowed": allowed}}
    if metadata.get("supersedes_submission_id"):
        bundle["supersedes_submission_id"] = metadata["supersedes_submission_id"]
    validate_bundle(bundle, record)
    write_json(output, bundle)
    return {"status": "ready" if allowed else "blocked", "reason_code": "bundle_created" if allowed else "sharing_not_allowed",
            "bundle_path": str(Path(output).resolve()), "paths": paths, "network_performed": False,
            "next_action": "submit_when_ready" if allowed else "keep_local_draft_and_continue_user_task",
            "public_submission_allowed": allowed}


def request_json(method, url, token, *, payload=None, idempotency_key=None, timeout=60):
    require_url(url, local_http=True)
    headers = {"Accept": "application/json", "Authorization": "Bearer " + token, "User-Agent": "robot-skill-hub/1"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    request = urllib.request.Request(url, data=payload, headers=headers, method=method)
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=timeout) as response:
            content = response.read(1024 * 1024 + 1)
            code = response.status
    except urllib.error.HTTPError as exc:
        content = exc.read(1024 * 1024)
        try:
            error = json.loads(content)
        except (ValueError, UnicodeError):
            error = {}
        reasons = {401: "authentication_required", 403: "permission_denied", 409: "submission_conflict",
                   413: "bundle_too_large", 422: "invalid_submission", 429: "rate_limited", 503: "github_unavailable"}
        raise RshError(reasons.get(exc.code, "api_error"), "Submission API rejected the request.", status="blocked",
                       next_action="keep_local_draft_and_follow_api_error", http_status=exc.code,
                       api_error=error, retry_after=exc.headers.get("Retry-After")) from exc
    except OSError as exc:
        raise RshError("api_unavailable", "Submission API could not be reached; the local bundle is preserved.",
                       status="blocked", next_action="retry_same_bundle_with_same_idempotency_key") from exc
    if len(content) > 1024 * 1024:
        raise RshError("invalid_api_response", "API response exceeds 1 MiB.")
    try:
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise ValueError()
    except (ValueError, UnicodeError) as exc:
        raise RshError("invalid_api_response", "API did not return a JSON object.") from exc
    return {**parsed, "http_status": code}


def api_configuration(api_url):
    token = os.environ.get("RSH_SUBMISSION_TOKEN")
    if not token:
        raise RshError("missing_submission_token", "Set RSH_SUBMISSION_TOKEN to an operator-issued pilot token.",
                       status="blocked", next_action="keep_local_draft_and_configure_pilot_token", network_performed=False)
    api_url = api_url or os.environ.get("RSH_API_URL")
    if not api_url:
        raise RshError("missing_api_url", "Set RSH_API_URL or pass --api-url.", status="blocked",
                       next_action="configure_api_endpoint", network_performed=False)
    require_url(api_url, local_http=True)
    parsed = urllib.parse.urlsplit(api_url)
    if parsed.query:
        raise RshError("invalid_api_url", "API base URL cannot contain a query.")
    return api_url.rstrip("/"), token


def submit(catalog, bundle_path, project, *, policy_path=None, api_url=None, idempotency_key=None):
    bundle = read_json(bundle_path)
    record = lookup(catalog, bundle.get("skill_id"))
    paths = validate_bundle(bundle, record)
    policy = read_policy(project, policy_path)
    if bundle["publication"]["public_submission_allowed"] is not True or not sharing_allowed(policy, bundle["skill_id"], paths):
        raise RshError("sharing_not_allowed", "Project publication policy does not allow this public contribution.",
                       status="blocked", next_action="keep_local_draft_and_continue_user_task",
                       bundle_path=str(Path(bundle_path).resolve()), network_performed=False)
    base, token = api_configuration(api_url)
    payload = canonical_bytes(bundle)
    key = idempotency_key or hashlib.sha256(payload).hexdigest()
    if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{8,128}", key):
        raise RshError("invalid_idempotency_key", "Idempotency key must be 8 to 128 safe ASCII characters.")
    receipt_path = Path(bundle_path).with_name(Path(bundle_path).stem + ".receipt.json")
    # Save the retry identity before transmission so a lost response is recoverable.
    write_json(receipt_path, {"bundle_sha256": hashlib.sha256(payload).hexdigest(), "idempotency_key": key,
                              "api_url": base, "submission_id": None, "status": "sending"})
    response = request_json("POST", base + "/v1/submissions", token, payload=payload, idempotency_key=key)
    write_json(receipt_path, {**response, "idempotency_key": key, "bundle_sha256": hashlib.sha256(payload).hexdigest(), "api_url": base})
    return {**response, "receipt_path": str(receipt_path.resolve()), "idempotency_key": key}


def submission_status(submission_id, *, api_url=None):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", submission_id):
        raise RshError("invalid_submission_id", "Submission ID must be an opaque URL-safe identifier.")
    base, token = api_configuration(api_url)
    return request_json("GET", base + "/v1/submissions/" + submission_id, token)
