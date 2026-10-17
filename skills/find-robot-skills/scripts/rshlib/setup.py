"""Explicit project authorization and read-only first-use diagnostics."""
from __future__ import annotations

from pathlib import Path
import json
import os
import re
import tempfile

from . import contributions, memories
from .core import IDENTIFIER, RshError, read_json

DEFAULT_API = "https://api.superfastrobotics.com"


def policy_path(project):
    root = Path(project).expanduser().resolve()
    if not root.is_dir():
        raise RshError("project_unavailable", "Setup requires an existing project directory.")
    target = root / ".robot-skill-hub.json"
    if not target.resolve().is_relative_to(root):
        raise RshError("policy_path_escape", "Project policy resolves outside the project.")
    return target


def read_policy(path):
    policy = read_json(path) if path.exists() else {}
    if not isinstance(policy, dict):
        raise RshError("invalid_project_policy", "Project policy must be a JSON object; it was not replaced.")
    return policy


def validate_scope(memory):
    if not isinstance(memory, dict) or not isinstance(memory.get("public_save_allowed"), bool):
        raise RshError("invalid_memory_policy", "Memory policy needs an explicit public_save_allowed boolean.")
    if set(memory) - {"public_save_allowed", "allowed_skill_ids", "allowed_kinds"}:
        raise RshError("invalid_memory_policy", "Memory policy contains unsupported fields.")
    for field, valid in (("allowed_skill_ids", lambda value: isinstance(value, str) and len(value) <= 80 and IDENTIFIER.fullmatch(value)),
                         ("allowed_kinds", lambda value: isinstance(value, str) and value in memories.KINDS)):
        values = memory.get(field)
        if values is None and not memory["public_save_allowed"]:
            continue
        if (not isinstance(values, list) or not values or any(not valid(value) for value in values)
                or len(set(values)) != len(values)):
            raise RshError("invalid_memory_policy", "Public saving requires explicit unique skill and finding-kind allowlists.")
    return memory


def write_policy(path, policy):
    """Atomically replace policy using a new exclusive file, never a fixed .tmp."""
    root = path.parent.resolve()
    if not path.resolve().is_relative_to(root):
        raise RshError("policy_path_escape", "Project policy resolves outside the project.")
    content = json.dumps(policy, ensure_ascii=False, indent=2) + "\n"
    descriptor, name = tempfile.mkstemp(prefix=".robot-skill-hub-", suffix=".tmp", dir=root)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if not path.resolve().is_relative_to(root) or not temporary.resolve().is_relative_to(root):
            raise RshError("policy_path_escape", "Policy write resolves outside the project.")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def configure(project, *, allow_public_memory=False, local_only=False, skill_ids=(), kinds=()):
    if bool(allow_public_memory) == bool(local_only):
        raise RshError("explicit_memory_mode_required", "Choose --local-only or the already-authorized --allow-public-memory scope.")
    if local_only and (skill_ids or kinds):
        raise RshError("invalid_setup_scope", "Local-only mode does not accept public skill or kind scopes.")
    memory = {"public_save_allowed": bool(allow_public_memory)}
    if allow_public_memory:
        memory.update(allowed_skill_ids=sorted(set(skill_ids)), allowed_kinds=sorted(set(kinds)))
    validate_scope(memory)
    path = policy_path(project)
    policy = read_policy(path)
    updated = {**policy, "memory": memory}
    changed = updated != policy
    if changed:
        write_policy(path, updated)
    return {"status": "ready", "reason_code": "project_memory_scope_configured", "policy_path": str(path),
            "memory": memory, "changed": changed, "network_performed": False,
            "authorization_basis": "explicit_caller_scope", "token_persisted": False,
            "next_action": "run_setup_check"}


def check(project, *, api_url=None, check_api=False, offline=False):
    path = policy_path(project)
    policy = read_policy(path)
    memory = validate_scope(policy["memory"]) if "memory" in policy else {"public_save_allowed": False}
    credential = {"configured": False, "source": "none", "authentication": "not_checked"}
    token_error = None
    try:
        token, source = contributions.submission_token()
        credential.update(configured=True, source=source)
    except RshError as error:
        token_error = error.result["reason_code"]
        credential["reason_code"] = token_error
    local_ready = memory["public_save_allowed"] and credential["configured"]
    result = {"status": "ready", "reason_code": "project_setup_checked", "policy_path": str(path),
              "memory": memory, "credential": credential, "local_public_save_ready": local_ready,
              "network_performed": False, "next_action": "save_observed_finding" if local_ready else "keep_findings_local"}
    if not check_api:
        return result
    if offline:
        raise RshError("offline_api_check", "--check-api cannot be combined with --offline.", network_performed=False)
    if token_error:
        return {**result, "status": "blocked", "reason_code": token_error, "next_action": "configure_scoped_token"}
    try:
        base, token = contributions.api_configuration(api_url or os.environ.get("RSH_API_URL") or DEFAULT_API)
        result["network_performed"] = True
        session = contributions.request_json("GET", base + "/v1/session", token, timeout=10)
        authorization = session.get("authorization")
        if (session.get("schema_version") != "1" or session.get("authenticated") is not True
                or not re.fullmatch(r"[a-f0-9]{64}", str(session.get("principal_id", "")))
                or not isinstance(authorization, dict) or authorization.get("api_submission_allowed") is not True
                or authorization.get("project_memory_scope") != "client_policy_required"):
            raise RshError("invalid_api_response", "API did not confirm the expected scoped session.")
        credential.update(authentication="verified", principal_id=session["principal_id"])
        return result
    except RshError as error:
        credential["authentication"] = "failed"
        details = memories.safe_api_error(error.result.get("api_error"))
        details = {key: value for key, value in details.items() if token not in value}
        return {**result, "status": "blocked", "reason_code": error.result["reason_code"],
                "api_error": details,
                "next_action": "keep_findings_local_and_check_api_configuration"}
