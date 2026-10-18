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
SOURCE_REVISION = re.compile(r"^(?:[0-9a-f]{40}|sha256:[0-9a-f]{64})$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
IDENTIFIER = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
PUBLIC_JSON_LIMIT = 8 * 1024 * 1024


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
            # Runtime import avoids a module cycle while preserving the same
            # byte bound, redirect policy and telemetry opt-out as discovery.
            from .discovery import fetch_public
            catalog = fetch_public(str(location))
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


def lookup_preparation(catalog, skill_id):
    """Known source references have inspection instructions, not an adapter."""
    for record in catalog["records"]:
        if record["id"] == skill_id:
            return record
    for reference in catalog.get("references", {}).get("records", []):
        if isinstance(reference, dict) and reference.get("id") == skill_id:
            source = reference.get("source", {})
            raise RshError("source_reference_no_adapter", "This pinned source reference has no Hub preparation adapter.",
                           status="unsupported", next_action="open_source_reference", skill_id=skill_id,
                           kind="source_reference", hub_prepare=False, source_url=source.get("url"),
                           setup_url=reference.get("access", {}).get("setup_url") or reference.get("setup_url"),
                           **reference_acquisition(catalog, reference),
                           source_download_performed=False, environment_created=False, execution_performed=False)
    return lookup(catalog, skill_id)


ENVIRONMENT_FIELDS = ("runtime", "runtime_version", "robot", "controller", "observation", "os", "python", "architecture")


def preparation_arguments(skill_id, source_commit, record_version, environment=None):
    """Keep explicit discovery constraints with the selected recipe/source pins."""
    arguments = ["prepare", skill_id, "--expected-source-commit", source_commit,
                 "--expected-record-version", record_version]
    for field in ENVIRONMENT_FIELDS:
        value = (environment or {}).get(field)
        if value is None or str(value).strip().lower() in ("", "unknown"):
            continue
        option = "python-version" if field == "python" else field.replace("_", "-")
        # One argv item preserves custom labels beginning with a dash.
        arguments.append("--" + option + "=" + str(value))
    return arguments


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
    hub = catalog.get("references", {}).get("hub_commit", catalog.get("hub_commit")) if reference else catalog.get("hub_commit")
    commit = source.get("commit") or (source.get("revision") if reference else None)
    if (not isinstance(version, str) or not 1 <= len(version) <= 120
            or not COMMIT.fullmatch(str(hub or "")) or not (SOURCE_REVISION if reference else COMMIT).fullmatch(str(commit or ""))):
        return None
    return {"record_version": version, "hub_commit": hub, "source_commit": commit}


def reference_environment_matches(record, environment):
    """Filter discovery facts without manufacturing environment combinations."""
    supplied = {key: str(environment[key]).strip().lower() for key in ENVIRONMENT_FIELDS
                if environment.get(key) is not None and str(environment[key]).strip().lower() not in ("", "unknown")}
    if not supplied:
        return True
    combinations = record.get("compatibility", [])
    if isinstance(combinations, dict):
        combinations = [combinations]
    if isinstance(combinations, list) and any(isinstance(combo, dict) and all(
            isinstance(combo.get(key), str) and combo[key].strip().lower() == value
            for key, value in supplied.items()) for combo in combinations):
        return True
    if len(supplied) != 1:
        return False
    if "runtime" in supplied:
        return any(isinstance(record.get(key), str) and record[key].strip().lower() == supplied["runtime"]
                   for key in ("runtime", "framework"))
    if "robot" in supplied:
        robots = record.get("robots", [])
        return isinstance(robots, list) and any(isinstance(robot, str) and robot.strip().lower() == supplied["robot"] for robot in robots)
    return False


def discovery_metadata(catalog):
    """Expose independent reference freshness instead of implying a fresh aggregate."""
    return {"catalog_hub_commit": catalog.get("hub_commit"),
            "catalog_origin": catalog.get("catalog_origin", "explicit"),
            "references_hub_commit": catalog.get("references", {}).get("hub_commit"),
            "references_origin": catalog.get("references_origin", "explicit"),
            "references_discovery": catalog.get("references_discovery", {}),
            "discovery_scope": catalog.get("discovery_scope", "compatibility_view"),
            "catalog_coverage": catalog.get("coverage", {"complete": True}),
            "references_coverage": catalog.get("references", {}).get("coverage", {"complete": True}),
            "discovery_fallback_reasons": catalog.get("discovery_fallback_reasons", [])}


def validate_find_pagination(limit, offset, hub_commit, *, maximum_limit=50):
    if type(limit) is not int or not 1 <= limit <= maximum_limit or type(offset) is not int or not 0 <= offset <= 1000000:
        raise RshError("invalid_pagination", f"Search requires limit 1..{maximum_limit} and offset 0..1000000.")
    if hub_commit is not None and (not isinstance(hub_commit, str) or not COMMIT.fullmatch(hub_commit)):
        raise RshError("invalid_hub_commit", "Use the exact published Hub commit returned by the previous search page.")


def query_terms(value):
    """Rewrite only standalone A*/D*/RRT* queries; document words stay unchanged."""
    import unicodedata

    def adjacent_identifier(character):
        return character in "_*" or unicodedata.category(character)[0] in "LNM"

    def algorithm(match):
        before = value[match.start() - 1] if match.start() else None
        after = value[match.end()] if match.end() < len(value) else None
        if any(character is not None and adjacent_identifier(character) for character in (before, after)):
            return match.group()
        return match.group()[:-1].lower() + "star"

    return re.findall(r"[^\W_]+", re.sub(r"(?:[rR][rR][tT]|[aAdD])\*", algorithm, value).lower())


def find(catalog, query, environment, limit=3, *, offset=0, hub_commit=None):
    validate_find_pagination(limit, offset, hub_commit)
    recipe_hub = catalog.get("hub_commit")
    reference_hub = catalog.get("references", {}).get("hub_commit", recipe_hub)
    if hub_commit is not None and (recipe_hub != hub_commit or reference_hub != hub_commit):
        raise RshError("catalog_generation_changed", "The available recipe/reference snapshots differ from the requested search generation.",
                       next_action="restart_search_or_use_original_catalog_snapshot",
                       expected_hub_commit=hub_commit, catalog_hub_commit=recipe_hub, references_hub_commit=reference_hub)
    # Match whole-word prefixes, never arbitrary substrings such as DWA inside
    # hardware. Keep Unicode words and distinguish punctuation from browsing.
    tokens = query_terms(query)
    punctuation_only = bool(query.strip()) and not tokens
    results = []
    for record in catalog["records"]:
        matched = compatibility(record, environment)
        if matched["compatibility_status"] == "incompatible":
            continue
        words = re.findall(r"[^\W_]+", " ".join([record["id"], record["name"], record["summary"],
                           *record["capabilities"], *record.get("aliases", [])]).lower())
        score = sum(any(word.startswith(token) for word in words) for token in tokens)
        if punctuation_only or score != len(tokens):
            continue
        results.append({"id": record["id"], "name": record["name"], "summary": record["summary"],
                        "kind": "preparation_recipe", "hub_prepare": True, "next_action": "inspect_recipe",
                        "source_commit": record["source"]["commit"], "record_version": record["maintenance"]["record_version"],
                        "memory_base": selection_base(catalog, record),
                        "prepare_args": preparation_arguments(record["id"], record["source"]["commit"],
                                                              record["maintenance"]["record_version"], environment),
                        "match_reason": ["Explicit environment constraints match a documented combination."]
                        + (["Environment is incomplete; compatibility is unconfirmed."] if matched["missing_requirements"] else []),
                        "missing_requirements": matched["missing_requirements"],
                        "compatibility_status": matched["compatibility_status"],
                        "evidence_level": record["evidence"]["level"], "_score": score})
    for record in catalog.get("references", {}).get("records", []):
        if not isinstance(record, dict):
            continue
        framework = str(record.get("framework", "")).lower()
        if not reference_environment_matches(record, environment):
            continue
        if (not IDENTIFIER.fullmatch(str(record.get("id", ""))) or not isinstance(record.get("source"), dict)
                or not SOURCE_REVISION.fullmatch(str(record["source"].get("commit") or record["source"].get("revision", "")))):
            continue
        words = re.findall(r"[^\W_]+", " ".join([record["id"], str(record.get("name", "")), str(record.get("summary", "")),
                          framework, *record.get("capabilities", []), *record.get("aliases", []), *record.get("robots", []),
                          *record.get("robot_types", [])]).lower())
        score = sum(any(word.startswith(token) for word in words) for token in tokens)
        if punctuation_only or score != len(tokens):
            continue
        results.append({"id": record["id"], "name": record.get("name", record["id"]),
                        "summary": record.get("summary", ""), "kind": "source_reference", "hub_prepare": False,
                        "next_action": "open_source_reference", "source_url": record["source"].get("url"),
                        "source_commit": record["source"].get("commit") or record["source"].get("revision"), "framework": framework,
                        **({"robot_types": list(record["robot_types"])} if record.get("robot_types") else {}),
                        "memory_base": selection_base(catalog, record, reference=True),
                        "compatibility_status": "unknown", "missing_requirements": ["upstream_environment_review"],
                        "match_reason": ["Pinned upstream source reference; no Hub preparation adapter or environment compatibility claim."],
                        "evidence_level": record.get("evidence", {}).get("level", "source_reviewed"), "_score": score})
    results.sort(key=lambda item: (item["id"] != query.lower(), -item["_score"], not item["hub_prepare"], item["id"]))
    for item in results:
        item.pop("_score")
    stable_hub = recipe_hub if isinstance(recipe_hub, str) and COMMIT.fullmatch(recipe_hub) and recipe_hub == reference_hub else None
    next_page = None
    if offset + limit < len(results):
        next_page = {"q": query, **{key: str(environment[key]) for key in ENVIRONMENT_FIELDS
                     if environment.get(key) not in (None, "", "unknown")}, "limit": limit, "offset": offset + limit,
                     **({"hub_commit": stable_hub} if stable_hub else {})}
    return {"status": "ready", "results": results[offset:offset + limit], "total": len(results),
            "search_semantics": "all_terms_word_prefix",
            "offset": offset, "limit": limit, "next": next_page,
            "pagination_stability": "single_generation" if stable_hub else "snapshot_required",
            **({"pagination_note": "Recipe and reference generations differ or are unknown; use one catalog snapshot for stable pagination."}
               if not stable_hub else {}), "execution_performed": False, **discovery_metadata(catalog)}


def reference_acquisition(catalog, reference):
    """Expose a pinned one-file route without making inspection depend on fetch support."""
    from .acquisition import plan_source
    hub = catalog.get("references", {}).get("hub_commit", catalog.get("hub_commit"))
    try:
        plan = plan_source(reference, hub)
    except RshError as error:
        return {"source_acquisition": {"status": "unsupported", "reason_code": error.result["reason_code"],
                                       "execution_performed": False}}
    return {"source_acquisition": plan, "fetch_source_args": plan["fetch_args"]}


def inspect(catalog, skill_id):
    for reference in catalog.get("references", {}).get("records", []):
        if reference.get("id") == skill_id:
            return {"status": "ready", **reference, "kind": "source_reference", "hub_prepare": False,
                    "memory_base": selection_base(catalog, reference, reference=True),
                    **reference_acquisition(catalog, reference),
                    "next_action": "open_source_reference", "execution_performed": False, **discovery_metadata(catalog)}
    record = lookup(catalog, skill_id)
    return {"status": "ready", **record, "commit": record["source"]["commit"],
            "kind": "preparation_recipe", "hub_prepare": True,
            "memory_base": selection_base(catalog, record),
            "prepare_args": ["prepare", record["id"], "--expected-source-commit", record["source"]["commit"],
                             "--expected-record-version", record["maintenance"]["record_version"]],
            "entrypoint": record["invocation"]["entrypoint"], "inputs": record["invocation"].get("inputs"),
            "outputs": record["invocation"].get("outputs"), "example": record["invocation"].get("example"),
            "execution_performed": False, **discovery_metadata(catalog)}


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
