"""Validate canonical records and generate the public catalog, docs and snapshot.

Uses only Python's standard library. The schema validator implements the JSON
Schema keywords used by schemas/skill.schema.json, not arbitrary JSON Schema.

Complete discovery uses checksum-bound v2 pages and per-receipt proofs. Bounded
v1 resources are compatibility views with explicit coverage, or are omitted
when their wire format cannot express partial coverage. Leaf and manifest byte
budgets remain explicit capacity limits for a future versioned migration.
"""
import argparse
import copy
import hashlib
import html
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE = "https://hub.superfastrobotics.com"
SITE_VERIFICATION_FILES = ("googlee9bdea008796b0b4.html",)
REPO = "https://github.com/Superfast-Robotics/robot-skill-hub"
API = "https://api.superfastrobotics.com"
# Import the same intake validator used by the installed CLI. ROOT can be
# overridden by isolated builder tests; the implementation stays in this repo.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/find-robot-skills/scripts"))
from rshlib.intake import validate_published_reference
from rshlib.core import RshError, task_attempt_metadata, validate_last_task_attempt
from rshlib.acquisition import plan_source
from rshlib.interfaces import validate_interface
if __package__:
    from .coverage_report import build_coverage, coverage_tables, update_readme
    from .reference_index import check_source_index, require_byte_budget, SOURCE_MANIFEST_MAX_BYTES, SOURCE_SHARD_MAX_BYTES
    from .catalog_v2 import compatibility_view, paged_index, receipt_proofs, json_bytes as v2_json_bytes
else:
    from coverage_report import build_coverage, coverage_tables, update_readme
    from reference_index import check_source_index, require_byte_budget, SOURCE_MANIFEST_MAX_BYTES, SOURCE_SHARD_MAX_BYTES
    from catalog_v2 import compatibility_view, paged_index, receipt_proofs, json_bytes as v2_json_bytes

