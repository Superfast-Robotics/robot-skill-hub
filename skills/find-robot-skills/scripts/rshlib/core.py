"""Catalog validation and conservative compatibility matching."""
from __future__ import annotations

import json
import os
import platform
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[2]
COMMIT = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
IDENTIFIER = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class RshError(Exception):
    def __init__(self, reason_code, message, *, status="failed", next_action="correct_input", **details):
        super().__init__(message)
        self.result = {"status": status, "reason_code": reason_code, "message": message,
                       "next_action": next_action, **details}


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise RshError("invalid_json", f"Cannot read JSON file: {path}") from exc


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def safe_relative(path):
    """A portable repository path, never an absolute path or traversal."""
    return (isinstance(path, str) and bool(path) and "\\" not in path and ":" not in path
            and not path.startswith("/") and all(p not in ("", ".", "..") for p in path.split("/")))


def require_url(url, *, local_http=False):
    try:
        parsed = urllib.parse.urlsplit(url)
        allowed = parsed.scheme == "https" or (local_http and parsed.scheme == "http"
                  and parsed.hostname in ("localhost", "127.0.0.1", "::1"))
        if not allowed or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise ValueError()
        return url
    except (TypeError, ValueError) as exc:
        raise RshError("invalid_url", "Use an HTTPS URL without embedded credentials.") from exc


def validate_record(record):
    if not isinstance(record, dict):
        raise RshError("invalid_record", "Catalog record must be an object.")
    for key in ("id", "name", "summary", "capabilities", "source", "license", "compatibility",
                "requirements", "invocation", "preparation", "evidence", "maintenance"):
        if key not in record:
            raise RshError("missing_record_field", f"Catalog record lacks {key}.", field=key)
    if not isinstance(record["id"], str) or not IDENTIFIER.fullmatch(record["id"]):
        raise RshError("invalid_record_id", "Invalid skill ID.")
    source = record["source"]
    if not isinstance(source, dict) or not COMMIT.fullmatch(str(source.get("commit", ""))):
        raise RshError("invalid_source_pin", "Source commit must be an exact 40-character lowercase hash.")
    for key in ("repository", "archive_url", "paths", "archive_sha256", "authors"):
        if key not in source:
            raise RshError("missing_source_field", f"Source lacks {key}.", field="source." + key)
    require_url(source["repository"])
    require_url(source["archive_url"])
    if source["commit"] not in source["archive_url"]:
        raise RshError("invalid_source_pin", "Archive URL does not contain the pinned commit.")
    if not SHA256.fullmatch(str(source["archive_sha256"])):
        raise RshError("invalid_source_hash", "Archive needs an exact SHA-256 hash.")
    if not isinstance(source["paths"], list) or not source["paths"] or not all(safe_relative(p) for p in source["paths"]):
        raise RshError("invalid_source_path", "Source paths must be nonempty safe relative paths.")
    license_info = record["license"]
    if not isinstance(license_info, dict) or "spdx" not in license_info or "verified" not in license_info:
        raise RshError("invalid_license", "License identifier and verification state are required.")
    combinations = record["compatibility"]
    if not isinstance(combinations, list) or not combinations:
        raise RshError("invalid_compatibility", "At least one exact compatibility combination is required.")
    for combination in combinations:
        for key in ("runtime", "runtime_version", "robot", "controller", "observation", "os"):
            if not isinstance(combination.get(key), str) or not combination[key]:
                raise RshError("missing_compatibility_field", f"Compatibility lacks {key}.")
        if any(value in ("*", "latest", "main", "master") for value in combination.values()):
            raise RshError("unbounded_compatibility", "Compatibility must use explicit combinations.")
    requirements = record["requirements"]
    if not isinstance(requirements.get("python"), str) or not isinstance(requirements.get("api_keys", []), list):
        raise RshError("invalid_requirements", "Python requirement and API key names are required.")
    for field in ("argv",):
        argv = record["invocation"].get(field)
        if not isinstance(argv, list) or not argv or not all(isinstance(x, str) for x in argv):
            raise RshError("invalid_invocation", "Invocation argv must be a nonempty string array.")
    install = record["preparation"].get("install_argv", [])
    if not isinstance(install, list) or not all(isinstance(x, str) for x in install):
        raise RshError("invalid_preparation", "Installation argv must be a string array.")
    commands = record["preparation"].get("install_commands", [])
    if not isinstance(commands, list) or any(not isinstance(command, list) or not command or
            not all(isinstance(argument, str) for argument in command) for command in commands):
        raise RshError("invalid_preparation", "Installation commands must be arrays of argument arrays.")
    files = record["preparation"].get("files", {})
    if not isinstance(files, dict) or any(not safe_relative(path) or not isinstance(content, str)
                                          for path, content in files.items()):
        raise RshError("invalid_recipe_file", "Embedded recipe files require safe paths and text content.")
    if record["evidence"].get("level") not in ("not_run", "source_reviewed", "install_verified", "import_verified", "task_complete", "contributor_reported"):
        raise RshError("invalid_evidence", "Unknown verification level.")
    return record


