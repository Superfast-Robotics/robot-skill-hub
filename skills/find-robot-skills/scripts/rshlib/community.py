"""Consent-scoped, local-first community experience. No project scans or execution."""
from __future__ import annotations

import hashlib
import heapq
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

from . import contributions, memories, setup
from .core import RshError, read_json

API = "https://api.superfastrobotics.com/v1/community"
ID = re.compile(r"exp_[a-f0-9]{64}")


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".community-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def request(method, path, *, token=None, value=None):
    if not path.startswith("/") or path.startswith("//"):
        raise RshError("invalid_community_path", "Use a community API path.")
    headers = {"Accept": "application/json", "User-Agent": "robot-skill-hub/1", "DNT": "1", "X-RSH-Telemetry": "off"}
    if token:
        headers["Authorization"] = "Bearer " + token
    payload = None
    if value is not None:
        payload = contributions.canonical_bytes(value)
        headers["Content-Type"] = "application/json"
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    try:
        with urllib.request.build_opener(NoRedirect).open(urllib.request.Request(API + path, data=payload, headers=headers, method=method), timeout=10) as response:
            raw = response.read(524289)
        if len(raw) > 524288:
            raise ValueError("bounded response")
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError("object required")
        return result
    except urllib.error.HTTPError as error:
        reason = "community_http_" + str(error.code)
        try:
            supplied = json.loads(error.read(8192)).get("reason_code")
            if isinstance(supplied, str) and re.fullmatch(r"[a-z0-9_]{1,80}", supplied) and (not token or token not in supplied):
                memories.reject_secrets({"reason_code": supplied})
                reason = supplied
        except (ValueError, TypeError, AttributeError, RshError):
            pass
        raise RshError(reason, "Community API rejected the experience; keep the local copy.",
                       http_status=error.code, retryable=error.code == 429 or error.code >= 500) from None
    except (urllib.error.URLError, OSError, ValueError) as error:
        # Never print a response body, credentials, proxy address, or submitted data.
        raise RshError("community_unavailable", "Keep the local experience; bounded delivery can retry later.") from error


def identity(value):
    data = {"finding": memories.fingerprint(value["finding"]), "parent_id": value.get("parent_id"),
            "variant": value.get("variant"), "outcome": value.get("outcome")}
    return "exp_" + hashlib.sha256(contributions.canonical_bytes(data)).hexdigest()


def key_path():
    home = Path.home().resolve()
    path = home / ".robot-skill-hub/community-key.json"
    if not path.resolve().is_relative_to(home):
        raise RshError("credential_path_escape", "Community credential path must stay in the user home.")
    return path


def credential():
    path = key_path()
    if path.is_symlink() or path.is_file() and path.stat().st_size > 4096:
        raise RshError("invalid_community_credential", "Use the dedicated small installation credential file.")
    value = read_json(path) if path.is_file() else {}
    if not isinstance(value, dict) or not re.fullmatch(r"csh_[A-Za-z0-9_-]{43}", str(value.get("token", ""))):
        raise RshError("community_not_joined", "Use join once for an already-authorized public project scope.")
    return value


