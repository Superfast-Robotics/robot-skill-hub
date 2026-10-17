"""New robot skills enter as pinned, data-only source references for review."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import urllib.parse
from pathlib import Path

from . import contributions
from .core import COMMIT, RshError, read_json

SOURCE_REVISION = re.compile(r"(?:[a-f0-9]{40}|sha256:[a-f0-9]{64})")
ARTIFACT_KINDS = {"code", "policy", "model", "dataset", "workflow", "robot_description", "documentation", "tool", "other"}
MAX_SOURCE_BYTES = 2 ** 53 - 1  # Preserve exact JSON integer identity in the Worker.


def source_revision(record):
    source = record.get("source", {})
    return source.get("commit") or source.get("revision")


def _need(condition, code, message):
    if not condition:
        raise RshError(code, message)


def _text(value, limit=500):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= limit and not re.search(r"[\x00-\x1f]", value)


def _object(value, fields):
    return isinstance(value, dict) and set(value) <= set(fields)


def _strings(value, limit=20, empty=False):
    return (isinstance(value, list) and (empty or bool(value)) and len(value) <= limit
            and all(_text(item, 240) for item in value) and len(value) == len(set(value)))


def public_url(value):
    if not _text(value, 1500):
        return False
    try:
        url = urllib.parse.urlsplit(value)
        return (url.scheme == "https" and not url.username and not url.password and not url.query and not url.fragment
                and not url.port and bool(re.fullmatch(r"[a-z0-9][a-z0-9.-]*\.[a-z]{2,}", url.hostname or "", re.I))
                and not re.search(r"(?:^|\.)(?:localhost|local|internal|invalid|test|example)$", url.hostname or ""))
    except ValueError:
        return False


def validate_skill(record):
    _need(_object(record, ["id", "name", "summary", "framework", "kind", "capabilities", "aliases", "robots", "source", "license", "artifact", "requirements", "invocation", "compatibility", "setup_url"]), "invalid_intake", "Unknown skill metadata or verification claim.")
    _need(isinstance(record.get("id"), str) and len(record["id"]) <= 80 and re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", record["id"])
          and _text(record.get("name"), 150) and _text(record.get("summary"), 1000) and _text(record.get("framework"), 120),
          "invalid_intake", "A stable ID, name, summary and framework are required.")
    _need(record.get("kind") == "community_skill" and _strings(record.get("capabilities"))
          and _strings(record.get("aliases"), empty=True) and _strings(record.get("robots")), "invalid_intake", "Describe capabilities, aliases and robot families.")
    source = record.get("source")
    _need(_object(source, ["repository", "commit", "revision", "path", "url", "sha256", "bytes", "authors"]), "invalid_source", "Unknown source field.")
    _need(public_url(source.get("repository")) and public_url(source.get("url")) and _text(source.get("path"), 500)
          and "\\" not in source["path"] and not any(part in ("", ".", "..") for part in source["path"].split("/"))
          and isinstance(source.get("sha256"), str) and re.fullmatch(r"[a-f0-9]{64}", source["sha256"])
          and type(source.get("bytes")) is int and 0 < source["bytes"] <= MAX_SOURCE_BYTES and _strings(source.get("authors")),
          "invalid_source", "Supply a public pinned source, safe path, SHA-256, positive safe-integer byte count and upstream authors.")
    if source.get("commit"):
        _need(bool(COMMIT.fullmatch(str(source["commit"]))) and "revision" not in source
              and source["commit"] in urllib.parse.urlsplit(source["url"]).path.split("/"), "invalid_source", "A Git URL must contain its exact commit as a path segment.")
    else:
        _need("commit" not in source and source.get("revision") == "sha256:" + source["sha256"], "invalid_source", "A standalone artifact revision must match its SHA-256.")
    license_info = record.get("license")
    _need(_object(license_info, ["spdx", "url", "scope"]) and _text(license_info.get("spdx"), 120)
          and public_url(license_info.get("url")) and _text(license_info.get("scope"), 1000), "invalid_license", "Declare the upstream license, public license URL and scope.")
    artifact = record.get("artifact")
    _need(_object(artifact, ["kind", "format"]) and artifact.get("kind") in ARTIFACT_KINDS and _text(artifact.get("format"), 120), "invalid_artifact", "Describe the artifact kind and format.")
    req = record.get("requirements")
    _need(_object(req, ["python", "packages", "hardware", "system", "notes"]) and "python" in req
          and (req["python"] is None or _text(req["python"], 120)) and _strings(req.get("packages"), 30, True)
          and _strings(req.get("hardware"), 20, True) and _strings(req.get("system"), 20, True) and _text(req.get("notes"), 2000),
          "invalid_requirements", "Declare requirements explicitly; Python may be null.")
    invoke = record.get("invocation")
    _need(_object(invoke, ["entrypoint", "notes"]) and _text(invoke.get("entrypoint"), 500) and _text(invoke.get("notes"), 2000)
          and public_url(record.get("setup_url")), "invalid_invocation", "Provide an upstream entrypoint, limitations and setup URL.")
    required = {"runtime", "runtime_version", "robot", "controller", "observation", "os"}
    optional = {"python", "architecture"}
    combos = record.get("compatibility")
    _need(isinstance(combos, list) and 0 < len(combos) <= 20 and all(_object(c, required | optional) and required <= set(c)
          and all(_text(value, 120) for value in c.values()) for c in combos), "invalid_compatibility", "Explicit compatibility combinations are required; Python and architecture may be omitted when unknown.")


def validate_bundle(value):
    _need(_object(value, ["schema_version", "base", "skill", "attribution", "publication"]) and value.get("schema_version") == "1", "invalid_intake", "A version 1 new-skill bundle is required.")
    _need(_object(value.get("base"), ["hub_commit"]) and bool(COMMIT.fullmatch(str(value["base"].get("hub_commit", "")))), "invalid_base", "An exact current hub commit is required.")
    validate_skill(value.get("skill"))
    attr = value.get("attribution")
    _need(_object(attr, ["contributor_label", "preserve_upstream_attribution"]) and _text(attr.get("contributor_label"), 150)
          and attr.get("preserve_upstream_attribution") is True, "invalid_attribution", "Preserve upstream attribution and label the contributor.")
    _need(_object(value.get("publication"), ["public_submission_allowed"]) and type(value["publication"].get("public_submission_allowed")) is bool,
          "invalid_publication", "An explicit sharing declaration is required.")
    contributions.reject_obvious_secrets(value)
    content = json.dumps(value, ensure_ascii=False)
    _need(not re.search(r"\brsh_[A-Za-z0-9_-]{43}\b|\bBearer\s+[A-Za-z0-9._~+/-]{16,}=*", content, re.I), "potential_secret", "Remove recognizable credentials from the minimal record.")
    _need(len(contributions.canonical_bytes(value)) <= 16 * 1024, "bundle_too_large", "New-skill metadata is limited to 16 KiB.")


def validate_published_reference(record):
    """Validate the generated intake data format without granting runtime trust."""
    _need(isinstance(record, dict), "invalid_intake", "An intake reference must be an object.")
    generated = {"access", "evidence", "maintenance"}
    draft = {key: value for key, value in record.items() if key not in generated}
    access = record.get("access", {})
    _need(_object(access, ["mode", "hub_prepare", "instructions", "setup_url"]) and access.get("mode") == "source_reference"
          and access.get("hub_prepare") is False and _text(access.get("instructions"), 2000), "invalid_intake", "Intake references cannot claim a preparation adapter.")
    draft["setup_url"] = access.get("setup_url")
    license_info = draft.get("license", {})
    _need(isinstance(license_info, dict) and type(license_info.get("verified")) is bool, "invalid_license", "License review state is required.")
    draft["license"] = {key: value for key, value in license_info.items() if key != "verified"}
    combos = draft.get("compatibility", [])
    _need(isinstance(combos, list) and all(isinstance(c, dict) and c.get("status") in {"unknown", "contributor_reported", "source_reviewed"} for c in combos), "invalid_compatibility", "Source references cannot claim hub runtime verification.")
    draft["compatibility"] = [{key: value for key, value in combo.items() if key != "status"} for combo in combos]
    validate_skill(draft)
    evidence = record.get("evidence", {})
    _need(_object(evidence, ["level", "runtime_verification", "checked_at", "inspection"]) and evidence.get("level") in {"contributor_reported", "source_reviewed"}
          and evidence.get("runtime_verification") == "not_run" and _text(evidence.get("checked_at"), 30) and _text(evidence.get("inspection"), 2000), "invalid_evidence", "Source intake evidence must remain separate from runtime execution.")
    maintenance = record.get("maintenance", {})
    _need(_object(maintenance, ["record_version", "last_checked", "upstream_status"]) and _text(maintenance.get("record_version"), 120)
          and _text(maintenance.get("last_checked"), 30) and _text(maintenance.get("upstream_status"), 120), "invalid_intake", "A reviewed source reference needs a version and maintenance state.")


def _write(path, value, project=None):
    if project and not path.resolve().is_relative_to(project):
        raise RshError("intake_path_escape", "Local intake storage resolves outside the project.")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".rsh-intake-", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        if project and not path.resolve().is_relative_to(project):
            raise RshError("intake_path_escape", "Local intake storage resolves outside the project.")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def register(catalog, skill_path, project, *, contributor, policy_path=None, api_url=None, output=None, draft=False, offline=False, refresh_base=False):
    root = Path(project).expanduser().resolve()
    _need(root.is_dir(), "project_unavailable", "Registration requires an existing project directory.")
    skill = read_json(skill_path)
    validate_skill(skill)
    policy = contributions.read_policy(project, policy_path)
    publication = policy.get("publication", {})
    scope = publication.get("allowed_new_skill_ids", [])
    allowed = (publication.get("public_submission_allowed") is True and isinstance(scope, list) and skill["id"] in scope
               and contributions.sharing_allowed(policy, skill["id"], ["catalog/intake/" + skill["id"] + ".json"]))
    bundle = {"schema_version": "1", "base": {"hub_commit": catalog.get("hub_commit")}, "skill": skill,
              "attribution": {"contributor_label": contributor, "preserve_upstream_attribution": True},
              "publication": {"public_submission_allowed": allowed}}
    validate_bundle(bundle)
    path = Path(output) if output else root / ".robot-skill-hub/intake" / (skill["id"] + ".json")
    boundary = None if output else root
    if boundary and not path.resolve().is_relative_to(boundary):
        raise RshError("intake_path_escape", "Local intake storage resolves outside the project.")
    if path.is_file() and not refresh_base:
        previous = read_json(path)
        validate_bundle(previous)
        # Retrying an accepted-to-send local identity must survive a newer catalog.
        # Changing its base is an explicit operation after inspecting a conflict.
        if (previous["publication"]["public_submission_allowed"] is True
                and previous["skill"] == bundle["skill"] and previous["attribution"] == bundle["attribution"]):
            bundle["base"] = previous["base"]
    _write(path, bundle, boundary)
    if draft or offline or not allowed:
        return {"status": "local_saved", "reason_code": "intake_draft_saved" if allowed else "sharing_not_allowed",
                "bundle_path": str(path.resolve()), "public_submission_allowed": allowed, "network_performed": False,
                "next_action": "submit_when_authorized" if not allowed else "register_when_ready"}
    base, token = contributions.api_configuration(api_url)
    _need(token not in json.dumps(bundle), "potential_secret", "The active credential cannot appear in public metadata.")
    payload = contributions.canonical_bytes(bundle)
    key = hashlib.sha256(payload).hexdigest()
    receipt_path = path.with_name(path.stem + ".receipt.json")
    _write(receipt_path, {"bundle_sha256": key, "idempotency_key": key, "api_url": base, "submission_id": None, "status": "sending"}, boundary)
    response = contributions.request_json("POST", base + "/v1/skills", token, payload=payload, idempotency_key=key)
    _write(receipt_path, {**response, "idempotency_key": key, "bundle_sha256": key, "api_url": base}, boundary)
    return {**response, "bundle_path": str(path.resolve()), "receipt_path": str(receipt_path.resolve()), "idempotency_key": key}
