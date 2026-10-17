"""Bounded public discovery, with independent offline snapshots and pinned projects."""
from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
import time
import urllib.request

from .core import COMMIT, PUBLIC_JSON_LIMIT, RshError, SKILL_ROOT, load_catalog, read_json, require_url, validate_catalog, write_json

BASE = "https://hub.superfastrobotics.com/catalog/v1/"
API_BASE = "https://api.superfastrobotics.com/v1/"
READ_TIMEOUT = 1.5
CACHE_SECONDS = 300
PUBLIC_LIMIT = PUBLIC_JSON_LIMIT


def cache_root():
    override = os.environ.get("RSH_CACHE_DIR")
    if override:
        return Path(override).expanduser()
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CACHE_HOME")
    return (Path(base) if base else Path.home() / ".cache") / "robot-skill-hub"


def client_headers(url):
    """Optional anonymous installation identity, sent only to the owned API."""
    headers = {"User-Agent": "robot-skill-hub/1", "Accept": "application/json"}
    if os.environ.get("RSH_TELEMETRY", "").lower() in ("off", "0", "false"):
        return {**headers, "DNT": "1", "X-RSH-Telemetry": "off"}
    if not url.startswith(API_BASE):
        return headers
    path = cache_root() / "anonymous-client-id"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            return headers
        if path.exists():
            if path.stat().st_nlink != 1:
                return headers
            with path.open(encoding="ascii") as stream:
                stored = stream.read(96).strip()
            value = stored.removeprefix("rsh-client-id-v1:") if stored.startswith("rsh-client-id-v1:") else ""
        else:
            value = secrets.token_hex(16)
            try:
                with path.open("x", encoding="ascii") as stream:
                    stream.write("rsh-client-id-v1:" + value + "\n")
            except FileExistsError:
                if path.is_symlink():
                    return headers
                if path.stat().st_nlink != 1:
                    return headers
                with path.open(encoding="ascii") as stream:
                    stored = stream.read(96).strip()
                value = stored.removeprefix("rsh-client-id-v1:") if stored.startswith("rsh-client-id-v1:") else ""
        if len(value) == 32 and all(c in "0123456789abcdef" for c in value):
            headers["X-RSH-Client"] = value
    except (OSError, UnicodeError):
        pass  # Identity and measurement are optional; discovery still works.
    return headers


def fetch_public(url):
    require_url(url, local_http=True)
    request = urllib.request.Request(url, headers=client_headers(url))
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=READ_TIMEOUT) as response:
        data = response.read(PUBLIC_LIMIT + 1)
    if len(data) > PUBLIC_LIMIT:
        raise RshError("catalog_too_large", "Public index exceeds 8 MiB.")
    return json.loads(data)


def index_data(value):
    if not isinstance(value, dict) or value.get("schema_version") != "1" or not isinstance(value.get("records"), list):
        raise RshError("invalid_index", "Expected schema_version 1 and a records array.")
    return value


def _read_cache(name):
    try:
        value = read_json(cache_root() / (name + ".json"))
        if not isinstance(value, dict) or not isinstance(value.get("fetched_at"), (int, float)):
            return None
        return value
    except (RshError, OSError, TypeError):
        return None


def _write_cache(name, value):
    try:
        write_json(cache_root() / (name + ".json"), {"fetched_at": time.time(), "data": value})
    except OSError:
        pass  # Read-only machines still use the retrieved data in this invocation.


