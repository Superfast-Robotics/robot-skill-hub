"""Small canonical source pins used by the submission service."""
import hashlib
import json
from pathlib import Path
import re

SHARD_SCHEME = "sha256-id-prefix-2"


def json_bytes(value):
    """The bytes in Git, manifest checksums and GitHub Contents must agree."""
    return (json.dumps(value, indent=2) + "\n").encode("utf-8")


def source_prefix(ident):
    return hashlib.sha256(ident.encode("utf-8")).hexdigest()[:2]


def source_index(records):
    output = []
    seen = set()
    for record in sorted(records, key=lambda item: item["id"]):
        if record["id"] in seen:
            raise ValueError("Duplicate source reference id")
        seen.add(record["id"])
        source = record["source"]
        output.append({"id": record["id"], "source_commit": source.get("commit") or source["revision"],
                       "source_sha256": source["sha256"], "record_version": "source-" + source["sha256"]})
    return {"schema_version": "1", "records": output}


def write_source_index(records, path):
    """Keep the flat compatibility index and publish bounded source-pin shards.

    Only an obsolete shard named by the previous generated manifest, still
    matching its recorded checksum, may be removed. Other files are untouched.
    """
    path = Path(path)
    manifest_path = path.parent / "source-index-manifest.json"
    shard_dir = path.parent / "source-index"
    parent = path.parent.resolve()
    if not shard_dir.resolve().is_relative_to(parent):
        raise ValueError("Source index shard directory escapes the catalog")
    try:
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        previous = {}
    manifest, shards = source_index_shards(records)
    shard_dir.mkdir(parents=True, exist_ok=True)
    for prefix, data in shards.items():
        destination = shard_dir / (prefix + ".json")
        if destination.is_symlink() or not destination.resolve().is_relative_to(shard_dir.resolve()):
            raise ValueError("Source index shard path escapes the catalog")
        destination.write_bytes(data)
    if previous.get("schema_version") == "1" and previous.get("scheme") == SHARD_SCHEME and isinstance(previous.get("shards"), dict):
        for prefix, descriptor in previous["shards"].items():
            if prefix in shards or not re.fullmatch(r"[a-f0-9]{2}", prefix) or not isinstance(descriptor, dict):
                continue
            if descriptor.get("path") != f"catalog/source-index/{prefix}.json":
                continue
            obsolete = shard_dir / (prefix + ".json")
            if obsolete.is_symlink() or not obsolete.resolve().is_relative_to(shard_dir.resolve()):
                continue
            if obsolete.is_file() and hashlib.sha256(obsolete.read_bytes()).hexdigest() == descriptor.get("sha256"):
                obsolete.unlink()
    manifest_path.write_bytes(json_bytes(manifest))
    path.write_bytes(json_bytes(source_index(records)))


def source_index_shards(records):
    """Return the manifest and exact UTF-8/LF bytes for non-empty hash shards."""
    grouped = {}
    flat = source_index(records)
    for record in flat["records"]:
        grouped.setdefault(source_prefix(record["id"]), []).append(record)
    shards = {}
    descriptors = {}
    for prefix in sorted(grouped):
        body = json_bytes({"schema_version": "1", "records": grouped[prefix]})
        shards[prefix] = body
        descriptors[prefix] = {"path": f"catalog/source-index/{prefix}.json",
                               "sha256": hashlib.sha256(body).hexdigest(), "records": len(grouped[prefix])}
    return {"schema_version": "1", "scheme": SHARD_SCHEME, "shards": descriptors, "records": len(flat["records"])}, shards


def check_source_index(records, path):
    """Validate exact shard hashes/coverage and the flat compatibility output."""
    path = Path(path)
    parent = path.parent.resolve()
    shard_dir = path.parent / "source-index"
    if not shard_dir.resolve().is_relative_to(parent):
        raise ValueError("Source index shard directory escapes the catalog")
    if path.read_bytes() != json_bytes(source_index(records)):
        raise ValueError("Compact canonical source index does not match the reviewed references")
    manifest, shards = source_index_shards(records)
    if (path.parent / "source-index-manifest.json").read_bytes() != json_bytes(manifest):
        raise ValueError("Source index shard manifest does not match the reviewed references")
    for prefix, expected in shards.items():
        shard = shard_dir / (prefix + ".json")
        if shard.is_symlink() or not shard.resolve().is_relative_to(shard_dir.resolve()):
            raise ValueError("Source index shard path escapes the catalog")
        if shard.read_bytes() != expected:
            raise ValueError(f"Source index shard checksum or coverage mismatch: {prefix}")