CATALOG_JSON_MAX_BYTES = 8 * 1024 * 1024
SEARCH_JSON_MAX_BYTES = 2 * 1024 * 1024
PUBLICATION_JSON_MAX_BYTES = 512 * 1024
VERSION_JSON_MAX_BYTES = 32 * 1024
RECORD_JSON_MAX_BYTES = 256 * 1024
LLMS_TEXT_MAX_BYTES = 16 * 1024
LLMS_FULL_TEXT_MAX_BYTES = 128 * 1024
V2_MANIFEST_MAX_BYTES = 128 * 1024
V2_PAGE_MAX_BYTES = 128 * 1024
V2_PAGE_MAX_RECORDS = 100
RECEIPT_PROOF_MAX_BYTES = 256 * 1024
COVERAGE_JSON_MAX_BYTES = 256 * 1024


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value, max_bytes=None):
    if max_bytes is not None:
        require_byte_budget(value.encode("utf-8"), max_bytes, str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")


def write_json(path, value, max_bytes=None):
    write(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n", max_bytes=max_bytes)


def publish_compatibility(index, path, snapshot, manifest_url):
    view = compatibility_view(index, CATALOG_JSON_MAX_BYTES, manifest_url)
    write_json(path, view, max_bytes=CATALOG_JSON_MAX_BYTES)
    write_json(snapshot, view, max_bytes=CATALOG_JSON_MAX_BYTES)
    return view


def write_exact_files(output, files):
    for relative, raw in files.items():
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)


def optional_aggregate(path, raw, limit):
    if len(raw) <= limit:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return True
    if path.is_file():
        path.unlink()
    return False


def validate_schema(value, schema, root_schema, location="$"):
    if "anyOf" in schema:
        for branch in schema["anyOf"]:
            try:
                validate_schema(value, branch, root_schema, location)
                break
            except ValueError:
                pass
        else:
            raise ValueError(f"{location}: no allowed schema alternative")
    if "$ref" in schema:
        referred = root_schema
        for part in schema["$ref"].split("/")[1:]:
            referred = referred[part]
        return validate_schema(value, referred, root_schema, location)
    types = schema.get("type")
    if types:
        types = [types] if isinstance(types, str) else types
        checks = {"object": lambda v: isinstance(v, dict), "array": lambda v: isinstance(v, list),
                  "string": lambda v: isinstance(v, str), "boolean": lambda v: isinstance(v, bool),
                  "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
                  "number": lambda v: type(v) in (int, float) and __import__('math').isfinite(v), "null": lambda v: v is None}
        if not any(checks[t](value) for t in types):
            raise ValueError(f"{location}: expected {types}")
    if "const" in schema and json.dumps(value, sort_keys=True) != json.dumps(schema["const"], sort_keys=True):
        raise ValueError(f"{location}: expected {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{location}: unsupported value {value!r}")
    if isinstance(value, dict):
        if len(value) > schema.get("maxProperties", len(value)):
            raise ValueError(f"{location}: too many properties")
        if "propertyNames" in schema:
            for key in value:
                validate_schema(key, schema["propertyNames"], root_schema, location + ".<key>")
        for key in schema.get("required", []):
            if key not in value:
                raise ValueError(f"{location}.{key}: required")
        properties = schema.get("properties", {})
        for key, item in value.items():
            if key in properties:
                validate_schema(item, properties[key], root_schema, f"{location}.{key}")
            elif schema.get("additionalProperties") is False:
                raise ValueError(f"{location}.{key}: unexpected field")
            elif isinstance(schema.get("additionalProperties"), dict):
                validate_schema(item, schema["additionalProperties"], root_schema, f"{location}.{key}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            raise ValueError(f"{location}: too few items")
        if len(value) > schema.get("maxItems", len(value)):
            raise ValueError(f"{location}: too many items")
        if schema.get("uniqueItems") and len({json.dumps(x, sort_keys=True) for x in value}) != len(value):
            raise ValueError(f"{location}: duplicate items")
        for i, item in enumerate(value):
            validate_schema(item, schema.get("items", {}), root_schema, f"{location}[{i}]")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            raise ValueError(f"{location}: empty string")
        if len(value) > schema.get("maxLength", len(value)):
            raise ValueError(f"{location}: string exceeds maximum length")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            raise ValueError(f"{location}: does not match {schema['pattern']}")
    if type(value) in (int, float) and value < schema.get("minimum", value):
        raise ValueError(f"{location}: below minimum")
    if type(value) in (int, float) and value > schema.get("maximum", value):
        raise ValueError(f"{location}: above maximum")


def safe_path(path):
    posix = PurePosixPath(path)
    if not path or posix.is_absolute() or ".." in posix.parts or "\\" in path or ":" in path:
        raise ValueError(f"Unsafe relative path: {path}")
    return ROOT.joinpath(*posix.parts)


def publish_record_evidence(records, hub_commit):
    """Resolve repository-local evidence to immutable public bytes."""
    for record in records:
        artifacts = record['evidence'].get('artifacts', [])
        published = []
        for artifact in artifacts:
            if artifact.startswith('evidence/'):
                safe_path(artifact)
                artifact = f'https://raw.githubusercontent.com/Superfast-Robotics/robot-skill-hub/{hub_commit}/{artifact}'
            published.append(artifact)
        if artifacts:
            record['evidence']['artifacts'] = published


def load_records():
    schema = read_json(ROOT / "schemas/skill.schema.json")
    records = []
    for path in sorted((ROOT / "catalog/records").glob("*.json")):
        record = read_json(path)
        validate_schema(record, schema, schema, str(path.relative_to(ROOT)))
        if 'interface' in record:
            validate_interface(record['interface'])
        ident = record["id"]
        if path.stem != ident:
            raise ValueError(f"{path}: filename and id differ")
        source = record["source"]
        parsed = urlparse(source["archive_url"])
        repo_path = urlparse(source["repository"]).path
        if parsed.netloc != "codeload.github.com" or parsed.path != f"{repo_path}/tar.gz/{source['commit']}":
            raise ValueError(f"{ident}: archive must address the exact source commit")
        if not record["license"]["verified"]:
            raise ValueError(f"{ident}: automatic preparation requires verified license")
        for path_string in source["paths"]:
            safe_path(path_string)
        for path_string in record["contribution"]["allowed_paths"]:
            allowed = {f"catalog/records/{ident}.json", f"docs/recipes/{ident}.md", f"recipes/{ident}/run.py", f"recipes/{ident}/requirements.txt"}
            if path_string not in allowed or not safe_path(path_string).is_file():
                raise ValueError(f"{ident}: contribution path missing or outside allowed recipe: {path_string}")
        recipe = safe_path(record["preparation"]["recipe_path"])
        if recipe != ROOT / "recipes" / ident:
            raise ValueError(f"{ident}: recipe directory must belong to this record")
        if record["evidence"]["level"] == "task_complete":
            if record["evidence"]["runtime_verification"] != "task_complete" or not record["evidence"]["artifacts"]:
                raise ValueError(f"{ident}: task_complete requires actual runtime evidence and artifacts")
        try:
            validate_last_task_attempt(record)
        except RshError as exc:
            raise ValueError(f"{ident}: {exc}") from exc
        for command in (record["invocation"]["argv"], record["preparation"]["install_argv"]):
            if not isinstance(command, list) or not command or not all(isinstance(x, str) for x in command):
                raise ValueError(f"{ident}: commands must be argv arrays")
        # Bundled files are generated from the editable hub recipe, never a second source.
        record["preparation"]["files"] = {name: (recipe / name).read_text(encoding="utf-8") for name in ("run.py", "requirements.txt")}
        for name in ('LICENSE', 'LICENSE_SCOPE.md'):
            record['preparation']['files'][name] = (ROOT / 'recipes' / name).read_text(encoding='utf-8')
        records.append(record)
    if not records:
        raise ValueError("Catalog is empty")
    return records


def markdown(record, hub_commit, base=DEFAULT_BASE):
    r = record
    c = r["compatibility"][0]
    source = r["source"]
    notes = (ROOT / f"docs/recipes/{r['id']}.md").read_text(encoding="utf-8")
    return f"""# {r['name']}

{r['summary']}

Record version: `{r['maintenance']['record_version']}` · Hub commit: `{hub_commit}`

{execution_interface_markdown(r)}

## Exact environment

| Runtime | Robot | Controller | Observation | OS | Python | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| {c['runtime']} {c['runtime_version']} | {c['robot']} | {c['controller']} | {c['observation']} | {c['os']} {c.get('architecture', 'unknown')} | {r['requirements']['python']} | {r['evidence']['level']} |

{r['observation']['description']}

Compatibility status: **{c['status']}**. An environment match does not establish task completion. Runtime verification: **{r['evidence']['runtime_verification']}**.

## Source and license

- Repository: {source['repository']}
- Source commit: `{source['commit']}` ({source.get('tag', 'no tag')})
- Original authors: {', '.join(source['authors'])}
- License: [{r['license']['spdx']}]({r['license']['url']})
- Source archive SHA256: `{source['archive_sha256']}`
- Upstream files: {', '.join('`' + x + '`' for x in source['paths'])}
- Upstream contribution rules: {source.get('contributing_url', source['repository'])}

## Find, inspect, prepare

```sh
python /PATH_TO_SKILL/scripts/rsh.py find "{r['capabilities'][0]}" --runtime {c['runtime']} --runtime-version {c['runtime_version']} --robot {c['robot']} --json
python /PATH_TO_SKILL/scripts/rsh.py inspect {r['id']} --json
python /PATH_TO_SKILL/scripts/rsh.py prepare {r['id']} --project ./experiment --expected-source-commit {r['source']['commit']} --expected-record-version {r['maintenance']['record_version']} --plan --json
```

Remove `--plan` to download the checksum-verified pinned source and create an isolated project environment. Preparation returns the remaining configuration. Dependency installation is an explicit `--install-deps` step; it can execute package build hooks. Robot simulation is a separate command returned by prepare, never run by find/inspect.

Direct package pins: {', '.join('`' + x + '`' for x in r['requirements']['packages'])}.

{r['requirements']['dependency_lock']}

Hardware: {'; '.join(r['requirements']['hardware'])}.

Rendering: {r['requirements']['rendering']}.

External API keys: {', '.join(r['requirements']['api_keys']) or 'none'}.

## Invocation contract

Entrypoint: `{r['invocation']['entrypoint']}`.

```json
{json.dumps({'argv': r['invocation']['argv'], 'inputs': r['invocation']['inputs'], 'outputs': r['invocation']['outputs']}, indent=2)}
```

Success: {r['completion']['success_condition']}

Timeout: {r['completion']['timeout_seconds']} seconds. {r['completion']['stop_condition']}

Failures: {'; '.join(r['completion']['failure_modes'])}.

## Actual evidence

{r['evidence']['result']}

Reviewer: {r['evidence']['verified_by']} · {r['evidence']['date']}.

Commands/checks actually performed:

{chr(10).join('- ' + x for x in r['evidence']['commands'])}

Submitted evidence and hub verification remain separate. A schema check, PR creation or merge does not establish task success or publication.

## Reusable fixes

{r['contribution']['instructions']}

{notes}
"""


def esc(value):
    return html.escape(str(value), quote=True)


def load_references(recipe_ids=()):
    path = ROOT / "catalog/references.json"
    index = read_json(path) if path.exists() else {"schema_version": "1", "records": []}
    if index.get("schema_version") != "1" or not isinstance(index.get("records"), list):
        raise ValueError("Invalid official source example index")
    seen = set(recipe_ids)
    for record in index["records"]:
        ident = record["id"]
        if ident in seen:
            raise ValueError(f"Duplicate catalog id: {ident}")
        seen.add(ident)
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", ident):
            raise ValueError(f"Unsafe source reference id: {ident}")
        source = record["source"]
        expected = f"{source['repository'].rstrip('/')}/blob/{source['commit']}/{source['path']}"
        if not re.fullmatch(r"[a-f0-9]{40}", source["commit"]) or source["url"] != expected or not re.fullmatch(r"[a-f0-9]{64}", source["sha256"]):
            raise ValueError(f"{ident}: official example requires an exact source commit and checksum")
        if (record["kind"] != "official_example" or record["access"].get("mode") != "source_reference"
                or record["access"].get("hub_prepare") is not False):
            raise ValueError(f"{ident}: official source examples cannot claim a hub preparation adapter")
        license_info = record["license"]
        if (not all(isinstance(license_info.get(key), str) and license_info[key].strip() for key in ("spdx", "url", "scope"))
                or urlparse(license_info["url"]).scheme != "https"
                or ("sha256" in license_info and not re.fullmatch(r"[a-f0-9]{64}", license_info["sha256"]))):
            raise ValueError(f"{ident}: official source reference requires license provenance")
        if record["evidence"].get("runtime_verification") != "not_run":
            raise ValueError(f"{ident}: source reference cannot claim runtime verification")
    source_index_path = ROOT / "catalog/source-index.json"
    if source_index_path.exists():
        expected_index = {"schema_version": "1", "records": [
            {"id": r["id"], "source_commit": r["source"]["commit"], "source_sha256": r["source"]["sha256"],
             "record_version": "source-" + r["source"]["sha256"]} for r in sorted(index["records"], key=lambda r: r["id"])]}
        if read_json(source_index_path) != expected_index:
            raise ValueError("Official source index does not match the canonical references")
    if (ROOT / "catalog/source-index-manifest.json").exists():
        check_source_index(index["records"], source_index_path)
    # Only reviewed, merged canonical intake records are published. Draft
    # bundles and submission receipts never become records on their own.
    for path in sorted((ROOT / "catalog/intake").glob("*.json")):
        record = read_json(path)
        try:
            validate_published_reference(record)
        except RshError as error:
            raise ValueError(f"{path.relative_to(ROOT)}: {error}") from error
        ident = record["id"]
        if path.stem != ident:
            raise ValueError(f"{path}: filename and id differ")
        if ident in seen:
            raise ValueError(f"Duplicate catalog id: {ident}")
        seen.add(ident)
        index["records"].append(record)
    return index


def load_publication_history():
    """Past live deployment proofs, captured by the operator before replacement.

    Never recalculate old path hashes from current files: the historical proof
    belongs to the original deployed commit and its immutable record snapshot.
    """
    path = ROOT / "catalog/publication-history.json"
    if not path.exists():
        return []
    history = read_json(path)
    if history.get("schema_version") != "1" or not isinstance(history.get("releases"), list):
        raise ValueError("Invalid publication history")
    schema = read_json(ROOT / "schemas/skill.schema.json")
    for release in history["releases"]:
        if not re.fullmatch(r"[a-f0-9]{40}", release["hub_commit"]):
            raise ValueError("Historical publication requires an exact hub commit")
        for proof in release["records"]:
            archive = safe_path(proof["archive_path"])
            if hashlib.sha256(archive.read_bytes()).hexdigest() != proof["archive_sha256"]:
                raise ValueError("Historical record archive checksum mismatch")
            record = read_json(archive)
            kind = proof.get("kind", "preparation_recipe")
            if kind == "source_reference":
                try:
                    validate_published_reference(record)
                except RshError as error:
                    raise ValueError(f"Historical source reference: {error}") from error
            elif kind == "preparation_recipe":
                validate_schema(record, schema, schema)
            else:
                raise ValueError("Unsupported historical record kind")
            revision = record["source"].get("commit") or record["source"].get("revision")
            if (record["id"] != proof["id"] or revision != proof["source_commit"]
                    or record["maintenance"]["record_version"] != proof["record_version"]):
                raise ValueError("Historical record does not match its publication proof")
            if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]*", proof["record_version"]):
                raise ValueError("Unsafe historical record version")
    return history["releases"]


MEMORY_FIELDS = ("schema_version", "skill_id", "base", "kind", "summary", "observation",
                 "resolution", "environment", "evidence", "attribution", "publication")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def load_memories():
    """Only main-branch, operator-reviewed reports become shared discovery data."""
    paths = sorted((ROOT / ".hub/memories").glob("mem_*.json"))
    if not paths:
        return []
    schema = read_json(ROOT / "schemas/memory.schema.json")
    entries = []
    for path in paths:
        raw = path.read_bytes()
        if len(raw) > 24 * 1024:
            raise ValueError("Stored memory exceeds its size limit")
        entry = json.loads(raw)
        payload = {key: entry[key] for key in MEMORY_FIELDS}
        validate_schema(payload, schema, schema, str(path.relative_to(ROOT)))
        if len(canonical(payload).encode("utf-8")) > 16 * 1024:
            raise ValueError("Memory request exceeds 16 KiB")
        material = {key: value for key, value in payload.items() if key not in ("attribution", "publication")}
        material["base"] = {key: payload["base"][key] for key in ("record_version", "source_commit")}
        fingerprint = hashlib.sha256(canonical(material).encode("utf-8")).hexdigest()
        principal = entry["principal_id"]
        if not re.fullmatch(r"[a-f0-9]{64}", principal):
            raise ValueError("Invalid memory principal hash")
        ident = "mem_" + hashlib.sha256(("rsh-memory-id-v1\0" + principal + "\0" + fingerprint).encode()).hexdigest()
        if entry["fingerprint"] != fingerprint or entry["memory_id"] != ident or path.stem != ident:
            raise ValueError("Memory content identity does not match its receipt")
        if entry["hub_validation"].get("level") != "structure_checked" or entry["hub_validation"].get("runtime") != "not_run":
            raise ValueError("Memory intake cannot claim runtime verification")
        extra = set(entry) - set(MEMORY_FIELDS) - {"memory_id", "principal_id", "fingerprint", "hub_validation", "created_at"}
        if extra:
            raise ValueError("Unexpected stored memory fields")
        entries.append((entry, raw))
    return entries


def publish_memories(entries, output, base, hub_commit, *, return_index=False):
    records, proofs = [], []
    for entry, raw in entries:
        ident = entry["memory_id"]
        url = base + "/memories/" + ident + ".json"
        digest = hashlib.sha256(raw).hexdigest()
        public = {key: entry[key] for key in MEMORY_FIELDS}
        public.update(memory_id=ident, fingerprint=entry["fingerprint"], content_sha256=digest,
                      entry_url=url, hash_target="entry_url", created_at=entry["created_at"],
                      curation="maintainer_merged", interpretation="data_only", trust="contributor_reported",
                      hub_validation=entry["hub_validation"])
        records.append(public)
        proofs.append({"memory_id": ident, "fingerprint": entry["fingerprint"], "content_sha256": digest,
                       "skill_id": entry["skill_id"], "record_version": entry["base"]["record_version"],
                       "source_commit": entry["base"]["source_commit"], "base_hub_commit": entry["base"]["hub_commit"],
                       "entry_url": url})
        # The hash covers these exact immutable bytes, not the discovery projection.
        destination = output / "memories" / (ident + ".json")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
    index = {"schema_version": "1", "hub_commit": hub_commit, "interpretation": "data_only",
             "trust": "contributor_reported", "records": records}
    publish_compatibility(index, output / "catalog/v1/memories.json",
                          ROOT / "skills/find-robot-skills/assets/memories.snapshot.json",
                          base + "/catalog/v2/memory-manifest.json")
    return (proofs, index) if return_index else proofs


def publish_history(releases, output, base):
    published = copy.deepcopy(releases)
    for release in published:
        for proof in release["records"]:
            archive = safe_path(proof.pop("archive_path"))
            record = read_json(archive)
            relative = f"releases/{proof['id']}/{proof['record_version']}/"
            proof["recipe_url"] = base + "/" + relative
            folder = output / relative
            if proof.get("kind") == "source_reference":
                # Preserve the immutable archive bytes as well as the original
                # accepted-path hashes. Neither is derived from today's intake.
                raw = archive.read_bytes()
                require_byte_budget(raw, RECORD_JSON_MAX_BYTES, str(folder / "skill.json"))
                folder.mkdir(parents=True, exist_ok=True)
                (folder / "skill.json").write_bytes(raw)
                write(folder / "README.md", reference_markdown(record, release["hub_commit"], publication_version=proof["record_version"]))
                write(folder / "index.html", reference_detail(record, base, release["hub_commit"],
                      publication_version=proof["record_version"], page_path=relative))
                continue
            write_json(folder / "skill.json", record, max_bytes=RECORD_JSON_MAX_BYTES)
            body = f"""<main><h1>{esc(record['name'])}</h1>
<p>Historical published record: <code>{esc(proof['record_version'])}</code>.</p>
<p>Published hub commit: <code>{esc(release['hub_commit'])}</code>.</p>
<p><a href="skill.json">Pinned record JSON, preparation files and source checksums</a></p>
<p><a href="{esc(base)}/skills/{esc(proof['id'])}/">Current documentation</a></p>
<p>This archived record preserves the source and preparation contract of the earlier publication. Current documentation can change independently.</p></main>"""
            write(folder / "index.html", shell(record["name"] + " — historical record", record["summary"], body, base, relative))
    return published


def shell(title, description, body, base, path=""):
    canonical = base.rstrip("/") + "/" + path
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
<link rel="icon" href="data:,">
<link rel="canonical" href="{esc(canonical)}">
<link rel="alternate" type="application/json" href="{esc(base)}/catalog/v1/index.json" title="Catalog JSON">
</head>
<body>
<header><p><a href="{esc(base)}/">Robot Skill Hub</a> by <a href="https://superfastrobotics.com/">Superfast Robotics</a></p>
<nav aria-label="Main navigation"><a href="{esc(base)}/samples/">Skill examples</a> | <a href="{esc(base)}/catalog/v2/search-manifest.json">Search index</a> | <a href="{esc(base)}/agent-quickstart.md">Agent quickstart</a> | <a href="{esc(base)}/llms-full.txt">Full text</a> | <a href="{REPO}">GitHub</a></nav></header>
{body}
<footer><hr><p><a href="{esc(base)}/agent.json">Publication proof contract</a> | <a href="{esc(base)}/contributing.md">Contributing</a> | <a href="{REPO}/blob/main/LICENSE">License</a></p></footer>
</body>
</html>"""


def resource_links(base):
    resources = [
        ("Agent contract JSON", "agent.json"),
        ("Catalog JSON", "catalog/v1/index.json"),
        ("Official source examples JSON", "catalog/v1/references.json"),
        ("Shared memory JSON", "catalog/v1/memories.json"),
        ("Catalog version JSON", "catalog/v1/version.json"),
        ("Publication manifest", "catalog/v1/publication.json"),
        ("Agent quickstart", "agent-quickstart.md"),
        ("Discovery index", "llms.txt"),
        ("Full documentation", "llms-full.txt"),
        ("Record schema", "schemas/skill.schema.json"),
        ("Compatibility", "compatibility.md"),
        ("Contributions", "contributing.md"),
    ]
    return "<ul>" + "".join(f'<li><a href="{esc(base)}/{path}">{label}</a>: <code>{esc(base)}/{path}</code></li>' for label, path in resources) + "</ul>"


def reference_list(references):
    return "<ul>" + "".join(f"""<li><h3><a href="{esc(r['source']['url'])}">{esc(r['name'])}</a></h3>
<p>{esc(r['framework'])} — {esc(r['summary'])}</p>
<p>Source: <a href="{esc(r['source']['url'])}"><code>{esc(r['source']['url'])}</code></a></p>
<p>License: <a href="{esc(r['license']['url'])}">{esc(r['license']['spdx'])}</a>. Evidence: <code>{esc(r['evidence']['level'])}</code>; runtime: <code>{esc(r['evidence']['runtime_verification'])}</code>.</p></li>""" for r in references["records"]) + "</ul>"


COMPATIBILITY_FIELDS = ("runtime", "runtime_version", "robot", "controller", "observation", "os", "python", "architecture", "status")
# These names identify upstream runtimes, not measured compatibility. Other
# framework labels may be arbitrary names, so they stay unknown.
KNOWN_RUNTIMES = {"maniskill", "mujoco", "pybullet", "webots", "isaaclab", "isaacsim", "robosuite",
                  "drake", "pinocchio", "ompl", "lerobot", "roboticstoolbox", "pyrobosim", "crazyflie",
                  "ros", "ros2", "moveit2", "nav2"}


def explicit_compatibility(record):
    """Preserve explicit combinations without making a Cartesian product."""
    raw = record.get("compatibility", [])
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    return [{key: combo[key] for key in COMPATIBILITY_FIELDS if isinstance(combo.get(key), str)}
            for combo in raw if isinstance(combo, dict)
            and any(isinstance(combo.get(key), str) and combo[key] not in ("", "unknown")
                    for key in COMPATIBILITY_FIELDS if key != "status")]


def reference_source_acquisition(record, hub_commit):
    """Use the installed CLI's pure metadata contract before offering retrieval."""
    try:
        return plan_source(record, hub_commit)
    except RshError as error:
        return {"status": "unavailable", "reason_code": error.result["reason_code"], "message": error.result["message"]}


def reference_markdown(record, hub_commit, publication_version=None, adaptations=()):
    source, license_info, evidence = record["source"], record["license"], record["evidence"]
    revision = source.get("commit") or source["revision"]
    authors = ", ".join(source.get("authors", [])) or "See pinned upstream source and license notices."
    version = publication_version or "source-" + source["sha256"]
    acquisition = reference_source_acquisition(record, hub_commit)
    if acquisition["status"] == "ready":
        command = "python /PATH_TO_SKILL/scripts/rsh.py " + " ".join(acquisition["fetch_args"]) + " --project ./experiment --json"
        retrieval = (f"Optional inert file retrieval: `{command}`. This verifies one file, preserves provenance and never installs or runs it. "
                     "See [source-file retrieval](https://hub.superfastrobotics.com/source-files.md).")
    else:
        retrieval = (f"Inert file retrieval is unavailable for this reference (`{acquisition['reason_code']}`): {acquisition['message']} "
                     "Use the pinned upstream source and its acquisition instructions. The Hub CLI does not download this artifact. "
                     "See [source-file retrieval limits](https://hub.superfastrobotics.com/source-files.md).")
    parts = [f"# {record['name']}", record["summary"],
             f"ID: `{record['id']}`\n\nRecord version: `{version}`\n\nHub commit: `{hub_commit}`"]
    if adaptations:
        parts.extend(['## Executable adaptations', 'These are separate bounded adaptations of this source. Inspect their model, input contract and evidence; they do not verify the original robot environment.'] +
            [f"- [{a['id']}]({a['detail_url']}) — {a['model']}" for a in adaptations])
    if publication_version:
        parts.extend(("Historical published source reference. This archive preserves the original metadata and publication; current documentation can change independently.",
                      f"Source identity version: `source-{source['sha256']}`"))
    parts.extend([
             "## Access", record["access"]["instructions"],
             retrieval,
             f"Hub preparation adapter: **false**. Runtime verification: **{evidence['runtime_verification']}**.",
             f"Upstream setup: {record['access'].get('setup_url', source['repository'])}",
             "## Source and license",
             f"- Repository: {source['repository']}\n- Pinned source: {source['url']}\n- Revision: `{revision}`\n"
             f"- Path: `{source['path']}`\n- Source SHA256: `{source['sha256']}`\n"
             f"- Source bytes: {source.get('bytes', 'unknown')}\n- Original authors: {authors}\n"
             f"- License: [{license_info['spdx']}]({license_info['url']})\n- License scope: {license_info['scope']}"])
    if license_info.get("sha256"):
        parts.append(f"License SHA256: `{license_info['sha256']}`")
    for label, key in (("Artifact", "artifact"), ("Requirements", "requirements"), ("Invocation", "invocation")):
        if record.get(key):
            parts.extend(("## " + label, "```json\n" + json.dumps(record[key], ensure_ascii=False, indent=2) + "\n```"))
    parts.extend(("## Compatibility", "```json\n" + json.dumps(explicit_compatibility(record), ensure_ascii=False, indent=2) + "\n```",
                  "Missing environment fields remain unknown. Source discovery labels do not establish robot compatibility.",
                  "## Evidence", f"Level: **{evidence['level']}**. Runtime verification: **{evidence['runtime_verification']}**.",
                  evidence.get("inspection", evidence.get("result", "No runtime execution evidence.")),
                  "Source review and contributor reports do not establish task completion. Preserve upstream attribution and licenses."))
    return "\n\n".join(parts) + "\n"


def reference_detail(record, base, hub_commit, publication_version=None, page_path=None, adaptations=()):
    source, license_info, evidence = record["source"], record["license"], record["evidence"]
    revision = source.get("commit") or source["revision"]
    version = publication_version or "source-" + source["sha256"]
    acquisition = reference_source_acquisition(record, hub_commit)
    if acquisition["status"] == "ready":
        retrieval = ("For one verified inert file, use the installed CLI's <code>inspect</code> response <code>fetch_source_args</code> "
                     f"and append <code>--project DIR --json</code>. <a href=\"{esc(base)}/source-files.md\">Source-file retrieval</a> "
                     "creates no environment and does not install or run the source.")
    else:
        retrieval = (f"Inert file retrieval is unavailable for this reference (<code>{esc(acquisition['reason_code'])}</code>): "
                     f"{esc(acquisition['message'])} Use the pinned upstream source and its acquisition instructions. "
                     "The Hub CLI does not download this artifact. "
                     f"See <a href=\"{esc(base)}/source-files.md\">source-file retrieval limits</a>.")
    historical = ""
    if publication_version:
        historical = f"""<p>Historical published source reference: <code>{esc(publication_version)}</code>.</p>
<p>Published hub commit: <code>{esc(hub_commit)}</code>. Source identity version: <code>source-{esc(source['sha256'])}</code>.</p>
<p>This archive preserves the original metadata and publication. <a href="{esc(base)}/references/{esc(record['id'])}/">Current documentation</a> can change independently.</p>"""
    body = f"""<main id="main-content"><h1>{esc(record['name'])}</h1>
<p>{esc(record['summary'])}</p>
{historical}
<p><code>{esc(record['id'])}</code> | Record version: <code>{esc(version)}</code></p>
<p><a href="skill.json">Record JSON</a> | <a href="README.md">Markdown</a> | <a href="{esc(source['url'])}">Pinned upstream source</a></p>
<h2>Access</h2><p>{esc(record['access']['instructions'])}</p>
<p>{retrieval}</p>
<p>Hub preparation adapter: <code>false</code>. Follow the <a href="{esc(record['access'].get('setup_url', source['repository']))}">upstream setup</a> and invocation contract.</p>
<h2>Source and license</h2><dl><dt>Repository</dt><dd><a href="{esc(source['repository'])}">{esc(source['repository'])}</a></dd>
<dt>Revision</dt><dd><code>{esc(revision)}</code></dd><dt>Path</dt><dd><code>{esc(source['path'])}</code></dd>
<dt>Source SHA256</dt><dd><code>{esc(source['sha256'])}</code></dd><dt>Source bytes</dt><dd>{esc(source.get('bytes', 'unknown'))}</dd><dt>Original authors</dt><dd>{esc(', '.join(source.get('authors', [])) or 'See pinned upstream source and license notices.')}</dd>
<dt>License</dt><dd><a href="{esc(license_info['url'])}">{esc(license_info['spdx'])}</a></dd>
<dt>License scope</dt><dd>{esc(license_info['scope'])}</dd><dt>License SHA256</dt><dd><code>{esc(license_info.get('sha256', 'not independently verified'))}</code></dd>
<dt>Hub commit</dt><dd><code>{esc(hub_commit)}</code></dd></dl>"""
    for label, value in (("Artifact", record.get("artifact")), ("Requirements", record.get("requirements")),
                         ("Invocation", record.get("invocation")), ("Explicit compatibility", explicit_compatibility(record))):
        if value is not None:
            body += f"<h2>{label}</h2><pre><code>{esc(json.dumps(value, ensure_ascii=False, indent=2))}</code></pre>\n"
    body += f"""<p>Missing environment fields remain unknown. Discovery labels do not establish robot compatibility.</p>
<h2>Evidence</h2><p>Level: <code>{esc(evidence['level'])}</code>; runtime verification: <code>{esc(evidence['runtime_verification'])}</code>.</p>
<p>{esc(evidence.get('inspection', evidence.get('result', 'No runtime execution evidence.')))}</p>
<p>Source review and contributor reports do not establish task completion. Preserve upstream attribution and licenses.</p></main>"""
    if adaptations:
        links=''.join('<li><a href="'+esc(a['detail_url'])+'">'+esc(a['id'])+'</a>: '+esc(a['model'])+'</li>' for a in adaptations)
        body=body.replace('</main>', '<h2>Executable adaptations</h2><p>Separate bounded adapters; inspect model, contract and evidence. This does not verify the original robot environment.</p><ul>'+links+'</ul></main>')
    return shell(record["name"] + " - Robot Skill Hub", record["summary"], body, base,
                 page_path or "references/" + record["id"] + "/")


def search_row(record, output, base, recipe=False):
    source = record["source"]
    relative = ("skills/" if recipe else "references/") + record["id"] + "/skill.json"
    combinations = explicit_compatibility(record)
    runtimes = list(dict.fromkeys(c["runtime"] for c in combinations if c.get("runtime") not in (None, "", "unknown")))
    runtime = runtimes[0] if len(runtimes) == 1 else "unknown"
    if not runtimes and record.get("framework") in KNOWN_RUNTIMES:
        runtime = record["framework"]
    row = {"id": record["id"], "name": record["name"], "summary": record["summary"],
           "kind": "preparation_recipe" if recipe else "source_reference",
           "capabilities": record.get("capabilities", []), "aliases": record.get("aliases", []),
           "compatibility": combinations, "runtime": runtime, "framework": record.get("framework", runtime),
           "record_version": record["maintenance"]["record_version"] if recipe else "source-" + source["sha256"],
           "source_commit": source.get("commit") or source["revision"],
           "source_sha256": source.get("archive_sha256") if recipe else source["sha256"],
           "source_url": source["repository"].rstrip("/") + "/tree/" + source["commit"] if recipe else source["url"],
           "license": {key: record["license"][key] for key in ("spdx", "url", "scope", "verified") if key in record["license"]},
           "evidence_level": record["evidence"]["level"], "runtime_verification": record["evidence"]["runtime_verification"],
           **task_attempt_metadata(record),
           "hub_prepare": recipe, "record_url": base + "/" + relative,
           "record_sha256": hashlib.sha256((output / relative).read_bytes()).hexdigest()}
    robots = record.get("robots") or list(dict.fromkeys(c["robot"] for c in combinations if c.get("robot") not in (None, "", "unknown")))
    if robots:
        row["robots"] = robots
    if not recipe and "robot_types" in record:
        types = record["robot_types"]
        if not isinstance(types, list) or any(not isinstance(value, str) or not 0 < len(value) <= 80 for value in types):
            raise ValueError(f"{record['id']}: robot type discovery labels must be bounded strings")
        if types:
            # Classification is searchable discovery data, not a compatibility tuple.
            row["robot_types"] = list(types)
    if recipe:
        row["python_requirement"] = record["requirements"]["python"]
        row['adapter_license'] = {'spdx': 'MIT', 'verified': True, 'scope': 'Hub-authored adapter only; upstream terms remain applicable',
                                  'paths': ['recipes/' + record['id'] + '/run.py', 'recipes/' + record['id'] + '/requirements.txt']}
        if record.get('interface'):
            row['execution_interface']={key:record['interface'][key] for key in ['version','kind','abstraction_level','execution_domain','language','input_transport','output_selector']}
    return row


def execution_interface_markdown(record):
    contract=record.get('interface')
    return ('## Executable interface\n\n```json\n'+json.dumps(contract,indent=2)+'\n```\n\n') if contract else ''


def prepared_adaptation_map(records,references,base):
    origins={r['id']:r for r in references['records']}
    result={}
    for record in records:
        for ident in record.get('interface',{}).get('origin_reference_ids',[]):
            origin=origins.get(ident)
            if not origin or origin['source']['repository']!=record['source']['repository'] or origin['source'].get('commit')!=record['source']['commit'] or origin['source']['path'] not in record['source']['paths']:
                raise ValueError(record['id']+': adaptation must reference the exact included source revision')
            result.setdefault(ident,[]).append({'id':record['id'],'record_version':record['maintenance']['record_version'],
                'source_commit':record['source']['commit'],'relationship':'adapted_from; model and contract may differ',
                'model':record['compatibility'][0]['robot'],'detail_url':base+'/skills/'+record['id']+'/'})
    return result


def home(records, base, references=None, coverage=None):
    references = references or {"records": []}
    install = "npx skills add Superfast-Robotics/robot-skill-hub --skill find-robot-skills"
    commands = f"""curl -fsSL '{API}/v1/search?q=grasp&limit=3'
curl -fsSL {base}/agent.json
{install}"""
    api_docs = f'<a href="{esc(base)}/openapi.json">OpenAPI</a> | ' if (ROOT / "docs/public-api.openapi.json").exists() else ""
    body = f"""<main id="main-content">
<h1>Robot Skill Hub — Robotics Skills Catalog for AI Agents</h1>
<p><strong>Robot Skill Hub is an open robotics skills catalog for AI agents.</strong> Find and reuse robot skills across robotics frameworks for motion planning, manipulation, kinematics and simulation. Inspect pinned code, compatibility and execution evidence through public HTTPS, MCP or the CLI; prepare a matching environment and share useful corrections for the next task.</p>
<p><a href="{API}/v1/search?q=grasp&amp;limit=3">Search robot skills</a> | <a href="{esc(base)}/samples/">Browse task examples</a> | <a href="{esc(base)}/coverage.html">Verified robot and environment coverage</a></p>
<p>Reuse the fix. Keep the context lean. Find a pinned starting point, recall a matching correction, and save what you learn for the next task.</p>
<p>CLI inspection JSON: <strong>17% fewer tokens. Same fields.</strong> Two-link IK regression: <strong>12/24 to 24/24 targets passed</strong> after saved-fix reuse. <a href="{esc(base)}/reuse-benchmark.md">Measurements and reproduction</a>.</p>
<p>Find reusable robot code, policies, models, datasets and workflows across robots and runtimes. Inspect immutable sources, licenses, requirements and execution evidence before use.</p>
<p>{len(records)} preparation recipes and {len(references['records'])} source references. Source references use upstream setup; preparation adapters are identified explicitly.</p>
<h2>Find and read</h2>
<p><a href="{API}/v1/search?q=grasp&amp;limit=3">Search JSON</a> | <a href="{esc(base)}/catalog/v2/search-manifest.json">Complete search index</a> | <a href="{esc(base)}/agent-quickstart.md">Agent quickstart</a></p>
<pre><code>{esc(commands)}</code></pre>
<p>Public HTTPS search and inspection need no installation or account. For the optional CLI, read <code>SKILL.md</code> and use <code>find</code> and <code>inspect</code>. <code>fetch-source</code> retrieves one verified inert source file; <code>prepare --plan</code> explains a supported recipe before downloads. Execution is separate.</p>
<h2>Connect an agent</h2>
<p>Read-only MCP: <a href="{API}/mcp"><code>{API}/mcp</code></a>. Public reads need no token. {api_docs}<a href="{esc(base)}/agent.json">Agent contract</a> | <a href="{API}/v1/capabilities">Capabilities</a></p>
{coverage_tables(coverage, base) if coverage is not None else ''}
<h2>Share a new skill or finding</h2>
<p>Use <code>rsh.py register --help</code> to register a pinned source record, or <code>POST {API}/v1/skills</code>. New submissions create a draft for maintainer review. Read <a href="{esc(base)}/new-skills.md">new-skill registration</a> and <a href="{esc(base)}/contributing.md">contribution instructions</a>. Save observed reusable findings with <code>rsh.py save</code>.</p>
<h2>Evidence</h2>
<p><code>not_run</code> means no runtime execution evidence. Source review and contributor reports do not establish task completion. Each record preserves its exact source pin and evidence level.</p>
<p><a href="{esc(base)}/catalog/v1/version.json">Version and resource checksums</a> | <a href="{esc(base)}/llms.txt">All discovery resources</a> | <a href="{esc(base)}/verification.md">Verification history</a></p>
<p>Platform: Apache-2.0. Hub execution adapters: MIT. External works retain their original terms. <a href="{esc(base)}/LICENSE_SCOPE.md">License scope</a>.</p>
</main>"""
    return shell("Robot Skill Hub | Robotics Skills Catalog for AI Agents", "Find and reuse robot skills for motion planning, manipulation, kinematics and simulation. Inspect pinned code, compatibility and execution evidence via HTTPS, MCP or CLI.", body, base)


def detail(r, base, hub_commit):
    environments = []
    for c in r["compatibility"]:
        fields = [("Runtime", c["runtime"] + " " + c["runtime_version"]), ("Robot", c["robot"]), ("Controller", c["controller"]), ("Observation", c["observation"]), ("OS / architecture", c["os"] + " / " + c.get("architecture", "unknown")), ("Python", r["requirements"]["python"])]
        environments.append("<dl>" + "".join(f"<dt>{esc(k)}</dt><dd>{esc(v)}</dd>" for k, v in fields) + f"</dl><p>Compatibility status: {esc(c['status'])}</p>")
    commands = f"""curl -fsSL {base}/skills/{r['id']}/skill.json
curl -fsSL {base}/skills/{r['id']}/README.md
python /PATH_TO_SKILL/scripts/rsh.py inspect {r['id']} --json
python /PATH_TO_SKILL/scripts/rsh.py prepare {r['id']} --project ./experiment --expected-source-commit {r['source']['commit']} --expected-record-version {r['maintenance']['record_version']} --plan --json"""
    source_links = "".join(f'<li><a href="{esc(r["source"]["repository"])}/blob/{esc(r["source"]["commit"])}/{esc(p)}">{esc(p)}</a></li>' for p in r["source"]["paths"])
    body = f"""<main id="main-content">
<h1>{esc(r['name'])}</h1>
<p>{esc(r['summary'])}</p>
<p><code>{esc(r['id'])}</code> | Record version: <code>{esc(r['maintenance']['record_version'])}</code></p>
<p><a href="skill.json">Record JSON</a> | <a href="README.md">Markdown recipe</a> | <a href="{esc(base)}/catalog/v2/search-manifest.json">Complete search index</a></p>
<h2>Fetch and prepare</h2>
<pre><code>{esc(commands)}</code></pre>
<p>Inspect the requirements, then remove <code>--plan</code> to prepare a project. Preparation verifies the archive SHA256 and preserves exact source pins. <code>--install-deps</code> explicitly installs dependencies. Run the returned simulation command separately.</p>
<h2>Environment</h2>
{''.join(environments)}
<p>{esc(r['observation']['description'])}</p>
<h2>Requirements</h2>
<ul>{''.join('<li>' + esc(x) + '</li>' for x in r['requirements']['hardware'])}</ul>
<p>{esc(r['requirements']['rendering'])}</p>
<p>Packages: <code>{esc(', '.join(r['requirements']['packages']))}</code></p>
<p>{esc(r['requirements']['dependency_lock'])}</p>
<p>External API keys: {esc(', '.join(r['requirements']['api_keys']) or 'none')}.</p>
<h2>Invocation</h2>
{('<h3>Executable interface</h3><pre><code>'+esc(json.dumps(r['interface'],indent=2))+'</code></pre>') if r.get('interface') else ''}
<p>Entrypoint: <code>{esc(r['invocation']['entrypoint'])}</code></p>
<pre><code>{esc(json.dumps({'argv':r['invocation']['argv'],'inputs':r['invocation']['inputs'],'outputs':r['invocation']['outputs']}, indent=2))}</code></pre>
<p>Success: {esc(r['completion']['success_condition'])}</p>
<p>Timeout: {esc(r['completion']['timeout_seconds'])} seconds. {esc(r['completion']['stop_condition'])}</p>
<h3>Failure modes</h3>
<ul>{''.join('<li>'+esc(x)+'</li>' for x in r['completion']['failure_modes'])}</ul>
<h2>Source and license</h2>
<dl><dt>Repository</dt><dd><a href="{esc(r['source']['repository'])}">{esc(r['source']['repository'])}</a></dd>
<dt>Authors</dt><dd>{esc(', '.join(r['source']['authors']))}</dd>
<dt>Commit</dt><dd><code>{esc(r['source']['commit'])}</code></dd>
<dt>Archive SHA256</dt><dd><code>{esc(r['source']['archive_sha256'])}</code></dd>
<dt>License</dt><dd><a href="{esc(r['license']['url'])}">{esc(r['license']['spdx'])}</a></dd>
<dt>Hub commit</dt><dd><code>{esc(hub_commit)}</code></dd></dl>
<ul>{source_links}</ul>
<h2>Evidence</h2>
<p>Runtime: {esc(r['evidence']['runtime_verification'])} / {esc(r['evidence']['level'])}</p>
<p>{esc(r['evidence']['result'])}</p>
<p>Reviewer: {esc(r['evidence']['verified_by'])} | {esc(r['evidence']['date'])}</p>
<ul>{''.join('<li>'+esc(x)+'</li>' for x in r['evidence']['commands'])}</ul>
<p>Submitter reports and hub verification remain separate. Source review does not establish task success.</p>
</main>"""
    return shell(r["name"] + " - Robot Skill Hub", r["summary"], body, base, "skills/" + r["id"] + "/")


def git_commit():
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, stderr=subprocess.DEVNULL, text=True).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "uncommitted"