def join(project, *, skill_ids, kinds, allow_public_memory=False, offline=False):
    if offline:
        raise RshError("offline_enrollment", "Community enrollment requires connectivity; local saving remains available.")
    if not allow_public_memory:
        raise RshError("scope_required", "Record existing user authorization with --allow-public-memory and explicit scope.")
    memory = {"public_save_allowed": True, "allowed_skill_ids": sorted(set(skill_ids)), "allowed_kinds": sorted(set(kinds))}
    setup.validate_scope(memory)
    path = setup.policy_path(project)
    policy = setup.read_policy(path)
    credentials = key_path()
    if credentials.exists():
        local = credential()
    else:
        local = {"token": "csh_" + secrets.token_urlsafe(32), "enrolled": False}
        # write_json uses an exclusive temporary file and atomic replacement.
        write_json(credentials, local)
        os.chmod(credentials, 0o600)
    if not local.get("enrolled"):
        challenge = request("GET", "/challenge")
        if (challenge.get("difficulty_hex_zeros") != 4 or not re.fullmatch(r"\d{10}\.[a-f0-9]{64}\.[a-f0-9]{64}", str(challenge.get("challenge", "")))):
            raise RshError("invalid_challenge", "Unsupported enrollment challenge; no work was attempted.")
        digest = hashlib.sha256(local["token"].encode()).hexdigest()
        prefix = (challenge["challenge"] + "." + digest + ".").encode()
        start = time.monotonic()
        for nonce in range(2000000):
            if nonce % 4096 == 0 and time.monotonic() - start > 15:
                raise RshError("enrollment_work_bound", "Enrollment proof exceeded its 15 second CPU bound; retry later.")
            if hashlib.sha256(prefix + str(nonce).encode()).hexdigest().startswith("0000"):
                break
        else:
            raise RshError("enrollment_work_bound", "Enrollment proof exceeded its bounded attempts.")
        receipt = request("POST", "/enroll", value={"token": local["token"], "challenge": challenge["challenge"], "nonce": str(nonce)})
        if receipt.get("status") != "ready" or receipt.get("principal_id") != digest:
            raise RshError("invalid_enrollment_receipt", "Enrollment identity was not confirmed.")
        local.update(enrolled=True, principal_id=digest)
        write_json(credentials, local)
        os.chmod(credentials, 0o600)
    policy.update(memory=memory, community={"enabled": True, "sync_before_recall": True})
    setup.write_policy(path, policy)
    return {"status": "ready", "channel": "community", "scope": memory, "principal_id": local["principal_id"],
            "identity": "pseudonymous_installation", "credential_persisted_in_user_home": True,
            "next_action": "inspect_with_project_then_save_actual_findings", "manager_approval_required": False}


def enabled(project):
    policy = memories.policy_for(project, None) if project else {}
    settings = policy.get("community", {})
    return isinstance(settings, dict) and settings.get("enabled") is True


def automatic_sync_allowed(project):
    policy = memories.policy_for(project, None) if project else {}
    settings = policy.get("community", {})
    return enabled(project) and settings.get("sync_before_recall") is True


def root(project):
    base = Path(project).expanduser().resolve()
    if not base.is_dir():
        raise RshError("project_unavailable", "Use an existing project directory.")
    path = base / ".robot-skill-hub/community/outbox"
    if not path.resolve().is_relative_to(base):
        raise RshError("memory_path_escape", "Community storage must stay in this project.")
    return path


def verify_entry(entry):
    if not isinstance(entry, dict) or not isinstance(entry.get('content'), dict) or not isinstance(entry.get('delivery', {}), dict):
        raise RshError("invalid_local_experience", "Local experience must contain structured content and delivery state.")
    value = entry.get("content", {})
    memories.validate_payload(value.get('finding'))
    if value.get('schema_version') != '1' or identity(value) != entry.get("id"):
        raise RshError("invalid_local_experience", "Local content identity does not match.")
    return value


