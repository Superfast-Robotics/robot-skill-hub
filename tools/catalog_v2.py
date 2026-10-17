"""Bounded static discovery pages, explicit legacy coverage and receipt proofs.

Complete inventory is carried by checksum-bound pages and per-ID documents.
Legacy aggregates are optional compatibility views. A leaf or manifest budget
still requires a versioned capacity migration before it can be exceeded.
"""
import copy
import hashlib
import json
import re

MANIFEST_MAX_BYTES = 128 * 1024
PAGE_MAX_BYTES = 128 * 1024
PAGE_MAX_RECORDS = 100
PROOF_MAX_BYTES = 256 * 1024
IDENT = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
COMMIT = re.compile(r"[a-f0-9]{40}")
SHA256 = re.compile(r"[a-f0-9]{64}")
SUBMISSION = re.compile(r"sub_[a-f0-9]{64}")
MEMORY = re.compile(r"mem_[a-f0-9]{64}")


def json_bytes(value, *, compact=False):
    options = {"sort_keys": True, "separators": (",", ":")} if compact else {"indent": 2}
    return (json.dumps(value, ensure_ascii=False, **options) + "\n").encode("utf-8")


def budget(raw, limit, label):
    if len(raw) > limit:
        raise ValueError(f"{label} exceeds its {limit}-byte UTF-8 budget ({len(raw)} bytes); capacity migration is required")


def compatibility_view(index, limit, complete_manifest_url):
    """Keep complete current data when it fits; otherwise mark a stable subset."""
    if len(json_bytes(index)) <= limit:
        return index
    rows = index["records"]
    result = {key: copy.deepcopy(value) for key, value in index.items() if key != "records"}
    result["records"] = []
    coverage = {"complete": False, "total_records": len(rows), "included_records": 0,
                "complete_manifest_url": complete_manifest_url}
    result["coverage"] = coverage
    budget(json_bytes(result), limit, "Compatibility view metadata")
    # A binary search finds the largest deterministic prefix without serializing
    # the growing inventory once for every candidate record.
    ordered = sorted(rows, key=lambda row: row.get("id", row.get("memory_id", "")))
    low, high = 0, len(ordered)
    while low < high:
        count = (low + high + 1) // 2
        result["records"] = ordered[:count]
        coverage["included_records"] = count
        if len(json_bytes(result)) <= limit:
            low = count
        else:
            high = count - 1
    result["records"] = ordered[:low]
    coverage["included_records"] = low
    budget(json_bytes(result), limit, "Compatibility view")
    return result


def paged_index(rows, hub_commit, kind, *, counts=None, memory_manifest=None,
                page_max_bytes=PAGE_MAX_BYTES, page_max_records=PAGE_MAX_RECORDS,
                manifest_max_bytes=MANIFEST_MAX_BYTES):
    if not COMMIT.fullmatch(str(hub_commit)) or kind not in {"search", "memories"}:
        raise ValueError("A v2 index requires an exact generation and supported page kind")
    if not 1 <= page_max_records <= PAGE_MAX_RECORDS:
        raise ValueError("A v2 page must contain at most 100 records")
    key, pattern = ("id", IDENT) if kind == "search" else ("memory_id", MEMORY)
    if any(not isinstance(row, dict) or not isinstance(row.get(key), str) for row in rows):
        raise ValueError("Invalid v2 record identity")
    ordered = sorted(rows, key=lambda row: row[key])
    seen, pages, descriptors = set(), {}, []

    def encoded(items):
        return json_bytes({"schema_version": "2", "hub_commit": hub_commit, "records": items}, compact=True)

    def finish(items):
        if not items:
            return
        number = len(descriptors)
        if number >= 1000000:
            raise ValueError("V2 page path space requires capacity migration")
        path = f"catalog/v2/generations/{hub_commit}/{kind}/{number:06d}.json"
        raw = encoded(items)
        budget(raw, page_max_bytes, path)
        pages[path] = raw
        descriptors.append({"path": path, "sha256": hashlib.sha256(raw).hexdigest(),
                            "bytes": len(raw), "records": len(items)})

    current = []
    for row in ordered:
        ident = row[key]
        if not isinstance(ident, str) or not pattern.fullmatch(ident) or (kind == "search" and len(ident) > 80) or ident in seen:
            raise ValueError("Duplicate or invalid v2 record identity")
        seen.add(ident)
        if current and (len(current) == page_max_records or len(encoded(current + [row])) > page_max_bytes):
            finish(current)
            current = []
        budget(encoded([row]), page_max_bytes, f"V2 {kind} record {ident}")
        current.append(row)
    finish(current)
    manifest = {"schema_version": "2", "hub_commit": hub_commit, "records": len(rows), "pages": descriptors}
    if kind == "search":
        manifest["counts"] = counts
        manifest["memory_manifest"] = memory_manifest
    budget(json_bytes(manifest, compact=True), manifest_max_bytes, f"V2 {kind} manifest")
    return manifest, pages