def discovery_text(records, base, references=None, *, memory_count=None):
    references = references or {"records": []}
    counts = f"{len(records)} preparation recipes and {len(references['records'])} source references"
    if memory_count is not None:
        counts += f"; {memory_count} published findings"
    return f"""# Robot Skill Hub

> Pinned robot code, environment contracts and preparation commands for coding agents.

Current catalog: {counts}. Search matches and source references do not establish runtime compatibility or task completion.

- [Agent quickstart]({base}/agent-quickstart.md): install, find, inspect and use supported sources
- [Agent contract JSON]({base}/agent.json): machine-readable operations, schemas and trust boundaries
- [Current execution and reference coverage]({base}/coverage.html): robot, environment and task tables; [JSON]({base}/catalog/v1/coverage.json)
- [Component license policy]({base}/license-policy.json): Apache-2.0 platform, MIT Hub execution adapters, original upstream terms
- [Public search API]({API}/v1/search): query capabilities and inspect selected records without authentication
- [Per-ID inspection contract]({base}/openapi.json): `GET {API}/v1/skills/{{skill_id}}` for one selected ID's exact source, license and record metadata
- [Exact-version findings contract]({base}/openapi.json): `GET {API}/v1/findings` with required skill, source and record-version pins
- [Read-only MCP]({API}/mcp): connect an agent with search, inspect and capabilities tools
- [OpenAPI]({base}/openapi.json): public read and authenticated contribution contracts
- [Complete search manifest]({base}/catalog/v2/search-manifest.json): bounded checksum-bound pages for every recipe and source reference
- [Complete finding manifest]({base}/catalog/v2/memory-manifest.json): bounded checksum-bound pages for every shared finding
- [Catalog version JSON]({base}/catalog/v1/version.json): published commit, resource counts and checksums
- [Recipe compatibility view]({base}/catalog/v1/index.json): inspect coverage; use the complete search manifest for enumeration
- [Source compatibility view]({base}/catalog/v1/references.json): inspect coverage; use the complete search manifest for enumeration
- [Publication proof contract]({base}/agent.json): per-receipt published versions, exact hashes and historical anchors
- [Source-file retrieval]({base}/source-files.md): one pinned inert file, independent of runtime preparation
- [Search and preparation guide]({base}/search.md): exact selections, pagination, offline coverage and execution evidence
- [Community experience]({base}/community.md): local recall, self-service enrollment, immediate immutable variants and actual reuse outcomes
- [Reuse measurements]({base}/reuse-benchmark.md): reproducible CLI text-token counts and a controlled two-link IK correction-transfer regression
- [Reviewed finding guide]({base}/memory.md): legacy reviewed observations and the shared minimal finding format
- [Usage guide collection]({base}/llms-full.txt): quickstart first, source retrieval, findings and reviewable contributions
- [Record schema]({base}/schemas/skill.schema.json)
- [Finding schema]({base}/schemas/memory.schema.json)
- [Project policy schema]({base}/schemas/project-policy.schema.json)
- [New-source intake schema]({base}/schemas/intake.schema.json)
- [Compatibility contract]({base}/compatibility.md)
- [Contribution contract]({base}/contributing.md)
- [Register a new skill]({base}/new-skills.md): immutable source metadata, local-first intake and maintainer review
- [Agent discovery guide]({base}/discovery.md): installation and read-only MCP connection
- [Task entrypoints and integrations]({base}/agent-distribution.md): planning, kinematics and trajectory skills; ROS-MCP and LangChain examples
- [HTTPS agent skill index]({base}/.well-known/agent-skills/index.json): three standalone, checksum-addressed lookup archives; install without a Git clone
- [Robotics problem reproductions]({base}/problems/): ten pinned input/contract cases in HTML, Markdown and JSON
- [Access measurement and privacy]({base}/privacy.md): measured activity, retained data and opt-out

## Read selected data

Search returns bounded results, an exact total and a next-parameters object pinned to one Hub commit. Continue with those exact parameters. Use each result's record_url and record_sha256 for its complete per-ID JSON. Reference pages live at `{base}/references/{{skill_id}}/`; recipe pages at `{base}/skills/{{skill_id}}/`.

For complete enumeration, read the search and finding manifests and verify each declared page hash and generation. Compatibility views can be incomplete or omitted at their size limits. This directory and the usage guide collection intentionally do not repeat individual records or source contents.
"""