def load_catalog(location=None):
    if location and str(location).startswith(("https://", "http://")):
        require_url(location, local_http=True)
        try:
            with urllib.request.urlopen(location, timeout=30) as response:
                data = response.read(4 * 1024 * 1024 + 1)
            if len(data) > 4 * 1024 * 1024:
                raise RshError("catalog_too_large", "Catalog exceeds 4 MiB.")
            catalog = json.loads(data)
        except (OSError, ValueError) as exc:
            raise RshError("catalog_unavailable", "Could not retrieve catalog.", next_action="use_bundled_snapshot") from exc
    else:
        catalog = read_json(location or SKILL_ROOT / "assets/catalog.snapshot.json")
    return validate_catalog(catalog)


def validate_catalog(catalog):
    if not isinstance(catalog, dict) or catalog.get("schema_version") != "1" or not isinstance(catalog.get("records"), list):
        raise RshError("invalid_catalog", "Expected catalog schema_version 1 and records array.")
    ids = set()
    for record in catalog["records"]:
        validate_record(record)
        if record["id"] in ids:
            raise RshError("duplicate_skill_id", "Catalog contains duplicate skill IDs.")
        ids.add(record["id"])
    return catalog


def lookup(catalog, skill_id):
    for record in catalog["records"]:
        if record["id"] == skill_id:
            return record
    raise RshError("skill_not_found", f"No catalog skill named {skill_id}.", status="unsupported", next_action="find_supported_skill")


ENVIRONMENT_FIELDS = ("runtime", "runtime_version", "robot", "controller", "observation", "os", "python", "architecture")


def compatibility(record, environment):
    """Return no match on any explicit conflict; unknowns stay unknown."""
    supplied = {key: str(environment[key]).lower() for key in ENVIRONMENT_FIELDS
                if environment.get(key) not in (None, "", "unknown")}
    if "python" in supplied:
        if not re.fullmatch(r"\d+\.\d+(?:\.\d+)?", supplied["python"]) or not python_satisfies(record["requirements"]["python"], supplied["python"]):
            return {"compatibility_status": "incompatible", "missing_requirements": [], "combinations": []}
        supplied["python"] = ".".join(supplied["python"].split(".")[:2])
    if "architecture" in supplied:
        supplied["architecture"] = {"amd64": "x86_64", "aarch64": "arm64"}.get(supplied["architecture"], supplied["architecture"])
    candidates = [item for item in record["compatibility"]
                  if all((key in ("python", "architecture") and key not in item)
                         or str(item.get(key, "")).lower() == value for key, value in supplied.items())]
    if not candidates:
        return {"compatibility_status": "incompatible", "missing_requirements": [], "combinations": []}
    relevant_fields = [key for key in ENVIRONMENT_FIELDS if key not in ("python", "architecture")
                       or any(key in item for item in candidates)]
    missing = [key for key in relevant_fields if key not in supplied]
    return {"compatibility_status": "unknown" if missing else "documented",
            "missing_requirements": missing, "combinations": candidates}


def selection_base(catalog, record, *, reference=False):
    """Memory identity for a selected entry, without claiming execution support."""
    source = record.get("source", {})
    if reference:
        digest = source.get("sha256")
        if not SHA256.fullmatch(str(digest or "")):
            return None
        version = "source-" + digest
    else:
        version = record.get("maintenance", {}).get("record_version")
    hub = catalog.get("hub_commit")
    commit = source.get("commit")
    if (not isinstance(version, str) or not 1 <= len(version) <= 120
            or not COMMIT.fullmatch(str(hub or "")) or not COMMIT.fullmatch(str(commit or ""))):
        return None
    return {"record_version": version, "hub_commit": hub, "source_commit": commit}