def _source_revision(value):
    return isinstance(value, str) and (COMMIT.fullmatch(value) or re.fullmatch(r"sha256:[a-f0-9]{64}", value))


def _record_identity(proof):
    hashes = proof.get("contribution_path_hashes")
    if (not isinstance(proof.get("id"), str) or not IDENT.fullmatch(proof["id"]) or len(proof["id"]) > 80
            or not isinstance(proof.get("record_version"), str) or not proof["record_version"]
            or not _source_revision(proof.get("source_commit")) or not isinstance(hashes, dict) or not hashes
            or not all(isinstance(path, str) and isinstance(value, str) and SHA256.fullmatch(value) for path, value in hashes.items())):
        raise ValueError("Invalid receipt publication proof")
    return proof["id"], proof["record_version"], proof["source_commit"], json.dumps(hashes, sort_keys=True)


def receipt_proofs(manifest, *, max_bytes=PROOF_MAX_BYTES):
    """Project existing validated publication proofs without recalculating them."""
    if manifest.get("schema_version") != "1" or not COMMIT.fullmatch(str(manifest.get("hub_commit"))):
        raise ValueError("Per-receipt publication needs an exact deployed generation")
    candidates, identities = {}, {}

    def remember(proof, release=None):
        ids = proof.get("submission_ids", [])
        if not isinstance(ids, list):
            raise ValueError("Invalid publication submission IDs")
        if not ids:
            return
        identity = _record_identity(proof)
        for ident in ids:
            if not isinstance(ident, str) or not SUBMISSION.fullmatch(ident):
                raise ValueError("Invalid publication submission ID")
            if ident in identities and identities[ident] != identity:
                raise ValueError("Conflicting publication proof for one submission ID")
            identities[ident] = identity
            # Current proof is sufficient. Otherwise preserve one actual
            # historical publication anchor in the operator's original order.
            if ident not in candidates or (candidates[ident][1] is not None and release is None):
                candidates[ident] = proof, release

    for proof in manifest.get("records", []):
        remember(proof)
    for release in manifest.get("history", []):
        if not COMMIT.fullmatch(str(release.get("hub_commit"))):
            raise ValueError("Invalid historical publication generation")
        for proof in release.get("records", []):
            remember(proof, release)

    def envelope():
        return {"schema_version": "1", "hub_commit": manifest["hub_commit"], "catalog_url": manifest["catalog_url"],
                "records": [], "memories": [], "history": []}

    output = {}
    for ident in sorted(candidates):
        proof, release = candidates[ident]
        value = envelope()
        if release is None:
            value["records"] = [copy.deepcopy(proof)]
        else:
            archived = {key: copy.deepcopy(item) for key, item in release.items() if key != "records"}
            archived["records"] = [copy.deepcopy(proof)]
            value["history"] = [archived]
        raw = json_bytes(value)
        budget(raw, max_bytes, ident)
        output[f"catalog/v2/submissions/{ident}.json"] = raw
    for proof in manifest.get("memories", []):
        ident = proof.get("memory_id")
        if (not isinstance(ident, str) or not MEMORY.fullmatch(ident)
                or not SHA256.fullmatch(str(proof.get("fingerprint")))
                or not SHA256.fullmatch(str(proof.get("content_sha256")))):
            raise ValueError("Invalid memory publication proof")
        path = f"catalog/v2/memories/{ident}.json"
        if path in output:
            raise ValueError("Duplicate memory publication proof")
        value = envelope()
        value["memories"] = [copy.deepcopy(proof)]
        raw = json_bytes(value)
        budget(raw, max_bytes, ident)
        output[path] = raw
    return output
