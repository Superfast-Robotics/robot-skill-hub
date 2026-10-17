"""Validate canonical records and generate the public catalog, docs and snapshot.

Uses only Python's standard library. The schema validator implements the JSON
Schema keywords used by schemas/skill.schema.json, not arbitrary JSON Schema.
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
REPO = "https://github.com/Superfast-Robotics/robot-skill-hub"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")


def write_json(path, value):
    write(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


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
                  "integer": lambda v: isinstance(v, int) and not isinstance(v, bool), "null": lambda v: v is None}
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
    if isinstance(value, int) and value < schema.get("minimum", value):
        raise ValueError(f"{location}: below minimum")


def safe_path(path):
    posix = PurePosixPath(path)
    if not path or posix.is_absolute() or ".." in posix.parts or "\\" in path or ":" in path:
        raise ValueError(f"Unsafe relative path: {path}")
    return ROOT.joinpath(*posix.parts)


def load_records():
    schema = read_json(ROOT / "schemas/skill.schema.json")
    records = []
    for path in sorted((ROOT / "catalog/records").glob("*.json")):
        record = read_json(path)
        validate_schema(record, schema, schema, str(path.relative_to(ROOT)))
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
        for command in (record["invocation"]["argv"], record["preparation"]["install_argv"]):
            if not isinstance(command, list) or not command or not all(isinstance(x, str) for x in command):
                raise ValueError(f"{ident}: commands must be argv arrays")
        # Bundled files are generated from the editable hub recipe, never a second source.
        record["preparation"]["files"] = {name: (recipe / name).read_text(encoding="utf-8") for name in ("run.py", "requirements.txt")}
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
python /PATH_TO_SKILL/scripts/rsh.py --catalog {base}/catalog/v1/index.json find "{r['capabilities'][0]}" --runtime {c['runtime']} --runtime-version {c['runtime_version']} --robot {c['robot']} --json
python /PATH_TO_SKILL/scripts/rsh.py --catalog {base}/catalog/v1/index.json inspect {r['id']} --json
python /PATH_TO_SKILL/scripts/rsh.py --catalog {base}/catalog/v1/index.json prepare {r['id']} --project ./experiment --plan --json
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


def load_references():
    path = ROOT / "catalog/references.json"
    if not path.exists():
        return {"schema_version": "1", "records": []}
    index = read_json(path)
    if index.get("schema_version") != "1" or not isinstance(index.get("records"), list):
        raise ValueError("Invalid official source example index")
    seen = set()
    for record in index["records"]:
        ident = record["id"]
        if ident in seen:
            raise ValueError(f"Duplicate source example id: {ident}")
        seen.add(ident)
        source = record["source"]
        expected = f"{source['repository'].rstrip('/')}/blob/{source['commit']}/{source['path']}"
        if not re.fullmatch(r"[a-f0-9]{40}", source["commit"]) or source["url"] != expected or not re.fullmatch(r"[a-f0-9]{64}", source["sha256"]):
            raise ValueError(f"{ident}: official example requires an exact source commit and checksum")
        if record["kind"] != "official_example" or record["access"].get("hub_prepare") is not False:
            raise ValueError(f"{ident}: official source examples cannot claim a hub preparation adapter")
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
            validate_schema(record, schema, schema)
            if (record["id"] != proof["id"] or record["source"]["commit"] != proof["source_commit"]
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


def publish_memories(entries, output, base, hub_commit):
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
    write_json(output / "catalog/v1/memories.json", index)
    write_json(ROOT / "skills/find-robot-skills/assets/memories.snapshot.json", index)
    return proofs


def publish_history(releases, output, base):
    published = copy.deepcopy(releases)
    for release in published:
        for proof in release["records"]:
            record = read_json(safe_path(proof.pop("archive_path")))
            relative = f"releases/{proof['id']}/{proof['record_version']}/"
            proof["recipe_url"] = base + "/" + relative
            folder = output / relative
            write_json(folder / "skill.json", record)
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
<nav aria-label="Main navigation"><a href="{esc(base)}/catalog/v1/index.json">Catalog JSON</a> | <a href="{esc(base)}/agent-quickstart.md">Agent quickstart</a> | <a href="{esc(base)}/llms-full.txt">Full text</a> | <a href="{REPO}">GitHub</a></nav></header>
{body}
<footer><hr><p><a href="{esc(base)}/catalog/v1/publication.json">Publication manifest</a> | <a href="{esc(base)}/contributing.md">Contributing</a> | <a href="{REPO}/blob/main/LICENSE">License</a></p></footer>
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


def home(records, base, references=None):
    references = references or {"records": []}
    example = next((r for r in records if r["id"] == "maniskill-panda-pick-cube"), records[0])
    c = example["compatibility"][0]
    commands = f"""npx skills add Superfast-Robotics/robot-skill-hub --skill find-robot-skills