def find(catalog, query, environment, limit=3):
    tokens = re.findall(r"[a-z0-9]+", query.lower())
    results = []
    for record in catalog["records"]:
        matched = compatibility(record, environment)
        if matched["compatibility_status"] == "incompatible":
            continue
        words = " ".join([record["id"], record["name"], record["summary"],
                          *record["capabilities"], *record.get("aliases", [])]).lower()
        score = sum(token in words for token in tokens)
        if tokens and score == 0:
            continue
        results.append({"id": record["id"], "name": record["name"], "summary": record["summary"],
                        "kind": "preparation_recipe", "hub_prepare": True, "next_action": "inspect_recipe",
                        "source_commit": record["source"]["commit"], "record_version": record["maintenance"]["record_version"],
                        "memory_base": selection_base(catalog, record),
                        "prepare_args": ["prepare", record["id"], "--expected-source-commit", record["source"]["commit"],
                                         "--expected-record-version", record["maintenance"]["record_version"]],
                        "match_reason": ["Explicit environment constraints match a documented combination."]
                        + (["Environment is incomplete; compatibility is unconfirmed."] if matched["missing_requirements"] else []),
                        "missing_requirements": matched["missing_requirements"],
                        "compatibility_status": matched["compatibility_status"],
                        "evidence_level": record["evidence"]["level"], "_score": score})
    for record in catalog.get("references", {}).get("records", []):
        if not isinstance(record, dict):
            continue
        framework = str(record.get("framework", "")).lower()
        runtime = str(environment.get("runtime", "unknown")).lower()
        if runtime not in ("", "unknown", framework):
            continue
        if (not IDENTIFIER.fullmatch(str(record.get("id", ""))) or not isinstance(record.get("source"), dict)
                or not COMMIT.fullmatch(str(record["source"].get("commit", "")))):
            continue
        words = " ".join([record["id"], str(record.get("name", "")), str(record.get("summary", "")),
                          framework, *record.get("capabilities", [])]).lower()
        score = sum(token in words for token in tokens)
        if tokens and score == 0:
            continue
        results.append({"id": record["id"], "name": record.get("name", record["id"]),
                        "summary": record.get("summary", ""), "kind": "source_reference", "hub_prepare": False,
                        "next_action": "open_source_reference", "source_url": record["source"].get("url"),
                        "source_commit": record["source"]["commit"], "framework": framework,
                        "memory_base": selection_base(catalog, record, reference=True),
                        "compatibility_status": "unknown", "missing_requirements": ["upstream_environment_review"],
                        "match_reason": ["Pinned official source example; no Hub preparation adapter or environment compatibility claim."],
                        "evidence_level": record.get("evidence", {}).get("level", "source_reviewed"), "_score": score})
    results.sort(key=lambda item: (-item["_score"], not item["hub_prepare"], item["id"]))
    for item in results:
        item.pop("_score")
    return {"status": "ready", "results": results[:limit], "total": len(results),
            "execution_performed": False, "catalog_hub_commit": catalog.get("hub_commit"),
            "catalog_origin": catalog.get("catalog_origin", "explicit")}


def inspect(catalog, skill_id):
    for reference in catalog.get("references", {}).get("records", []):
        if reference.get("id") == skill_id:
            return {"status": "ready", **reference, "kind": "source_reference", "hub_prepare": False,
                    "memory_base": selection_base(catalog, reference, reference=True),
                    "next_action": "open_source_reference", "execution_performed": False}
    record = lookup(catalog, skill_id)
    return {"status": "ready", **record, "commit": record["source"]["commit"],
            "kind": "preparation_recipe", "hub_prepare": True,
            "memory_base": selection_base(catalog, record),
            "prepare_args": ["prepare", record["id"], "--expected-source-commit", record["source"]["commit"],
                             "--expected-record-version", record["maintenance"]["record_version"]],
            "entrypoint": record["invocation"]["entrypoint"], "inputs": record["invocation"].get("inputs"),
            "outputs": record["invocation"].get("outputs"), "example": record["invocation"].get("example"),
            "execution_performed": False, "catalog_hub_commit": catalog.get("hub_commit")}


def local_environment():
    return {"os": {"windows": "windows", "darwin": "macos", "linux": "linux"}.get(platform.system().lower(), "unknown"),
            "python": platform.python_version(),
            "architecture": {"amd64": "x86_64", "aarch64": "arm64"}.get(platform.machine().lower(), platform.machine().lower())}


def python_satisfies(specification, version):
    """Small explicit subset used by reviewed recipes, no dependency on packaging."""
    actual = tuple(int(part) for part in version.split(".")[:3])
    actual += (0,) * (3 - len(actual))
    for clause in specification.split(","):
        match = re.fullmatch(r"\s*(>=|<=|==|>|<)\s*(\d+(?:\.\d+){0,2})\s*", clause)
        if not match:
            raise RshError("invalid_python_requirement", "Python constraint must use explicit comparisons.")
        expected = tuple(map(int, match.group(2).split(".")))
        expected += (0,) * (3 - len(expected))
        op = match.group(1)
        if not {">=": actual >= expected, "<=": actual <= expected, "==": actual == expected,
                ">": actual > expected, "<": actual < expected}[op]:
            return False
    return True


def format_argv(argv, replacements):
    try:
        return [argument.format_map(replacements) for argument in argv]
    except KeyError as exc:
        raise RshError("unknown_command_placeholder", f"Unknown command placeholder: {exc}") from exc
