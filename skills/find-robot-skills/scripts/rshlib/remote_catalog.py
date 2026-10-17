"""Bounded public search and per-ID reads; no credentials or artifact execution."""
from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.parse

from . import discovery
from .core import (COMMIT, ENVIRONMENT_FIELDS, SHA256, SOURCE_REVISION, RshError,
                   compatibility, reference_environment_matches, require_url, validate_record)

IDENT = re.compile(r"[a-z0-9][a-z0-9-]{0,79}\Z")


def _need(condition, message):
    if not condition:
        raise RshError("invalid_public_discovery", message, next_action="use_cached_or_bundled_discovery")


def _hub(value):
    _need(isinstance(value, dict) and value.get("schema_version") == "1" and COMMIT.fullmatch(str(value.get("hub_commit", ""))),
          "Public discovery must identify an exact Hub commit.")
    return value["hub_commit"]


def _reference(record):
    _need(isinstance(record, dict) and IDENT.fullmatch(str(record.get("id", ""))), "Invalid source reference ID.")
    _need(record.get("kind") in ("official_example", "community_skill"), "Unsupported public reference kind.")
    source = record.get("source", {})
    _need(isinstance(source, dict) and SOURCE_REVISION.fullmatch(str(source.get("commit") or source.get("revision", "")))
          and SHA256.fullmatch(str(source.get("sha256", ""))), "Source reference lacks immutable pins.")
    require_url(source.get("url"))
    license_info = record.get("license", {})
    _need(isinstance(license_info, dict) and isinstance(license_info.get("spdx"), str) and license_info["spdx"], "Source reference lacks a license.")
    require_url(license_info.get("url"))
    access = record.get("access", {})
    _need(isinstance(access, dict) and access.get("mode") == "source_reference" and access.get("hub_prepare") is False,
          "A source reference must identify its preparation boundary.")
    _need(isinstance(record.get("evidence"), dict) and record["evidence"].get("runtime_verification") == "not_run",
          "Public source references must retain their separate execution evidence.")


def _record_catalog(value, skill_id, origin, fetched_at=None):
    hub = _hub(value)
    record = value.get("record")
    _need(isinstance(record, dict) and record.get("id") == skill_id, "Public record identity changed.")
    _need(len(json.dumps(record, ensure_ascii=False).encode("utf-8")) <= 256 * 1024, "Public record exceeds its read limit.")
    recipe = "preparation" in record and "archive_sha256" in record.get("source", {})
    if recipe:
        validate_record(record)
    else:
        _reference(record)
    coverage = {"complete": False, "scope": "selected_record", "included_records": 1}
    return {"schema_version": "1", "hub_commit": hub, "records": [record] if recipe else [], "coverage": coverage,
            "references": {"schema_version": "1", "hub_commit": hub, "records": [] if recipe else [record], "coverage": coverage},
            "catalog_origin": origin, "references_origin": origin,
            "references_discovery": {"origin": origin, "publication_hub_commit": hub, "fetched_at": fetched_at, "fallback_reasons": []},
            "discovery_scope": "selected_record"}


def selected_catalog(skill_id, *, offline=False, refresh=False, persist=True):
    _need(isinstance(skill_id, str) and IDENT.fullmatch(skill_id), "Use an exact public skill ID.")
    key = "api-record-" + skill_id
    cached = discovery._read_cache(key)
    if cached:
        try:
            _record_catalog(cached["data"], skill_id, "api_cache", cached["fetched_at"])
        except (RshError, TypeError, KeyError):
            cached = None
    if cached and (offline or not refresh and time.time() - cached["fetched_at"] < discovery.CACHE_SECONDS):
        return _record_catalog(cached["data"], skill_id, "api_cache", cached["fetched_at"])
    if not offline:
        try:
            value = discovery.fetch_public(discovery.API_BASE + "skills/" + skill_id, max_bytes=512 * 1024)
            result = _record_catalog(value, skill_id, "remote_api", time.time())
            if persist:
                discovery._write_cache(key, value)
            return result
        except (OSError, ValueError, TypeError, RshError):
            if cached:
                result = _record_catalog(cached["data"], skill_id, "api_cache_fallback", cached["fetched_at"])
                result["references_discovery"]["fallback_reasons"] = ["public_record_unavailable"]
                return result
            raise
    raise RshError("public_record_not_cached", "No individually cached public record is available.", next_action="use_bundled_discovery")