def deliver(entry, path, project, *, retry_blocked=False):
    value = verify_entry(entry)
    finding = value["finding"]
    result = {"status": "local_saved", "id": entry["id"], "finding_path": str(path), "next_action": "continue_user_task"}
    if entry.get("delivery", {}).get("status") == "stored":
        return {**result, "status": "stored", "replay": True}
    if entry.get("delivery", {}).get("status") == "needs_attention" and not retry_blocked:
        return {**result, "reason_code": entry["delivery"]["reason_code"], "automatic_retry": False}
    policy = memories.policy_for(project, None)
    if not enabled(project) or not memories.allowed(policy, finding["skill_id"], finding["kind"]):
        return {**result, "reason_code": "public_scope_not_allowed"}
    if time.time() < entry.get("delivery", {}).get("retry_after", 0):
        return {**result, "reason_code": "delivery_backoff"}
    network_performed = False
    try:
        local = credential()
        wire = {**value, "finding": {**finding, "publication": {"public_submission_allowed": True}}}
        network_performed = True
        receipt = request("POST", "/items", token=local["token"], value=wire)
        content = receipt.get("content", {})
        if (receipt.get("status") != "stored" or receipt.get("id") != entry["id"] or identity(content) != entry["id"]
                or hashlib.sha256(contributions.canonical_bytes(content)).hexdigest() != receipt.get("content_sha256")):
            raise RshError("invalid_community_receipt", "Stored content identity was not confirmed.")
        entry["delivery"] = {"status": "stored", "content_sha256": receipt["content_sha256"]}
        write_json(path, entry)
        return {**result, "status": "stored", "content_sha256": receipt["content_sha256"], "network_performed": True}
    except (RshError, OSError, ValueError, TypeError, KeyError) as error:
        permanent = isinstance(error, RshError) and error.result.get("retryable") is False
        reason = error.result["reason_code"] if isinstance(error, RshError) else "community_delivery_pending"
        entry["delivery"] = ({"status": "needs_attention", "reason_code": reason} if permanent else
                             {"status": "local_saved", "reason_code": reason, "retry_after": int(time.time()) + 900})
        try:
            write_json(path, entry)
        except OSError:
            pass
        return {**result, "reason_code": reason, "network_performed": network_performed, "automatic_retry": not permanent}


def save(catalog, skill_id, project, finding_file, *, offline=False, patch=None, license_spdx=None, parent_id=None, outcome=None):
    path = Path(finding_file)
    if path.stat().st_size > memories.MAX_BYTES:
        raise RshError("finding_too_large", "Use a bounded minimal finding.")
    finding = memories.normalize_finding(read_json(path))
    base, _ = memories.base_for(catalog, skill_id, project)
    value = {"schema_version": "1", "finding": {"schema_version": "1", "skill_id": skill_id, "base": base, **finding,
                                                   "publication": {"public_submission_allowed": False}}}
    if parent_id:
        if not ID.fullmatch(parent_id):
            raise RshError("invalid_parent", "Use the exact exp_ content ID.")
        value["parent_id"] = parent_id
    if patch:
        file = Path(patch)
        if file.stat().st_size > 12000 or not license_spdx or not finding["resolution"] or outcome:
            raise RshError("invalid_variant", "A variant needs a bounded patch, upstream license and resolution; report reuse separately.")
        text = file.read_text(encoding="utf-8")
        contributions.patch_paths(text)
        value["variant"] = {"patch": text, "license_spdx": license_spdx}
    elif license_spdx:
        raise RshError("invalid_variant", "--license requires --patch.")
    if outcome:
        if not parent_id or outcome not in ("succeeded", "failed", "not_applicable") or finding["evidence"]["level"] != "contributor_reported":
            raise RshError("invalid_outcome", "Report an actual result with contributor_reported evidence and an exact parent ID.")
        value["outcome"] = outcome
    memories.reject_secrets(value)
    if re.search(r"\bcsh_[A-Za-z0-9_-]{43}\b", json.dumps(value)):
        raise RshError("potential_secret", "Remove community credentials before saving.")
    if len(contributions.canonical_bytes(value)) > 32768:
        raise RshError("finding_too_large", "Experience exceeds the 32 KiB wire limit.")
    item_id = identity(value)
    target = root(project) / (item_id + ".json")
    if not target.resolve().is_relative_to(Path(project).expanduser().resolve()):
        raise RshError("memory_path_escape", "Experience resolves outside the project.")
    if target.exists():
        entry = read_json(target)
        verify_entry(entry)
    else:
        entry = {"id": item_id, "content": value, "created_at": int(time.time()), "delivery": {"status": "local_saved"}}
        write_json(target, entry)
    return {"status": "local_saved", "id": item_id, "finding_path": str(target), "next_action": "continue_user_task"} if offline else deliver(entry, target, project)