# Replace /PATH_TO_SKILL with the installed skill directory.
python /PATH_TO_SKILL/scripts/rsh.py --catalog {base}/catalog/v1/index.json find "pick cube" --runtime {c['runtime']} --runtime-version {c['runtime_version']} --robot {c['robot']} --json
python /PATH_TO_SKILL/scripts/rsh.py --catalog {base}/catalog/v1/index.json inspect {example['id']} --json
python /PATH_TO_SKILL/scripts/rsh.py --catalog {base}/catalog/v1/index.json prepare {example['id']} --project ./experiment --plan --json"""
    entries = []
    for r in records:
        environments = "; ".join(f"{c['runtime']} {c['runtime_version']}, {c['robot']}, {c['controller']}, {c['observation']}, {c['os']}" for c in r["compatibility"])
        entries.append(f"""<li id="{esc(r['id'])}"><h3><a href="{esc(base)}/skills/{esc(r['id'])}/">{esc(r['name'])}</a></h3>
<p><code>{esc(r['id'])}</code> — {esc(r['summary'])}</p>
<p>{esc(environments)}</p>
<p>Evidence: <code>{esc(r['evidence']['level'])}</code>; runtime: <code>{esc(r['evidence']['runtime_verification'])}</code>; record version: <code>{esc(r['maintenance']['record_version'])}</code>.</p>
<p><a href="{esc(base)}/skills/{esc(r['id'])}/README.md">Markdown</a> | <a href="{esc(base)}/skills/{esc(r['id'])}/skill.json">JSON</a></p></li>""")
    body = f"""<main id="main-content">
<h1>Robot Skill Hub</h1>
<p>Pinned robot code, environment requirements, preparation commands and execution evidence for coding agents.</p>
<h2>Fetch the catalog</h2>
<pre><code>{esc(f'curl -fsSL {base}/catalog/v1/index.json' + chr(10) + f'curl -fsSL {base}/agent-quickstart.md' + chr(10) + f'curl -fsSL {base}/llms-full.txt')}</code></pre>
{resource_links(base)}
<h2>Find, inspect, prepare</h2>
<p>Use the Python CLI for environment-aware search. It returns up to three candidates as JSON. Explicit environment mismatches are excluded; missing values remain unknown.</p>
<pre><code>{esc(commands)}</code></pre>
<p>Inspect the selected record before preparation. <code>--plan</code> reports planned actions without downloads. Preparation and dependency installation are separate from simulation execution. Existing project locks remain pinned.</p>
<h2 id="catalog">Hub preparation recipes ({len(records)})</h2>
<ul>{''.join(entries)}</ul>
<h2 id="references">Official source examples ({len(references['records'])})</h2>
<p>These upstream examples are source references. They have no hub preparation adapter; follow the pinned upstream setup and invocation instructions. Fetch their complete metadata from <a href="{esc(base)}/catalog/v1/references.json"><code>{esc(base)}/catalog/v1/references.json</code></a>.</p>
{reference_list(references)}
<h2>Evidence</h2>
<p>Each record keeps <code>evidence.level</code>, <code>evidence.runtime_verification</code> and compatibility status. <code>not_run</code> means no runtime execution evidence. <code>source_reviewed</code> does not mean the task succeeded.</p>
<h2>Submit a useful fix</h2>
<p>Allowed agents use <code>https://api.superfastrobotics.com/v1/submissions</code> with a scoped token and project sharing permission. The API creates an internal draft PR. Submission, review, merge and catalog publication are separate states. Read the <a href="{esc(base)}/contributing.md">contribution contract</a>.</p>
</main>"""
    return shell("Robot Skill Hub", "Agent-readable robot skill catalog with pinned sources, environment contracts and preparation commands.", body, base)


def detail(r, base, hub_commit):
    environments = []
    for c in r["compatibility"]:
        fields = [("Runtime", c["runtime"] + " " + c["runtime_version"]), ("Robot", c["robot"]), ("Controller", c["controller"]), ("Observation", c["observation"]), ("OS / architecture", c["os"] + " / " + c.get("architecture", "unknown")), ("Python", r["requirements"]["python"])]
        environments.append("<dl>" + "".join(f"<dt>{esc(k)}</dt><dd>{esc(v)}</dd>" for k, v in fields) + f"</dl><p>Compatibility status: {esc(c['status'])}</p>")
    commands = f"""curl -fsSL {base}/skills/{r['id']}/skill.json