def _search(value, environment, limit, origin, fetched_at=None, *, params=None):
    hub = _hub(value)
    rows, total = value.get("results"), value.get("total")
    _need(isinstance(rows, list) and len(rows) <= limit and type(total) is int and total >= len(rows), "Invalid bounded search result.")
    _need(len(rows) == min(limit, total) and (value.get("next") is not None) == (total > limit), "Search page omits rows or pagination.")
    _need(value.get("execution_performed") is False and value.get("offset") == 0 and value.get("limit") == limit
          and isinstance(value.get("coverage"), dict) and value["coverage"].get("complete") is True,
          "Search must remain read-only, complete and bounded by its requested pagination.")
    next_page = value.get("next")
    if next_page is not None:
        _need(isinstance(params, dict) and next_page == {**params, "offset": limit, "hub_commit": hub}
              and total > len(rows) and len(rows) == limit,
              "Search pagination must retain the exact bounded generation.")
    results = []
    seen = set()
    for row in rows:
        _need(isinstance(row, dict) and IDENT.fullmatch(str(row.get("id", "")))
              and row.get("kind") in ("preparation_recipe", "source_reference")
              and SHA256.fullmatch(str(row.get("record_sha256", "")))
              and SHA256.fullmatch(str(row.get("source_sha256", "")))
              and SOURCE_REVISION.fullmatch(str(row.get("source_commit", "")))
              and isinstance(row.get("record_version"), str) and 1 <= len(row["record_version"]) <= 120,
              "Search row lacks an exact source and record identity.")
        _need(row["id"] not in seen, "Search returned a duplicate record identity.")
        seen.add(row["id"])
        recipe = row["kind"] == "preparation_recipe"
        _need(row.get("hub_prepare") is recipe, "Search preparation flags conflict.")
        _need(isinstance(row.get("robot_types", []), list) and all(
            isinstance(value, str) and 0 < len(value) <= 80 for value in row.get("robot_types", [])),
            "Robot type discovery labels must be bounded strings.")
        _need(isinstance(row.get("compatibility", []), list)
              and all(isinstance(item, dict) for item in row.get("compatibility", [])), "Invalid declared environment combinations.")
        if recipe:
            _need(COMMIT.fullmatch(row["source_commit"]), "Recipes require an exact Git source commit.")
            _need(isinstance(row.get("python_requirement"), str) and row["python_requirement"],
                  "Recipe search must preserve its explicit Python constraint.")
            matched = compatibility({"compatibility": row.get("compatibility", []),
                                     "requirements": {"python": row["python_requirement"]}}, environment)
            _need(matched["compatibility_status"] != "incompatible", "Remote search ignored an explicit recipe environment constraint.")
        else:
            _need(row["record_version"] == "source-" + row["source_sha256"], "Source reference version differs from its file hash.")
            _need(reference_environment_matches(row, environment), "Remote search ignored an explicit source environment constraint.")
            matched = {"compatibility_status": "unknown", "missing_requirements": ["upstream_environment_review"]}
        result = {**row, "memory_base": {"hub_commit": hub, "record_version": row["record_version"], "source_commit": row["source_commit"]},
                  "next_action": "inspect_recipe" if recipe else "open_source_reference",
                  "compatibility_status": matched["compatibility_status"], "missing_requirements": matched["missing_requirements"],
                  "match_reason": ["Pinned public search result; inspect its exact source, license and execution evidence before use."]}
        if recipe:
            result["prepare_args"] = ["prepare", row["id"], "--expected-source-commit", row["source_commit"], "--expected-record-version", row["record_version"]]
        results.append(result)
    return {"status": "ready", "results": results, "total": total, "execution_performed": False,
            "catalog_hub_commit": hub, "references_hub_commit": hub, "catalog_origin": origin, "references_origin": origin,
            "references_discovery": {"origin": origin, "publication_hub_commit": hub, "fetched_at": fetched_at, "fallback_reasons": []},
            "search_backend": value.get("backend", "published_api"), "search_semantics": value.get("search_semantics"), "counts": value.get("counts"),
            "next": value.get("next"), "discovery_scope": "complete_public_query"}


def search(query, environment, limit=3, *, refresh=False):
    params = {"q": query, "limit": limit}
    for key in ENVIRONMENT_FIELDS:
        if environment.get(key) not in (None, "", "unknown"):
            text = str(environment[key])
            _need(len(text) <= 80, "Environment filter exceeds its public query bound.")
            params[key] = text
    _need(isinstance(query, str) and len(query) <= 240, "Search query exceeds its public bound.")
    key = "api-search-" + hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()
    cached = discovery._read_cache(key)
    if cached:
        try:
            _search(cached["data"], environment, limit, "api_cache", cached["fetched_at"], params=params)
        except (RshError, KeyError, TypeError):
            cached = None
    if cached and not refresh and time.time() - cached["fetched_at"] < discovery.CACHE_SECONDS:
        return _search(cached["data"], environment, limit, "api_cache", cached["fetched_at"], params=params)
    try:
        value = discovery.fetch_public(discovery.API_BASE + "search?" + urllib.parse.urlencode(params), max_bytes=512 * 1024)
        result = _search(value, environment, limit, "remote_api", time.time(), params=params)
        discovery._write_cache(key, value)
        return result
    except (OSError, ValueError, TypeError, RshError):
        if cached:
            result = _search(cached["data"], environment, limit, "api_cache_fallback", cached["fetched_at"], params=params)
            result["references_discovery"]["fallback_reasons"] = ["public_search_unavailable"]
            return result
        raise


def current_catalog():
    value = discovery.fetch_public(discovery.BASE + "version.json", max_bytes=128 * 1024)
    hub = _hub(value)
    return {"schema_version": "1", "hub_commit": hub, "records": [], "catalog_origin": "remote_version",
            "coverage": {"complete": False, "scope": "generation_metadata", "included_records": 0},
            "discovery_scope": "generation_metadata", "counts": value.get("counts", {})}
