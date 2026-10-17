"""Acquire one immutable source file as inert data, without preparing or executing it."""
from __future__ import annotations

import copy
import ctypes
import errno
import hashlib
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import ssl
import stat
import sys
import tempfile
import threading
import time
import urllib.parse

from .core import COMMIT, IDENTIFIER, SHA256, SOURCE_REVISION, RshError, lookup, selection_base

MAX_SOURCE_BYTES = 8 * 1024 * 1024
MAX_METADATA_BYTES = 256 * 1024
MAX_SAFE_INTEGER = 9007199254740991
SOCKET_TIMEOUT = 10
TRANSFER_TIMEOUT = 30
ARTIFACT_NAME = "artifact.source"
MANIFEST_NAME = "manifest.json"
GITHUB_REPOSITORY = re.compile(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
SECRET = re.compile(r"\b(?:github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|rsh_[A-Za-z0-9_-]{43}|sk-[A-Za-z0-9_-]{24,}|AKIA[A-Z0-9]{16})\b|Bearer\s+[A-Za-z0-9._~+/-]{16,}|-----BEGIN [A-Z ]*PRIVATE KEY-----", re.I)
SECRET_QUERY_KEY = re.compile(r"token|auth|password|passwd|secret|credential|signature|api.?key|access.?key|^sig$|^key$|^x-amz-|^x-goog-", re.I)


def _flags(request=False, downloaded=False):
    return {"source_download_only": True, "source_download_performed": downloaded,
            "source_request_performed": request, "execution_performed": False,
            "environment_created": False, "installed_as_skill": False, "hub_prepare": False}


def _fail(code, message, *, request=False, downloaded=False, action="inspect_source_metadata"):
    raise RshError(code, message, next_action=action, **_flags(request, downloaded))


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _metadata(value):
    try:
        encoded = _canonical(value)
    except (TypeError, ValueError, UnicodeError):
        _fail("invalid_source_metadata", "Source provenance must be finite JSON data.")
    if len(encoded) > MAX_METADATA_BYTES:
        _fail("source_metadata_too_large", "Source provenance exceeds its metadata byte limit.")
    if SECRET.search(encoded.decode("utf-8")):
        _fail("source_metadata_contains_credentials", "Remove credentials from source provenance.")
    return json.loads(encoded)


def _safe_path(path):
    if (not isinstance(path, str) or not 0 < len(path) <= 4096 or "\\" in path or ":" in path
            or any(ord(c) < 32 or ord(c) == 127 for c in path)
            or any(piece in ("", ".", "..") for piece in path.split("/"))):
        _fail("invalid_source_path", "The selected source needs one safe repository-relative file path.")
    return path


def _public_ip(value):
    try:
        address = ipaddress.ip_address(value)
        return address.is_global and not address.is_multicast and not address.is_unspecified
    except ValueError:
        return False


def _url(value):
    if (not isinstance(value, str) or not 0 < len(value) <= 8192 or "\\" in value
            or any(ord(c) <= 32 or ord(c) == 127 for c in value) or SECRET.search(value)):
        _fail("unsafe_source_url", "Use a public HTTPS source URL without credentials or control characters.")
    try:
        parsed = urllib.parse.urlsplit(value)
        if any(ord(c) < 32 or ord(c) == 127 for c in urllib.parse.unquote(value)):
            raise ValueError()
        host = parsed.hostname
        port = parsed.port or 443
        if parsed.scheme != "https" or not host or parsed.username is not None or parsed.password is not None or parsed.fragment:
            raise ValueError()
        host = host.encode("idna").decode("ascii").lower()
        if "%" in host or host.endswith(".") or host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".lan", ".home")):
            raise ValueError()
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if (re.fullmatch(r"[0-9.]+", host) or "." not in host or len(host) > 253 or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in host.split("."))):
                raise ValueError()
        else:
            if not _public_ip(str(address)):
                raise ValueError()
        query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True, max_num_fields=32)
        if any(SECRET_QUERY_KEY.search(key) or SECRET.search(val) or "\r" in key + val or "\n" in key + val for key, val in query):
            raise ValueError()
        if not 1 <= port <= 65535:
            raise ValueError()
    except (ValueError, TypeError, UnicodeError):
        _fail("unsafe_source_url", "Use a public HTTPS source URL without credentials, private addresses or secret query parameters.")
    return parsed, host, port