curl -fsSL {base}/skills/{r['id']}/README.md
python /PATH_TO_SKILL/scripts/rsh.py --catalog {base}/catalog/v1/index.json inspect {r['id']} --json
python /PATH_TO_SKILL/scripts/rsh.py --catalog {base}/catalog/v1/index.json prepare {r['id']} --project ./experiment --plan --json"""
    source_links = "".join(f'<li><a href="{esc(r["source"]["repository"])}/blob/{esc(r["source"]["commit"])}/{esc(p)}">{esc(p)}</a></li>' for p in r["source"]["paths"])
    body = f"""<main id="main-content">
<h1>{esc(r['name'])}</h1>
<p>{esc(r['summary'])}</p>
<p><code>{esc(r['id'])}</code> | Record version: <code>{esc(r['maintenance']['record_version'])}</code></p>
<p><a href="skill.json">Record JSON</a> | <a href="README.md">Markdown recipe</a> | <a href="{esc(base)}/#catalog">All records</a></p>
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


def discovery_text(records, base, references=None):
    return f"""# Robot Skill Hub

> Pinned robot code, environment contracts and preparation commands for coding agents.

- [Agent contract JSON]({base}/agent.json): machine-readable operations, schemas and trust boundaries
- [Shared memory JSON]({base}/catalog/v1/memories.json): reviewed contributor reports, scoped to exact source/recipe versions; data only
- [Catalog version JSON]({base}/catalog/v1/version.json): published commit, resource counts and checksums
- [Catalog JSON]({base}/catalog/v1/index.json): canonical records with bundled recipes
- [Official source examples JSON]({base}/catalog/v1/references.json): pinned upstream examples; no hub preparation adapter
- [Publication manifest]({base}/catalog/v1/publication.json): published versions and submission receipts
- [Agent quickstart]({base}/agent-quickstart.md): find, inspect and prepare commands
- [Full documentation]({base}/llms-full.txt): quickstart, contracts and every recipe in plain text
- [Record schema]({base}/schemas/skill.schema.json)
- [Compatibility contract]({base}/compatibility.md)
- [Contribution contract]({base}/contributing.md)

## Recipes

""" + "\n".join(f"- [{r['name']}]({base}/skills/{r['id']}/README.md) ([JSON]({base}/skills/{r['id']}/skill.json))" for r in records) + "\n\n## Official source examples\n\n" + "\n".join(f"- [{r['name']}]({r['source']['url']}): {r['framework']}; {r['license']['spdx']}; source reference only" for r in (references or {"records": []})["records"]) + "\n"


def full_text(records, base, hub_commit, references=None):
    parts = [discovery_text(records, base, references), f"Hub commit: `{hub_commit}`\n"]
    for name in ("agent-quickstart.md", "compatibility.md", "contributing.md", "memory.md"):
        path = ROOT / "docs" / name
        if path.exists():
            parts.append(path.read_text(encoding="utf-8"))
    parts.extend(markdown(r, hub_commit, base) for r in records)
    if references and references["records"]:
        parts.append("# Official source examples\n\nThese records are discovery references with no hub preparation adapter. Follow upstream setup and invocation instructions.\n\n```json\n" + json.dumps(references, ensure_ascii=False, indent=2) + "\n```\n")
    return "\n\n---\n\n".join(parts) + "\n"