def sync(project, *, offline=False, limit=1, retry_blocked=False):
    if not 1 <= limit <= 3:
        raise RshError("invalid_limit", "Sync at most three experiences per call.")
    if offline or not enabled(project):
        return {"status": "ready", "deliveries": [], "network_performed": False}
    deliveries = []
    directory = root(project)
    cursor_path = directory.parent / 'sync-cursor.json'
    cursor = ''
    if cursor_path.is_file() and not cursor_path.is_symlink() and cursor_path.stat().st_size <= 1024:
        try:
            saved = read_json(cursor_path).get('after', '')
            if re.fullmatch(r'exp_[a-f0-9]{64}\.json', saved):
                cursor = saved
        except (RshError, AttributeError, TypeError):
            pass
    # Scan names only in the owned outbox; read at most 1,000 bodies. Advance
    # the cursor even past delivered items so a large history cannot starve new work.
    select = lambda after: heapq.nsmallest(1000, (p for p in directory.glob('exp_*.json') if p.name > after), key=lambda p: p.name)
    paths = select(cursor)
    if not paths and cursor:
        paths = select('')
    scanned = 0
    for path in paths:
        if len(deliveries) >= limit:
            break
        cursor = path.name
        scanned += 1
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 40000:
                continue
            entry = read_json(path)
            if not isinstance(entry, dict) or not isinstance(entry.get('delivery', {}), dict):
                continue
            state = entry.get("delivery", {})
            if state.get("status") == "stored" or state.get("retry_after", 0) > time.time() or state.get("status") == "needs_attention" and not retry_blocked:
                continue
            deliveries.append(deliver(entry, path, project, retry_blocked=retry_blocked))
        except (RshError, OSError, ValueError, TypeError):
            continue
    if scanned:
        try:
            write_json(cursor_path, {'after': cursor})
        except OSError:
            return {"status": "ready", "deliveries": deliveries, "scanned": scanned, "cursor_persisted": False}
    return {"status": "ready", "deliveries": deliveries, "local_files_read_maximum": 1000, "scanned": scanned}