def plan_source(record, catalog_hub_commit, expected_source_revision=None, expected_source_sha256=None):
    """Validate a pinned file and return a plan without filesystem or network access."""
    if not isinstance(record, dict) or "preparation" in record or "archive_sha256" in record.get("source", {}):
        _fail("source_is_preparation_recipe", "Use prepare for a Hub preparation recipe.", action="use_prepare")
    ident = record.get("id")
    access = record.get("access", {})
    if (not isinstance(ident, str) or len(ident) > 80 or not IDENTIFIER.fullmatch(ident)
            or not isinstance(access, dict) or access.get("mode") != "source_reference" or access.get("hub_prepare") is not False):
        _fail("invalid_source_reference", "Select a source reference with an explicit source-only boundary.")
    source, license_info = record.get("source"), record.get("license")
    if not isinstance(source, dict) or not isinstance(license_info, dict) or not license_info.get("spdx"):
        _fail("invalid_source_metadata", "Source identity and its unchanged license context are required.")
    source, license_info = _metadata(source), _metadata(license_info)
    revision = source.get("commit") or source.get("revision")
    sha = source.get("sha256")
    size = source.get("bytes")
    if (not isinstance(revision, str) or not SOURCE_REVISION.fullmatch(revision)
            or not isinstance(sha, str) or not SHA256.fullmatch(sha)
            or source.get("commit") and source.get("revision") and source["commit"] != source["revision"]):
        _fail("invalid_source_pin", "An exact source revision and full SHA-256 are required.")
    if revision.startswith("sha256:") and revision != "sha256:" + sha:
        _fail("invalid_source_pin", "The content-addressed revision must equal the source SHA-256.")
    if type(size) is not int or not 0 < size <= MAX_SAFE_INTEGER:
        _fail("invalid_source_size", "Declared source bytes must be a positive safe integer.")
    if size > MAX_SOURCE_BYTES:
        _fail("source_too_large", "This single-file acquisition exceeds the fixed 8 MiB limit.")
    if ((expected_source_revision is not None and expected_source_revision != revision)
            or (expected_source_sha256 is not None and expected_source_sha256 != sha)):
        _fail("selected_source_changed", "The selected source differs from the explicit revision or SHA-256.", action="inspect_selected_source")
    path = _safe_path(source.get("path"))
    _url(source.get("url"))
    if license_info.get("url"):
        _url(license_info["url"])
    repository = source.get("repository")
    if isinstance(repository, str) and GITHUB_REPOSITORY.fullmatch(repository):
        if any(part in (".", "..") for part in repository.removeprefix("https://github.com/").split("/")):
            _fail("invalid_source_repository", "The pinned GitHub repository identity is invalid.")
        if not COMMIT.fullmatch(revision):
            _fail("invalid_source_pin", "A GitHub source requires its full Git commit.")
        source_url = repository.replace("https://github.com/", "https://raw.githubusercontent.com/") + "/" + revision + "/" + urllib.parse.quote(path, safe="/")
        if source.get("raw_url") is not None and source["raw_url"] != source_url:
            _fail("source_url_pin_mismatch", "The raw source URL disagrees with its pinned repository, commit and path.")
    else:
        source_url = source["url"]
        parsed, _, _ = _url(source_url)
        if COMMIT.fullmatch(revision) and revision not in [urllib.parse.unquote(segment) for segment in parsed.path.split("/")]:
            _fail("source_url_pin_mismatch", "A non-GitHub Git source URL must contain the exact commit as a path segment.")
        if source.get("raw_url") is not None and source["raw_url"] != source_url:
            _fail("source_url_pin_mismatch", "The direct source URL disagrees with the selected pinned URL.")
    _url(source_url)
    base = selection_base({"hub_commit": catalog_hub_commit}, {"source": source}, reference=True)
    if base is None:
        _fail("invalid_source_base", "The reference requires its own exact published Hub and source pins.")
    identity = hashlib.sha256(_canonical({"skill_id": ident, "source": source, "license": license_info})).hexdigest()
    result = {"status": "ready", "reason_code": "source_acquisition_plan", "skill_id": ident,
            "interpretation": "data_only", "kind": "source_reference", "base": base,
            "source": source, "license": license_info, "original_path": path,
            "source_revision": revision, "source_sha256": sha, "source_bytes": size,
            "source_url": source_url, "acquisition_id": identity, "max_source_bytes": MAX_SOURCE_BYTES,
            "planned_network": [source_url], "next_action": "fetch_pinned_source",
            "fetch_args": ["fetch-source", ident, "--expected-source-revision", revision, "--expected-source-sha256", sha],
            **_flags()}
    if len(_canonical(_manifest(result))) + 1 > MAX_METADATA_BYTES:
        _fail("source_metadata_too_large", "Acquisition provenance exceeds its metadata byte limit.")
    return result