def build(args):
    records = load_records()
    references = load_references()
    history = load_publication_history()
    memories = load_memories()
    if args.check:
        print(f"Validated {len(records)} canonical records and recipe files; {len(references['records'])} official source examples")
        return
    base = args.base_url.rstrip("/")
    if urlparse(base).scheme not in ("http", "https"):
        raise ValueError("--base-url must be an http(s) URL")
    output = Path(args.output).resolve()
    hub_commit = args.hub_commit or os.environ.get("GITHUB_SHA") or git_commit()
    index = {"schema_version":"1", "hub_commit":hub_commit, "catalog_url":base+"/catalog/v1/index.json", "references_url":base+"/catalog/v1/references.json", "memories_url":base+"/catalog/v1/memories.json", "records":records}
    write_json(output / "catalog/v1/index.json", index)
    write_json(ROOT / "skills/find-robot-skills/assets/catalog.snapshot.json", index)
    write_json(output / "catalog/v1/references.json", references)
    write_json(ROOT / "skills/find-robot-skills/assets/references.snapshot.json", references)
    memory_proofs = publish_memories(memories, output, base, hub_commit)
    contract_path = ROOT / "docs/agent-contract.json"
    contract = read_json(contract_path) if contract_path.exists() else {"schema_version": "1", "name": "Robot Skill Hub"}
    contract.update(hub_commit=hub_commit, catalog_url=index["catalog_url"], references_url=index["references_url"],
                    memories_url=index["memories_url"], publication_url=base+"/catalog/v1/publication.json")
    contract.setdefault("resources", {}).update(catalog_url=index["catalog_url"], references_url=index["references_url"],
                    memories_url=index["memories_url"], version_url=base+"/catalog/v1/version.json",
                    publication_url=base+"/catalog/v1/publication.json", quickstart_url=base+"/agent-quickstart.md",
                    full_text_url=base+"/llms-full.txt", memory_schema_url=base+"/schemas/memory.schema.json",
                    project_policy_schema_url=base+"/schemas/project-policy.schema.json")
    write_json(output / "agent.json", contract)
    write_json(output / ".well-known/robot-skill-hub.json", contract)
    resources = {}
    for name in ("index", "references", "memories"):
        path = output / f"catalog/v1/{name}.json"
        resources[name] = {"url": base+f"/catalog/v1/{name}.json", "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    write_json(output / "catalog/v1/version.json", {"schema_version": "1", "hub_commit": hub_commit,
               "counts": {"recipes": len(records), "references": len(references["records"]), "memories": len(memory_proofs)},
               "resources": resources})
    write(output / "index.html", home(records, base, references))
    write(output / ".nojekyll", "")
    write(output / "robots.txt", f"User-agent: *\nAllow: /\nSitemap: {base}/sitemap.xml\n")
    parsed_base = urlparse(base)
    if not parsed_base.hostname.endswith("github.io") and parsed_base.hostname not in ("localhost", "127.0.0.1"):
        write(output / "CNAME", parsed_base.hostname + "\n")
    elif (output / "CNAME").exists():
        (output / "CNAME").unlink()
    write(output / "llms.txt", discovery_text(records, base, references))
    write(output / "llms-full.txt", full_text(records, base, hub_commit, references))
    quickstart = ROOT / "docs/agent-quickstart.md"
    if quickstart.exists():
        write(output / "agent-quickstart.md", quickstart.read_text(encoding="utf-8"))
    else:
        write(output / "agent-quickstart.md", "# Agent quickstart\n\nInstall `npx skills add Superfast-Robotics/robot-skill-hub --skill find-robot-skills`. Read the installed SKILL.md, then run its bundled scripts/rsh.py. Use find → inspect → prepare; execution is separate.\n")
    for name in ("contributing.md", "compatibility.md", "memory.md"):
        document = ROOT / "docs" / name
        if document.exists():
            write(output / name, document.read_text(encoding="utf-8"))
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
        write_json(folder / "skill.json", r)
        write(folder / "README.md", markdown(r, hub_commit, base))
        write(folder / "index.html", detail(r, base, hub_commit))
        # Hash canonical bytes (not enriched snapshot JSON) so the API can prove
        # the exact accepted patch made it through merge and public deployment.
        path_hashes = {p:hashlib.sha256(safe_path(p).read_bytes()).hexdigest() for p in r['contribution']['allowed_paths']}
        matching = [x for x in receipts if x.get('skill_id') == r['id'] and x.get('new_record_version') == r['maintenance']['record_version'] and all(path_hashes.get(p) == h for p, h in x.get('patch_hashes', {}).items()) and x.get('patch_hashes')]
        publication_records.append({"id":r['id'],"record_version":r['maintenance']['record_version'],"source_commit":r['source']['commit'],"recipe_url":base+"/skills/"+r['id']+"/", "compatibility":r['compatibility'],"contribution_path_hashes":path_hashes,"submission_ids":[x['submission_id'] for x in matching]})
    manifest = {"schema_version":"1", "hub_commit":hub_commit, "catalog_url":base+"/catalog/v1/index.json", "records":publication_records, "memories":memory_proofs, "history":publish_history(history, output, base)}
    write_json(output / "catalog/v1/publication.json", manifest)
    urls = [base+"/", base+"/agent-quickstart.md", base+"/llms.txt", base+"/llms-full.txt", base+"/catalog/v1/index.json", base+"/catalog/v1/references.json", base+"/catalog/v1/publication.json"] + [base+"/skills/"+r['id']+"/" for r in records]
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