def public_index(name, *, url=None, offline=False, refresh=False, diagnostics=None):
    """Return (index, origin); network failure is never required for discovery."""
    cached = _read_cache(name)
    failures = []
    def result(data, origin):
        if diagnostics is not None:
            diagnostics.update({"origin": origin, "publication_hub_commit": data.get("hub_commit"),
                                "fetched_at": time.time() if origin == "remote" else cached.get("fetched_at") if cached and origin.startswith("cache") else None,
                                "fallback_reasons": list(dict.fromkeys(failures))})
        return data, origin
    if cached:
        try:
            index_data(cached["data"])
        except (RshError, KeyError, TypeError):
            cached = None
            failures.append("invalid_cached_index")
    if cached and not refresh and time.time() - cached["fetched_at"] < CACHE_SECONDS:
        return result(cached["data"], "cache")
    if not offline:
        target = url or BASE + name + ".json"
        candidates = [API_BASE + "references", target] if name == "references" and target == BASE + "references.json" else [target]
        for candidate in candidates:
            try:
                data = index_data(fetch_public(candidate))
                _write_cache(name, data)
                return result(data, "remote")
            except (OSError, ValueError, TypeError, RshError) as error:
                failures.append(error.result["reason_code"] if isinstance(error, RshError) else "network_unavailable" if isinstance(error, OSError) else "invalid_index")
    if cached:
        return result(cached["data"], "cache_fallback")
    snapshot = SKILL_ROOT / "assets" / (name + ".snapshot.json")
    try:
        return result(index_data(read_json(snapshot)), "bundled_snapshot")
    except (OSError, RshError, ValueError, TypeError):
        failures.append("bundled_index_unavailable")
        return result({"schema_version": "1", "records": []}, "empty_snapshot")


def load_discovery(location=None, *, offline=False, refresh=False, latest=True):
    if location:
        # Explicit fixture/local/custom catalogs keep their original network contract.
        if offline and str(location).startswith(("https://", "http://")):
            raise RshError("offline_remote_catalog", "Use a local catalog file with --offline.")
        result = load_catalog(location)
        return {**result, "catalog_origin": "explicit"}
    cached = _read_cache("catalog")
    if cached:
        try:
            validate_catalog(cached["data"])
            if not COMMIT.fullmatch(str(cached["data"].get("hub_commit", ""))):
                raise RshError("invalid_catalog", "A published catalog needs an exact Hub commit.")
        except (RshError, KeyError, TypeError):
            cached = None
    catalog, origin = None, None
    if cached and (not latest or offline or (not refresh and time.time() - cached["fetched_at"] < CACHE_SECONDS)):
        catalog, origin = cached["data"], "cache"
    if catalog is None and latest and not offline:
        for url in (API_BASE + "catalog", BASE + "index.json"):
            try:
                candidate = validate_catalog(fetch_public(url))
                if not COMMIT.fullmatch(str(candidate.get("hub_commit", ""))):
                    raise RshError("invalid_catalog", "A published catalog needs an exact Hub commit.")
                catalog = candidate
                _write_cache("catalog", catalog)
                origin = "remote"
                break
            except (OSError, ValueError, TypeError, RshError):
                pass
    if catalog is None:
        catalog = cached["data"] if cached else load_catalog()
        origin = "cache_fallback" if cached else "bundled_snapshot"
    refs_diagnostics = {}
    refs, refs_origin = public_index("references", url=catalog.get("references_url"),
                                     offline=offline or not latest or origin == "bundled_snapshot",
                                     refresh=refresh, diagnostics=refs_diagnostics)
    return {**catalog, "references": refs, "catalog_origin": origin, "references_origin": refs_origin,
            "references_discovery": refs_diagnostics}


def pinned_project_catalog(catalog, project, skill_id):
    """Use a previously saved project record; never refresh an existing lock."""
    project = Path(project).expanduser().resolve()
    path = project / ".robot-skill-hub/locks" / (skill_id + ".json")
    if not path.resolve().is_relative_to(project):
        raise RshError("preparation_path_escape", "Project lock resolves outside the requested project.")
    if not path.is_file():
        return catalog
    lock = read_json(path)
    record = lock.get("record")
    if not isinstance(record, dict):
        return catalog  # Older locks retain the existing conflict checks in prepare.
    pinned = validate_catalog({"schema_version": "1", "hub_commit": lock.get("hub_commit"), "records": [record]})
    if (record.get("id") != skill_id or record["source"]["commit"] != lock.get("source_commit")
            or record["maintenance"]["record_version"] != lock.get("record_version")):
        raise RshError("invalid_project_lock", "Project record and lock pins differ.")
    return {**pinned, "catalog_origin": "project_lock"}