def _addresses(host, port):
    try:
        answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
    except OSError:
        _fail("source_dns_unavailable", "The public source hostname could not be resolved.")
    if not answers or any(family not in (socket.AF_INET, socket.AF_INET6) or not _public_ip(sockaddr[0]) for family, _, _, _, sockaddr in answers):
        _fail("private_source_address", "Every resolved source address must be public; no source request was sent.")
    return [(family, sockaddr) for family, _, _, _, sockaddr in answers]


def _download(url, expected_bytes, expected_sha256):
    parsed, host, port = _url(url)
    addresses = _addresses(host, port)
    request_started = False
    connection = None
    response = None
    raw_socket = None
    tls_socket = None
    deadline = time.monotonic() + TRANSFER_TIMEOUT
    def interrupt_transfer():
        resource = tls_socket if tls_socket is not None else raw_socket
        if resource is not None:
            try:
                resource.shutdown(socket.SHUT_RDWR)
                resource.close()
            except OSError:
                pass
    watchdog = threading.Timer(TRANSFER_TIMEOUT, interrupt_transfer)
    watchdog.daemon = True
    def remaining_timeout():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _fail("source_timeout", "The bounded source transfer timed out.", request=request_started)
        return min(SOCKET_TIMEOUT, remaining)
    try:
        watchdog.start()
        family, sockaddr = addresses[0]
        raw_socket = socket.socket(family, socket.SOCK_STREAM)
        raw_socket.settimeout(remaining_timeout())
        # Connect to the already validated numeric sockaddr; there is no second DNS lookup.
        raw_socket.connect(sockaddr)
        raw_socket.settimeout(remaining_timeout())
        tls_socket = ssl.create_default_context().wrap_socket(raw_socket, server_hostname=host)
        connection = http.client.HTTPSConnection(host, port=port, timeout=SOCKET_TIMEOUT)
        connection.sock = tls_socket
        target = urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
        authority = ("[" + host + "]" if ":" in host else host) + (":" + str(port) if port != 443 else "")
        connection.putrequest("GET", target, skip_host=True, skip_accept_encoding=True)
        for key, value in {"Host": authority, "User-Agent": "robot-skill-hub-source-acquisition/1", "Accept": "application/octet-stream",
                           "DNT": "1", "X-RSH-Telemetry": "off", "Connection": "close"}.items():
            connection.putheader(key, value)
        tls_socket.settimeout(remaining_timeout())
        request_started = True
        connection.endheaders()
        tls_socket.settimeout(remaining_timeout())
        # This is one request on a socket we own. HTTPConnection.getresponse()
        # closes connection.sock for server-close responses, which can invalidate
        # later timeout updates once HTTPResponse finishes its socket file.
        # Parse directly and retain socket ownership through body verification.
        response = http.client.HTTPResponse(tls_socket, method="GET")
        response.begin()
        if 300 <= response.status < 400:
            _fail("source_redirect_refused", "Pinned source redirects are not followed.", request=True)
        if response.status != 200:
            _fail("source_http_error", "The pinned source did not return a successful file response.", request=True)
        if response.getheader("Content-Encoding", "identity").lower() not in ("", "identity"):
            _fail("source_encoding_unsupported", "Compressed source transfer encoding is not accepted.", request=True)
        declared = response.getheader("Content-Length")
        if declared is not None and (not re.fullmatch(r"[0-9]+", declared) or int(declared) != expected_bytes):
            _fail("source_size_mismatch", "The source response size disagrees with its declared byte pin.", request=True)
        data = bytearray()
        digest = hashlib.sha256()
        while True:
            tls_socket.settimeout(remaining_timeout())
            chunk = response.read(min(65536, expected_bytes + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
            if len(data) > expected_bytes or len(data) > MAX_SOURCE_BYTES:
                _fail("source_size_mismatch", "The source body exceeds its pinned byte count.", request=True)
            digest.update(chunk)
        if len(data) != expected_bytes:
            _fail("source_size_mismatch", "The source body disagrees with its pinned byte count.", request=True)
        if digest.hexdigest() != expected_sha256:
            _fail("source_hash_mismatch", "The source body disagrees with its pinned SHA-256.", request=True)
        return bytes(data)
    except RshError:
        raise
    except (OSError, ValueError, http.client.HTTPException):
        _fail("source_unavailable", "The bounded HTTPS source transfer failed; no server error text was retained.", request=request_started)
    finally:
        watchdog.cancel()
        for resource in (response, connection, tls_socket, raw_socket):
            if resource is not None:
                try:
                    resource.close()
                except OSError:
                    pass


def _paths(project, identity):
    supplied = Path(project).expanduser().absolute()
    if any(path.is_symlink() for path in [supplied, *supplied.parents]):
        _fail("source_path_escape", "Source acquisition does not use symlinked project paths.")
    root = supplied.resolve()
    paths = [root, root / ".robot-skill-hub", root / ".robot-skill-hub/source-files"]
    paths.append(paths[-1] / identity)
    for path in paths:
        if path.is_symlink() or not path.resolve().is_relative_to(root) or path.exists() and not path.is_dir():
            _fail("source_path_escape", "A managed acquisition directory is linked or conflicts with existing data.")
    return root, paths[-2], paths[-1]


def _manifest(plan):
    return {"schema_version": "1", "interpretation": "data_only", "acquisition_id": plan["acquisition_id"],
            "skill_id": plan["skill_id"], "base": copy.deepcopy(plan["base"]),
            "source": copy.deepcopy(plan["source"]), "license": copy.deepcopy(plan["license"]),
            "original_path": plan["original_path"], "source_url": plan["source_url"],
            "source_revision": plan["source_revision"], "source_sha256": plan["source_sha256"],
            "source_bytes": plan["source_bytes"], "artifact_filename": ARTIFACT_NAME,
            "source_download_only": True, "execution_performed": False, "environment_created": False, "installed_as_skill": False}


def _regular(path, maximum):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > maximum:
        _fail("source_cache_conflict", "The existing acquisition contains a linked, oversized or non-regular file.")


def _cached(target, plan):
    manifest_path, artifact_path = target / MANIFEST_NAME, target / ARTIFACT_NAME
    try:
        _regular(manifest_path, MAX_METADATA_BYTES)
        _regular(artifact_path, plan["source_bytes"])
        with manifest_path.open("rb") as stream:
            manifest = json.loads(stream.read(MAX_METADATA_BYTES + 1))
        expected = _manifest(plan)
        base = manifest.get("base") if isinstance(manifest, dict) else None
        if (not isinstance(base, dict) or set(base) != {"hub_commit", "record_version", "source_commit"}
                or not COMMIT.fullmatch(str(base.get("hub_commit", "")))
                or any(base.get(key) != plan["base"][key] for key in ("record_version", "source_commit"))):
            _fail("source_cache_conflict", "The existing acquisition has an invalid original source base.")
        expected["base"] = base
        if manifest != expected:
            _fail("source_cache_conflict", "The existing acquisition does not match this immutable source and license context.")
        with artifact_path.open("rb") as stream:
            data = stream.read(plan["source_bytes"] + 1)
        if len(data) != plan["source_bytes"] or hashlib.sha256(data).hexdigest() != plan["source_sha256"]:
            _fail("source_cache_conflict", "The existing source file failed size or SHA-256 verification; it was not overwritten.")
        return manifest
    except RshError:
        raise
    except (OSError, ValueError, TypeError, KeyError, UnicodeError):
        _fail("source_cache_conflict", "The existing acquisition is incomplete or invalid; it was not overwritten.")


def catalog_from_manifest(manifest_path, project, skill_id):
    """Select one verified managed acquisition's original pins, without discovery."""
    try:
        if not isinstance(skill_id, str) or len(skill_id) > 80 or not IDENTIFIER.fullmatch(skill_id):
            _fail("invalid_source_id", "Use an exact catalog source-reference ID.")
        supplied = Path(manifest_path).expanduser().absolute()
        identity = supplied.parent.name
        if supplied.name != MANIFEST_NAME or not SHA256.fullmatch(identity):
            _fail("invalid_source_manifest", "Select one explicit managed source acquisition manifest.")
        _, _, target = _paths(project, identity)
        if supplied != target / MANIFEST_NAME:
            _fail("source_path_escape", "The selected source manifest must belong to this project's managed acquisition folder.")
        _regular(supplied, MAX_METADATA_BYTES)
        with supplied.open("rb") as stream:
            manifest = json.loads(stream.read(MAX_METADATA_BYTES + 1))
        if (not isinstance(manifest, dict) or manifest.get("schema_version") != "1"
                or manifest.get("interpretation") != "data_only"
                or manifest.get("artifact_filename") != ARTIFACT_NAME
                or manifest.get("source_download_only") is not True
                or any(manifest.get(key) is not False for key in ("execution_performed", "environment_created", "installed_as_skill"))
                or type(manifest.get("source_bytes")) is not int):
            _fail("invalid_source_manifest", "The selected manifest does not describe a bounded inert source acquisition.")
        if manifest.get("skill_id") != skill_id:
            _fail("source_manifest_id_mismatch", "The selected source manifest belongs to a different source-reference ID.")
        base = manifest.get("base")
        if (not isinstance(base, dict) or set(base) != {"hub_commit", "record_version", "source_commit"}
                or any(not isinstance(base.get(key), str) for key in base)
                or not COMMIT.fullmatch(base["hub_commit"])):
            _fail("invalid_source_manifest", "The selected manifest requires its exact original Hub and source base.")
        record = {"id": skill_id, "kind": "source_reference",
                  "source": manifest.get("source"), "license": manifest.get("license"),
                  "access": {"mode": "source_reference", "hub_prepare": False}}
        prepared = plan_source(record, base["hub_commit"])
        if prepared["acquisition_id"] != identity or prepared["base"] != base:
            _fail("invalid_source_manifest", "The selected manifest's identity or original base does not match its source pins.")
        verified = _cached(target, prepared)
        coverage = {"complete": False, "scope": "selected_record", "included_records": 1}
        return {"schema_version": "1", "hub_commit": verified["base"]["hub_commit"], "records": [],
                "references": {"schema_version": "1", "hub_commit": verified["base"]["hub_commit"],
                               "records": [record], "coverage": dict(coverage)},
                "coverage": coverage, "catalog_origin": "source_acquisition_manifest",
                "references_origin": "source_acquisition_manifest", "discovery_scope": "selected_record",
                "source_manifest_base": copy.deepcopy(verified["base"])}
    except RshError:
        raise
    except FileNotFoundError:
        _fail("source_manifest_unavailable", "The selected managed source manifest or artifact is missing.")
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        _fail("invalid_source_manifest", "The selected managed source manifest is unreadable or malformed.")


def _publish_directory(staging, target):
    """Atomically publish the complete pair, refusing even an empty existing target."""
    if os.name == "nt":
        os.rename(staging, target)  # Windows rename refuses an existing directory.
        return
    library = ctypes.CDLL(None, use_errno=True)
    if sys.platform.startswith("linux") and hasattr(library, "renameat2"):
        rename = library.renameat2
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        result = rename(-100, os.fsencode(staging), -100, os.fsencode(target), 1)  # RENAME_NOREPLACE
    elif sys.platform == "darwin" and hasattr(library, "renamex_np"):
        rename = library.renamex_np
        rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        result = rename(os.fsencode(staging), os.fsencode(target), 4)  # RENAME_EXCL
    else:
        _fail("atomic_source_publish_unsupported", "This platform has no supported atomic no-overwrite source publication.")
    if result != 0:
        code = ctypes.get_errno()
        if code in (errno.EEXIST, errno.ENOTEMPTY):
            raise FileExistsError()
        raise OSError(code, "Atomic source publication failed")


def _write_exclusive(path, data):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _cleanup(staging, parent):
    if staging.is_symlink():
        staging.unlink()
    elif staging.exists() and staging.resolve().is_relative_to(parent.resolve()):
        for name in (ARTIFACT_NAME, MANIFEST_NAME):
            (staging / name).unlink(missing_ok=True)
        staging.rmdir()


def _result(plan, target, manifest, *, request=False, downloaded=False, reused=False):
    selection = [plan["skill_id"], "--project", str(target.parents[2]), "--source-manifest", str(target / MANIFEST_NAME)]
    return {**plan, "reason_code": "source_cache_verified" if reused else "source_acquired",
            "base": manifest["base"], "selected_base": plan["base"], "cache_reused": reused,
            "source_file": str(target / ARTIFACT_NAME), "manifest_path": str(target / MANIFEST_NAME),
            "save_args": ["save", *selection], "memories_args": ["memories", *selection],
            "next_action": "inspect_acquired_source_and_upstream_setup", **_flags(request, downloaded)}


def fetch_source(catalog, skill_id, project, expected_source_revision=None, expected_source_sha256=None, plan=False, offline=False):
    """Acquire exactly the selected reference file; metadata reads belong to the caller."""
    request_state = False
    downloaded = False
    staging = None
    parent = None
    try:
        if not isinstance(skill_id, str) or len(skill_id) > 80 or not IDENTIFIER.fullmatch(skill_id):
            _fail("invalid_source_id", "Use an exact catalog source-reference ID.")
        try:
            recipe = lookup(catalog, skill_id)
        except RshError as error:
            if error.result["reason_code"] != "skill_not_found":
                raise
        else:
            plan_source(recipe, catalog.get("hub_commit"))  # Deliberately rejects recipe acquisition.
        references = catalog.get("references", {})
        try:
            record = lookup({"records": references.get("records", [])}, skill_id)
        except RshError:
            _fail("skill_not_found", "No selected source reference has this ID.")
        base = selection_base(catalog, record, reference=True)
        prepared = plan_source(record, base["hub_commit"] if base else None, expected_source_revision, expected_source_sha256)
        if plan:
            return prepared
        _, parent, target = _paths(project, prepared["acquisition_id"])
        if target.exists():
            return _result(prepared, target, _cached(target, prepared), reused=True)
        if offline:
            _fail("source_unavailable_offline", "No verified local acquisition exists; offline mode makes no source request.")
        request_state = None
        data = _download(prepared["source_url"], prepared["source_bytes"], prepared["source_sha256"])
        request_state = True
        if len(data) != prepared["source_bytes"] or hashlib.sha256(data).hexdigest() != prepared["source_sha256"]:
            _fail("source_hash_mismatch", "The acquired source failed its exact size or SHA-256 check.", request=True)
        downloaded = True
        root, parent, target = _paths(project, prepared["acquisition_id"])
        for directory in (root, root / ".robot-skill-hub", parent):
            if directory.is_symlink():
                _fail("source_path_escape", "A managed source directory changed to a symlink.")
            directory.mkdir(parents=True, exist_ok=True)
        _paths(project, prepared["acquisition_id"])
        staging = Path(tempfile.mkdtemp(prefix=".acquiring-", dir=parent))
        manifest = _manifest(prepared)
        manifest_bytes = _canonical(manifest) + b"\n"
        if len(manifest_bytes) > MAX_METADATA_BYTES:
            _fail("source_metadata_too_large", "Acquisition provenance exceeds its metadata byte limit.")
        _write_exclusive(staging / ARTIFACT_NAME, data)
        _write_exclusive(staging / MANIFEST_NAME, manifest_bytes)
        _paths(project, prepared["acquisition_id"])
        try:
            _publish_directory(staging, target)
        except FileExistsError:
            # Another complete acquisition may win; its original Hub base is authoritative.
            return _result(prepared, target, _cached(target, prepared), request=True, downloaded=True, reused=True)
        staging = None
        return _result(prepared, target, manifest, request=True, downloaded=True)
    except RshError as error:
        if request_state is True:
            error.result["source_request_performed"] = True
        if downloaded:
            error.result["source_download_performed"] = True
        for key, value in _flags(request_state, downloaded).items():
            error.result.setdefault(key, value)
        raise
    except (OSError, ValueError, TypeError, KeyError, UnicodeError):
        _fail("source_acquisition_failed", "Source acquisition failed safely; existing files and credentials were not replaced.", request=request_state, downloaded=downloaded)
    finally:
        if staging is not None and parent is not None:
            try:
                _cleanup(staging, parent)
            except OSError:
                pass