def full_text(records, base, hub_commit, references=None, *, memory_count=None):
    quickstart = ROOT / "docs/agent-quickstart.md"
    parts = [quickstart.read_text(encoding="utf-8") if quickstart.exists() else
             f"# Agent quickstart\n\nRead {base}/agent.json, search {API}/v1/search, and inspect a selected ID before use. Public reads need no account. Runtime execution and authenticated sharing remain separate.\n"]
    for name in ("search.md", "source-files.md", "community.md"):
        guide = ROOT / "skills/find-robot-skills/references" / name
        if guide.exists():
            parts.append(guide.read_text(encoding="utf-8"))
    for name in ("memory.md", "new-skills.md", "contributing.md", "compatibility.md", "discovery.md", "privacy.md"):
        path = ROOT / "docs" / name
        if path.exists():
            parts.append(path.read_text(encoding="utf-8"))
    parts.append(f"# Discovery resources and publication\n\nHub commit: `{hub_commit}`\n\n" +
                 discovery_text(records, base, references, memory_count=memory_count))
    return "\n\n---\n\n".join(parts) + "\n"


def publish_agent_entry_texts(output, records, base, hub_commit, references=None, *, memory_count=None):
    """Bound agent entry documents without truncating guides or catalog data."""
    write(output / "llms.txt", discovery_text(records, base, references, memory_count=memory_count), max_bytes=LLMS_TEXT_MAX_BYTES)
    write(output / "llms-full.txt", full_text(records, base, hub_commit, references, memory_count=memory_count), max_bytes=LLMS_FULL_TEXT_MAX_BYTES)