def recall(catalog, skill_id, environment, *, project=None, offline=False, limit=3):
    if (not isinstance(environment, dict) or len(environment) > 16 or any(
            not isinstance(k, str) or (k not in memories.ENV_KEYS and not re.fullmatch(r"package\.[A-Za-z_][A-Za-z0-9_]{0,79}", k))
            or not memories.text(v, 1, 240) for k, v in environment.items())):
        raise RshError("invalid_environment", "Recall accepts only explicit bounded environment labels.")
    base, _ = memories.base_for(catalog, skill_id, project)
    expected = {k: v for k, v in environment.items() if str(v).lower() not in ("", "unknown")}
    results, seen, scanned = [], set(), 0
    local_truncated, local_skipped = False, 0
    if project:
        directories = [(root(project), True), (memories.outbox_root(project), False)]
        for directory, modern in directories:
            def candidates():
                nonlocal local_skipped
                for candidate in directory.glob('*.json'):
                    try:
                        if candidate.is_symlink() or not candidate.is_file():
                            continue
                        yield (candidate.stat().st_mtime_ns, candidate)
                    except OSError:
                        local_skipped += 1
            paths = [pair[1] for pair in heapq.nlargest(1001, candidates(), key=lambda pair: pair[0])]
            local_truncated = local_truncated or len(paths) > 1000
            for path in paths[:1000]:
                scanned += 1
                if scanned > 1000:
                    break
                try:
                    if path.is_symlink() or path.stat().st_size > 40000:
                        local_skipped += 1
                        continue
                    entry = read_json(path)
                    value = verify_entry(entry) if modern else {"schema_version": "1", "finding": entry["payload"]}
                    finding = value["finding"]
                    memories.validate_payload(finding)
                    if (finding["skill_id"] != skill_id or any(finding["base"][k] != base[k] for k in ("source_commit", "record_version"))
                            or any(str(finding["environment"].get(k, "")).lower() != str(v).lower() for k, v in expected.items())):
                        continue
                    item_id = identity(value)
                    if item_id not in seen:
                        seen.add(item_id)
                        results.append({"id": item_id, "summary": finding["summary"], "environment": finding["environment"],
                                        "location": "local", "path": str(path), "trust": "contributor_reported", "kind": "reuse_report" if value.get("outcome") else "variant" if value.get("variant") else "finding"})
                except (RshError, OSError, ValueError, KeyError, TypeError):
                    local_skipped += 1
                    continue
    remote, remote_status = {}, "offline" if offline else "unknown"
    if not offline:
        try:
            remote = request("GET", "/items?" + urllib.parse.urlencode({"skill_id": skill_id, "record_version": base["record_version"],
                                      "source_commit": base["source_commit"], "environment": json.dumps(expected), "limit": limit}))
            if remote.get("status") != "ready" or not isinstance(remote.get("results"), list) or len(remote['results']) > limit:
                raise ValueError("invalid response")
            for row in remote["results"]:
                if (not isinstance(row, dict) or not isinstance(row.get('base'), dict) or not isinstance(row.get('environment', {}), dict)
                        or not ID.fullmatch(str(row.get("id", ""))) or any(row['base'].get(k) != base[k] for k in ("record_version", "source_commit"))
                        or any(str(row.get('environment', {}).get(k, '')).lower() != str(v).lower() for k,v in expected.items())):
                    raise ValueError("scope mismatch")
            # Validate the entire page before merging; a malformed later row
            # cannot leave an earlier row partially trusted in the local result.
            for row in remote["results"]:
                if row["id"] in seen:
                    for local in results:
                        if local['id'] == row['id']:
                            local.update({k:v for k,v in row.items() if k not in ('location','path')})
                            local['also_published'] = True
                else:
                    results.append({**row, "location": "community"})
                    seen.add(row["id"])
            remote_status = "ready"
        except (RshError, ValueError, TypeError, KeyError):
            remote_status = "unknown"
    local = [row for row in results if row['location'] == 'local']
    shared = [row for row in results if row['location'] == 'community']
    selected = (local[:1] + shared + local[1:])[:limit]
    return {"status": "ready", "results": selected, "remote_status": remote_status,
            "complete": remote_status == "ready" and remote.get("complete") is True and len(results) <= limit and scanned <= 1000 and not local_truncated and local_skipped == 0,
            "local_skipped": local_skipped,
            "remote_next_after": remote.get("next_after"), "remote_through": remote.get("through"),
            "base": base, "interpretation": "data_only", "execution_performed": False,
            "next_action": "read_selected_experience_check_applicability_then_report_actual_outcome"}


def get(item_id, output=None):
    if not ID.fullmatch(item_id):
        raise RshError("invalid_experience_id", "Use an exp_ content ID.")
    value = request("GET", "/items/" + item_id)
    content = value.get("content", {})
    if (not isinstance(content, dict) or not isinstance(content.get("finding"), dict) or value.get("id") != item_id
            or identity(content) != item_id or hashlib.sha256(contributions.canonical_bytes(content)).hexdigest() != value.get("content_sha256")):
        raise RshError("invalid_experience_content", "Experience identity or digest mismatch.")
    if output:
        path = Path(output)
        if path.exists():
            raise RshError("output_exists", "Choose a new output path; existing files are preserved.")
        write_json(path, value)
        return {"status": "ready", "id": item_id, "path": str(path), "execution_performed": False, "interpretation": "data_only"}
    return {"status": "ready", **value, "execution_performed": False}