def build(args):
    records = load_records()
    references = load_references(r["id"] for r in records)
    adaptations=prepared_adaptation_map(records,references,args.base_url.rstrip('/'))
    history = load_publication_history()
    memories = load_memories()
    if args.check:
        print(f"Validated {len(records)} canonical records and recipe files; {len(references['records'])} source references")
        return
    base = args.base_url.rstrip("/")
    if urlparse(base).scheme not in ("http", "https") or not urlparse(base).hostname:
        raise ValueError("--base-url must be an http(s) URL")
    output = Path(args.output).resolve()
    hub_commit = args.hub_commit or os.environ.get("GITHUB_SHA") or git_commit()
    coverage = build_coverage(records, references, ROOT, hub_commit, base)
    update_readme(ROOT, coverage, DEFAULT_BASE)
    write_json(output / 'catalog/v1/coverage.json', coverage, max_bytes=COVERAGE_JSON_MAX_BYTES)
    write(output / 'coverage.html', shell('Robot Skill Hub coverage', 'Current pinned execution evidence and declared reference coverage.',
        '<main><h1>Robot Skill Hub coverage</h1><p>Hub commit: <code>' + esc(hub_commit) + '</code>. ' + esc(coverage['scope']) + '</p>' + coverage_tables(coverage, base, full=True) + '</main>', base, 'coverage.html'))
    for relative in ('LICENSE', 'NOTICE', 'LICENSE_SCOPE.md', 'license-policy.json', 'LICENSES/MIT.txt'):
        write(output / relative, (ROOT / relative).read_text(encoding='utf-8'))
    publish_record_evidence(records, hub_commit)
    # This is the commit of the independently cached reference resource, not a
    # source pin. Keep the editable official aggregate unchanged on disk.
    references["hub_commit"] = hub_commit
    search_manifest_url = base + "/catalog/v2/search-manifest.json"
    memory_manifest_url = base + "/catalog/v2/memory-manifest.json"
    index = {"schema_version":"1", "hub_commit":hub_commit, "catalog_url":base+"/catalog/v1/index.json", "references_url":base+"/catalog/v1/references.json", "memories_url":base+"/catalog/v1/memories.json", "search_manifest_url":search_manifest_url, "records":records}
    source_index = ROOT / "catalog/source-index.json"
    if source_index.exists():
        write(output / "catalog/v1/source-index.json", canonical(read_json(source_index)) + "\n")
    source_manifest = ROOT / "catalog/source-index-manifest.json"
    if source_manifest.exists():
        public_manifest = read_json(source_manifest)
        for prefix, descriptor in public_manifest["shards"].items():
            raw = safe_path(descriptor["path"]).read_bytes()
            require_byte_budget(raw, SOURCE_SHARD_MAX_BYTES, descriptor["path"])
            # The canonical manifest addresses files in Git. Public descriptors
            # address the mirrored bytes, without changing their checksums.
            relative = f"catalog/v1/source-index/{prefix}.json"
            destination = output / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(raw)
            descriptor.update(path=relative, url=base + "/" + relative)
        write(output / "catalog/v1/source-index-manifest.json", canonical(public_manifest) + "\n", max_bytes=SOURCE_MANIFEST_MAX_BYTES)
    source_projects = ROOT / "catalog/source-projects.json"
    if source_projects.exists():
        write(output / "catalog/v1/source-projects.json", canonical(read_json(source_projects)) + "\n")
    registry_manifests = {}
    for name in ("artifact-projects.json", "workflow-projects.json", "agent-skill-projects.json", "curated-source-projects.json"):
        manifest_path = ROOT / "catalog" / name
        if manifest_path.exists():
            relative = "catalog/v1/" + name
            write(output / relative, canonical(read_json(manifest_path)) + "\n", max_bytes=2 * 1024 * 1024)
            registry_manifests[name.removesuffix(".json")] = base + "/" + relative
    memory_proofs, memory_index = publish_memories(memories, output, base, hub_commit, return_index=True)
    contract_path = ROOT / "docs/agent-contract.json"
    contract = read_json(contract_path) if contract_path.exists() else {"schema_version": "1", "name": "Robot Skill Hub"}
    contract.update(hub_commit=hub_commit, catalog_url=index["catalog_url"], references_url=index["references_url"],
                    memories_url=index["memories_url"], publication_url=base+"/catalog/v1/publication.json")
    contract.setdefault("resources", {}).update(catalog_url=index["catalog_url"], references_url=index["references_url"],
                    memories_url=index["memories_url"], version_url=base+"/catalog/v1/version.json",
                    publication_url=base+"/catalog/v1/publication.json", quickstart_url=base+"/agent-quickstart.md",
                    full_text_url=base+"/llms-full.txt", memory_schema_url=base+"/schemas/memory.schema.json",
                    project_policy_schema_url=base+"/schemas/project-policy.schema.json",
                    search_url=API+"/v1/search", findings_url=API+"/v1/findings", search_manifest_url=search_manifest_url,
                    memory_manifest_url=memory_manifest_url, api_search_url=API+"/v1/search", mcp_url=API+"/mcp",
                    api_base_url=API, new_skill_url=API+"/v1/skills", intake_schema_url=base+"/schemas/intake.schema.json",
                    privacy_url=base+"/privacy.md", discovery_url=base+"/discovery.md", new_skills_guide_url=base+"/new-skills.md",
                    source_files_guide_url=base+"/source-files.md",
                    coverage_url=base+"/catalog/v1/coverage.json", coverage_tables_url=base+"/coverage.html",
                    coverage_api_url=API+"/v1/coverage", license_policy_url=base+"/license-policy.json",
                    executable_skills_guide_url=base+"/executable-skills.md",
                    execution_interface_schema_url=base+"/schemas/execution-interface.schema.json",
                    submission_proof_url_template=base+"/catalog/v2/submissions/{submission_id}.json",
                    memory_proof_url_template=base+"/catalog/v2/memories/{memory_id}.json")
    if (ROOT / "docs/public-api.openapi.json").exists():
        contract["resources"]["openapi_url"] = base+"/openapi.json"
    if source_index.exists():
        contract["resources"]["source_index_url"] = base+"/catalog/v1/source-index.json"
    if source_manifest.exists():
        contract["resources"]["source_index_manifest_url"] = base+"/catalog/v1/source-index-manifest.json"
    if source_projects.exists():
        contract["resources"]["source_projects_url"] = base+"/catalog/v1/source-projects.json"
    if registry_manifests:
        contract["resources"]["source_registry_manifests"] = registry_manifests
    write(output / "index.html", home(records, base, references, coverage))
    write(output / ".nojekyll", "")
    write(output / "robots.txt", f"User-agent: *\nAllow: /\nSitemap: {base}/sitemap.xml\n")
    # Public ownership proofs must survive every Pages rebuild, byte for byte.
    # Use an explicit list so unrelated local files are never published.
    for name in SITE_VERIFICATION_FILES:
        shutil.copyfile(ROOT / "docs/site-verification" / name, output / name)
    parsed_base = urlparse(base)
    if not parsed_base.hostname.endswith("github.io") and parsed_base.hostname not in ("localhost", "127.0.0.1"):
        write(output / "CNAME", parsed_base.hostname + "\n")
    elif (output / "CNAME").exists():
        (output / "CNAME").unlink()
    publish_agent_entry_texts(output, records, base, hub_commit, references, memory_count=len(memory_proofs))
    quickstart = ROOT / "docs/agent-quickstart.md"
    if quickstart.exists():
        write(output / "agent-quickstart.md", quickstart.read_text(encoding="utf-8"))
    else:
        write(output / "agent-quickstart.md", "# Agent quickstart\n\nInstall `npx skills add Superfast-Robotics/robot-skill-hub --skill find-robot-skills`. Read the installed SKILL.md, then run its bundled scripts/rsh.py. Use find → inspect → prepare; execution is separate.\n")
    for name in ("search.md", "source-files.md", "community.md"):
        guide = ROOT / "skills/find-robot-skills/references" / name
        if guide.exists():
            write(output / name, guide.read_text(encoding="utf-8"))
    for name in ("runtime-expansion.md", "agent-distribution.md", "problems.md", "contributing.md", "compatibility.md", "memory.md", "new-skills.md", "discovery.md", "privacy.md", "verification.md", "reuse-benchmark.md", "sample-sources.md", "workflow-sources.md", "agent-skill-sources.md", "robot-agent-policy-sources.md", "canonical-policy-sources.md", "platform-sources-review.md", "executable-skills.md", "coverage.md"):
        document = ROOT / "docs" / name
        if document.exists():
            text = document.read_text(encoding="utf-8")
            if name in ("runtime-expansion.md", "sample-sources.md", "workflow-sources.md", "agent-skill-sources.md", "robot-agent-policy-sources.md", "canonical-policy-sources.md", "platform-sources-review.md", "verification.md", "reuse-benchmark.md"):
                text = text.replace("](../", "](" + REPO + "/blob/" + hub_commit + "/")
            write(output / name, text)
    openapi = ROOT / "docs/public-api.openapi.json"
    if openapi.exists():
        read_json(openapi)
        shutil.copyfile(openapi, output / "openapi.json")
    server_manifest = ROOT / "server.json"
    if server_manifest.exists():
        read_json(server_manifest)
        shutil.copyfile(server_manifest, output / "server.json")
    indexnow = ROOT / "docs/indexnow-key.txt"
    if indexnow.exists():
        key = indexnow.read_text(encoding="utf-8").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", key):
            raise ValueError("Invalid public IndexNow key")
        write(output / (key + ".txt"), key + "\n")
    # The catalog has no CSS, images, fonts or client-side JavaScript. Remove only
    # known legacy runtime assets when rebuilding an existing local output folder.
    for name in ("style.css", "catalog.js"):
        legacy = output / "assets" / name
        if legacy.is_file():
            legacy.unlink()
    shutil.copytree(ROOT / "schemas", output / "schemas", dirs_exist_ok=True)
    publication_records = []
    receipts = [read_json(p) for p in sorted((ROOT / ".hub/submissions").glob("*.json"))]
    for r in records:
        folder = output / "skills" / r['id']
        write_json(folder / "skill.json", r, max_bytes=RECORD_JSON_MAX_BYTES)
        write(folder / "README.md", markdown(r, hub_commit, base))
        write(folder / "index.html", detail(r, base, hub_commit))
        # Hash canonical bytes (not enriched snapshot JSON) so the API can prove
        # the exact accepted patch made it through merge and public deployment.
        path_hashes = {p:hashlib.sha256(safe_path(p).read_bytes()).hexdigest() for p in r['contribution']['allowed_paths']}
        matching = [x for x in receipts if x.get('skill_id') == r['id'] and x.get('new_record_version') == r['maintenance']['record_version'] and all(path_hashes.get(p) == h for p, h in x.get('patch_hashes', {}).items()) and x.get('patch_hashes')]
        publication_records.append({"id":r['id'],"record_version":r['maintenance']['record_version'],"source_commit":r['source']['commit'],"recipe_url":base+"/skills/"+r['id']+"/", "compatibility":r['compatibility'],"contribution_path_hashes":path_hashes,"submission_ids":[x['submission_id'] for x in matching]})
    for r in references["records"]:
        folder = output / "references" / r["id"]
        write_json(folder / "skill.json", r, max_bytes=RECORD_JSON_MAX_BYTES)
        write(folder / "README.md", reference_markdown(r, hub_commit, adaptations=adaptations.get(r['id'],())))
        write(folder / "index.html", reference_detail(r, base, hub_commit, adaptations=adaptations.get(r['id'],())))
        intake_path = ROOT / "catalog/intake" / (r["id"] + ".json")
        if not intake_path.exists():
            continue
        relative = "catalog/intake/" + intake_path.name
        path_hashes = {relative: hashlib.sha256(intake_path.read_bytes()).hexdigest()}
        revision = r["source"].get("commit") or r["source"]["revision"]
        matching = [x for x in receipts if x.get("skill_id") == r["id"]
                    and x.get("change_kind") == "new_skill"
                    and x.get("new_record_version") == r["maintenance"]["record_version"]
                    and x.get("base", {}).get("source_commit") == revision
                    and x.get("patch_paths") == [relative] and x.get("patch_hashes") == path_hashes]
        publication_records.append({"id": r["id"], "kind": "source_reference", "record_version": r["maintenance"]["record_version"],
                                    "source_commit": revision, "recipe_url": base+"/references/"+r["id"]+"/",
                                    "compatibility": r["compatibility"], "contribution_path_hashes": path_hashes,
                                    "submission_ids": [x["submission_id"] for x in matching]})
    counts = {"recipes": len(records), "references": len(references["records"]), "memories": len(memory_proofs)}
    rows = [search_row(r, output, base, recipe=True) for r in records]
    rows.extend(search_row(r, output, base) for r in references["records"])
    for row in rows:
        if row['id'] in adaptations: row['prepared_adaptations']=adaptations[row['id']]
    page_options = {"page_max_bytes": V2_PAGE_MAX_BYTES, "page_max_records": V2_PAGE_MAX_RECORDS,
                    "manifest_max_bytes": V2_MANIFEST_MAX_BYTES}
    memory_manifest, memory_pages = paged_index(memory_index["records"], hub_commit, "memories", **page_options)
    memory_manifest_raw = v2_json_bytes(memory_manifest, compact=True)
    memory_descriptor = {"path": "catalog/v2/memory-manifest.json", "sha256": hashlib.sha256(memory_manifest_raw).hexdigest(),
                         "bytes": len(memory_manifest_raw), "records": len(memory_index["records"])}
    search_manifest, search_pages = paged_index(rows, hub_commit, "search", counts=counts,
                                               memory_manifest=memory_descriptor, **page_options)
    search_manifest_raw = v2_json_bytes(search_manifest, compact=True)
    write_exact_files(output, {**memory_pages, **search_pages, "catalog/v2/memory-manifest.json": memory_manifest_raw,
                              "catalog/v2/search-manifest.json": search_manifest_raw})
    search = {"schema_version": "1", "hub_commit": hub_commit, "counts": counts, "records": rows}
    search_bytes = (canonical(search) + "\n").encode("utf-8")
    legacy_search = optional_aggregate(output / "catalog/v1/search.json", search_bytes, SEARCH_JSON_MAX_BYTES)
    if legacy_search:
        index["search_url"] = base + "/catalog/v1/search.json"
        contract["resources"]["search_index_url"] = index["search_url"]
    else:
        contract["resources"]["search_index_url"] = search_manifest_url
    publish_compatibility(index, output / "catalog/v1/index.json",
                          ROOT / "skills/find-robot-skills/assets/catalog.snapshot.json", search_manifest_url)
    publish_compatibility(references, output / "catalog/v1/references.json",
                          ROOT / "skills/find-robot-skills/assets/references.snapshot.json", search_manifest_url)
    resources = {}
    for name in ("index", "references", "memories", "search", "coverage", "source-index", "source-index-manifest", "source-projects"):
        path = output / f"catalog/v1/{name}.json"
        if path.exists():
            resources[name] = {"url": base+f"/catalog/v1/{name}.json", "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    resources["search-manifest"] = {"url": search_manifest_url, "sha256": hashlib.sha256(search_manifest_raw).hexdigest()}
    resources["memory-manifest"] = {"url": memory_manifest_url, "sha256": hashlib.sha256(memory_manifest_raw).hexdigest()}
    write_json(output / "catalog/v1/version.json", {"schema_version": "1", "hub_commit": hub_commit,
               "counts": counts, "resources": resources}, max_bytes=VERSION_JSON_MAX_BYTES)
    manifest = {"schema_version":"1", "hub_commit":hub_commit, "catalog_url":base+"/catalog/v1/index.json", "records":publication_records, "memories":memory_proofs, "history":publish_history(history, output, base)}
    per_receipt = receipt_proofs(manifest, max_bytes=RECEIPT_PROOF_MAX_BYTES)
    write_exact_files(output, per_receipt)
    # Only recognized generated receipt filenames are eligible for cleanup.
    for folder, pattern in (("submissions", r"sub_[a-f0-9]{64}\.json"), ("memories", r"mem_[a-f0-9]{64}\.json")):
        for path in (output / "catalog/v2" / folder).glob("*.json"):
            if re.fullmatch(pattern, path.name) and path.relative_to(output).as_posix() not in per_receipt and path.is_file():
                path.unlink()
    legacy_publication = optional_aggregate(output / "catalog/v1/publication.json", v2_json_bytes(manifest), PUBLICATION_JSON_MAX_BYTES)
    if not legacy_publication:
        contract.pop("publication_url", None)
        contract["resources"].pop("publication_url", None)
    contract["community"] = {"guide_url": base + "/community.md", "api_url": API + "/v1/community",
        "publication": "immediate_after_mechanical_checks", "manager_approval_required": False,
        "identity": "self_service_pseudonymous_installation", "trust": "contributor_reported",
        "cli_commands": ["join", "inspect --project", "recall", "save", "experience", "community-sync"],
        "public_scope_required": True, "canonical_code_overwritten": False,
        "archive_url": REPO + "/tree/community-data"}
    if __package__:
        from .publish_agent_skills import publish as publish_agent_skills
    else:
        from publish_agent_skills import publish as publish_agent_skills
    skill_index_url = publish_agent_skills(ROOT, output, base, hub_commit)
    if skill_index_url:
        contract['resources']['agent_skills_index_url'] = skill_index_url
        contract['resources']['agent_skills_publication_url'] = base + '/.well-known/agent-skills/publication.json'
    write_json(output / "agent.json", contract)
    write_json(output / ".well-known/robot-skill-hub.json", contract)
    urls = [base+"/", base+"/agent.json", base+"/agent-quickstart.md", base+"/source-files.md", base+"/llms.txt", base+"/llms-full.txt", base+"/catalog/v1/index.json", base+"/catalog/v1/references.json", search_manifest_url, memory_manifest_url] + [base+"/skills/"+r['id']+"/" for r in records]
    if (output / "search.md").is_file():
        urls.append(base+"/search.md")
    if legacy_search:
        urls.append(base+"/catalog/v1/search.json")
    if legacy_publication:
        urls.append(base+"/catalog/v1/publication.json")
    urls.extend(base+"/references/"+r["id"]+"/" for r in references["records"])
    if __package__:
        from .sample_pages import publish as publish_sample_pages
        from .problem_pages import publish as publish_problem_pages
    else:
        from sample_pages import publish as publish_sample_pages
        from problem_pages import publish as publish_problem_pages
    urls.extend(publish_sample_pages(records, output, base, hub_commit, shell))
    urls.append(base+"/coverage.html")
    urls.extend(publish_problem_pages(ROOT, output, base, hub_commit))
    if openapi.exists():
        urls.append(base+"/openapi.json")
    write(output / "sitemap.xml", '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + "\n".join(f"  <url><loc>{esc(url)}</loc></url>" for url in urls) + "\n</urlset>\n")
    print(f"Built {len(records)} recipes and {len(references['records'])} source examples → {output}; hub_commit={hub_commit}; base={base}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Validate without generating files")
    parser.add_argument("--output", default=str(ROOT / "site"))
    parser.add_argument("--base-url", default=os.environ.get("SITE_BASE_URL", DEFAULT_BASE))
    parser.add_argument("--hub-commit")
    args = parser.parse_args()
    try:
        build(args)
    except (ValueError, KeyError, OSError, json.JSONDecodeError) as error:
        print(f"Catalog validation/build failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
