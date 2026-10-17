"""Validate canonical records and generate the public catalog, docs and snapshot.

Uses only Python's standard library. The schema validator implements the JSON
Schema keywords used by schemas/skill.schema.json, not arbitrary JSON Schema.
"""
import argparse
import copy
import hashlib
import html
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE = "https://superfastrobotics.com"
REPO = "https://github.com/Superfast-Robotics/robot-skill-hub"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")


def write_json(path, value):
    write(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def validate_schema(value, schema, root_schema, location="$"):
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
    if "const" in schema and value != schema["const"]:
        raise ValueError(f"{location}: expected {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{location}: unsupported value {value!r}")
    if isinstance(value, dict):
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
        if schema.get("uniqueItems") and len({json.dumps(x, sort_keys=True) for x in value}) != len(value):
            raise ValueError(f"{location}: duplicate items")
        for i, item in enumerate(value):
            validate_schema(item, schema.get("items", {}), root_schema, f"{location}[{i}]")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            raise ValueError(f"{location}: empty string")
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


def markdown(record, hub_commit):
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
python /PATH_TO_SKILL/scripts/rsh.py find "{r['capabilities'][0]}" --runtime maniskill --runtime-version {c['runtime_version']} --robot panda --json
python /PATH_TO_SKILL/scripts/rsh.py inspect {r['id']} --json
python /PATH_TO_SKILL/scripts/rsh.py prepare {r['id']} --project ./experiment --json
```

Preparation downloads the checksum-verified pinned source and creates an isolated project environment. It returns the remaining configuration. Dependency installation is an explicit `--install-deps` step; it can execute package build hooks. Robot simulation is a separate command returned by prepare, never run by find/inspect.

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


def shell(title, description, body, base, path="", extra=""):
    canonical = base.rstrip("/") + "/" + path
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title><meta name="description" content="{esc(description)}">
<link rel="canonical" href="{esc(canonical)}"><meta property="og:title" content="{esc(title)}"><meta property="og:description" content="{esc(description)}">
<meta name="theme-color" content="#0B0D10"><link rel="icon" href="{esc(base)}/assets/brand/r-light.png" type="image/png"><link rel="icon" href="{esc(base)}/assets/brand/r-dark.png" type="image/png" media="(prefers-color-scheme: dark)"><link rel="stylesheet" href="{esc(base)}/assets/style.css">{extra}</head>
<body><a class="skip-link" href="#main-content">Skip to content</a><header class="header"><a class="brand" href="{esc(base)}/" aria-label="Superfast Robotics — Robot Skill Hub home"><img src="{esc(base)}/assets/brand/wordmark-dark.png" width="1182" height="159" alt="Superfast Robotics"><span class="brand-product">ROBOT SKILL HUB</span></a><nav aria-label="Main navigation"><a href="{esc(base)}/#catalog">Catalog</a><a href="{esc(base)}/agent-quickstart.md">For agents <span aria-hidden="true">↗</span></a><a class="nav-github" href="{REPO}">GitHub <span aria-hidden="true">↗</span></a></nav></header>
{body}<footer><div class="footer-brand"><img src="{esc(base)}/assets/brand/wordmark-dark.png" width="1182" height="159" alt="Superfast Robotics"><span>ROBOT SKILL HUB / OPEN SOURCE</span></div><div class="footer-links"><a href="{esc(base)}/catalog/v1/index.json">JSON catalog ↗</a><a href="{esc(base)}/catalog/v1/publication.json">Publication manifest ↗</a><a href="{REPO}/blob/main/LICENSE">License ↗</a></div><p>Simulation code. Exact sources. Honest evidence.</p><span class="footer-coordinate" aria-hidden="true">SFR / 001</span></footer></body></html>"""


def speed_field():
    """Decorative straight light trails inspired by the name card, not a logo."""
    rays = []
    for i in range(88):
        angle = i * math.tau / 88 + .018 * (i % 3)
        start = 165 + (i * 37 % 100)
        end = start + 55 + (i * 53 % 180)
        color = "#7187FF" if i % 4 == 0 else "#EEEBDD"
        rays.append(f'<path d="M{280+math.cos(angle)*start:.1f},{260+math.sin(angle)*start:.1f} L{280+math.cos(angle)*end:.1f},{260+math.sin(angle)*end:.1f}" stroke="{color}" stroke-width="{1.2 if i % 4 == 0 else .6}" opacity="{.62 if i % 4 == 0 else .22}"/>')
    return '<svg class="speed-field" viewBox="0 0 560 520" aria-hidden="true">' + ''.join(rays) + '</svg>'


def card(record, base):
    c = record["compatibility"][0]
    evidence_label = record['evidence']['level'].replace('_', ' ').capitalize()
    runtime_label = ('Runtime unverified · 미검증' if record['evidence']['runtime_verification'] == 'not_run'
                     else record['evidence']['runtime_verification'].replace('_', ' ').capitalize())
    return f"""<article class="skill-card" data-skill="{esc(record['id'])}"><div class="card-top"><span class="task-number">{esc(record['invocation']['inputs']['task'])}</span><span class="evidence">{esc(evidence_label)}</span></div><h3><a href="{esc(base)}/skills/{esc(record['id'])}/">{esc(record['name'].replace('ManiSkill Panda ', '').replace(' Python recipe', ''))}<span>↗</span></a></h3><p>{esc(record['summary'])}</p><div class="tags"><span>{esc(c['runtime'])} {esc(c['runtime_version'])}</span><span>{esc(c['robot'])}</span><span>{esc(c['observation'])}</span></div><div class="card-meta"><span>{esc(record['license']['spdx'])}</span><code>{esc(record['source']['commit'][:7])}</code><span>v{esc(record['maintenance']['record_version'])}</span></div><div class="runtime-note">○ {esc(runtime_label)}</div><a class="card-link" href="{esc(base)}/skills/{esc(record['id'])}/">Inspect recipe <span>→</span></a></article>"""


def home(records, base):
    cards = "".join(card(r, base) for r in records)
    body = f"""<main id="main-content"><section class="hero"><div class="hero-copy"><p class="eyebrow"><span class="pulse"></span> ROBOT SKILL HUB <span class="preview">PREVIEW</span></p><h1>Robot code.<br><em>Ready to reuse.</em></h1><p class="lead">Find a starting point for your robot.<br>Inspect the source. Prepare your environment.<br>Know what has actually been verified.</p><div class="hero-actions"><a class="button" href="#catalog">Explore the catalog <span aria-hidden="true">↓</span></a><a class="text-link" href="{esc(base)}/agent-quickstart.md">Connect your agent <span aria-hidden="true">↗</span></a></div><p class="hero-foot">OPEN SOURCE <span>/</span> LOCAL EXECUTION <span>/</span> NO SIGNUP</p></div><div class="hero-visual"><div class="visual-caption"><span>SFR / OPEN ROBOTICS</span><span class="tiny-status">SOURCE → SKILL</span></div><div class="brand-field">{speed_field()}<img class="hero-symbol" src="{esc(base)}/assets/brand/r-dark.png" alt="" width="387" height="307"><span class="field-coordinate field-top" aria-hidden="true">01 — PANDA</span><span class="field-coordinate field-bottom" aria-hidden="true">PINNED / INSPECTABLE</span></div><div class="visual-footer"><div><b>Built on shared code.</b><span>Made useful through context.</span></div><span class="visual-arrow" aria-hidden="true">↗</span></div></div></section>
<section class="trust-strip" aria-label="Catalog principles"><div><span>01</span><p><strong>Know your source</strong>Exact commits and original authors.</p></div><div><span>02</span><p><strong>Match your environment</strong>Runtime, robot, controller and inputs.</p></div><div><span>03</span><p><strong>See the evidence</strong>Unrun checks stay unverified.</p></div></section>
<section class="catalog-section" id="catalog"><div class="section-heading"><div><p class="eyebrow">01 / THE CATALOG</p><h2>A starting point.<br>A source you can inspect.</h2></div><span class="count" id="result-count">{len(records)} recipes</span></div><div class="environment-strip"><span class="environment-label">FIRST ENVIRONMENT</span><p>ManiSkill 3.0.0b22 <span>/</span> Panda <span>/</span> Linux x86_64 <span>/</span> Python 3.10</p><span class="environment-status">Runtime unverified · 미검증</span></div><p class="section-description">Source-reviewed recipes. Simulation execution remains unverified. Inspect all requirements before preparing.</p>
<form class="filters" id="catalog-filters" role="search"><label class="search-field"><span aria-hidden="true">⌕</span><span class="sr-only">Search robot skills</span><input id="query" type="search" placeholder="Search grasping, stacking, pick-and-place…" autocomplete="off"></label><label><span>Runtime version</span><input id="runtime-version" placeholder="3.0.0b22" aria-label="Runtime version"></label><label><span>Robot</span><select id="robot"><option value="">Any robot</option><option value="panda">Panda</option><option value="ur5">UR5 (unsupported)</option></select></label><label><span>Controller</span><select id="controller"><option value="">Any controller</option><option>pd_joint_pos</option><option>pd_ee_delta_pose</option></select></label><label><span>OS</span><select id="os"><option value="">Any OS</option><option value="linux">Linux</option><option value="windows">Windows</option><option value="darwin">macOS</option></select></label></form>
<p class="filter-hint" id="filter-hint" aria-live="polite">Unspecified environment fields are unknown. Inspect all requirements before preparing.</p><div class="card-grid" id="catalog-results">{cards}</div><div class="empty-state" id="empty-state" hidden><h3>No recipe matches this environment.</h3><p>Explicit version, robot or controller mismatches are excluded. Try another supported environment.</p><button class="button" id="clear-filters" type="button">Clear filters</button></div></section>
<section class="agent-section" id="agents"><div><p class="eyebrow">02 / FOR YOUR CODING AGENT</p><h2>Find. Inspect.<br><em>Prepare.</em></h2><p>Search locally, inspect requirements, then prepare an isolated project. Your agent keeps the source pin and reports what actually ran.</p><a class="text-link" href="{esc(base)}/agent-quickstart.md">Read the agent quickstart ↗</a></div><div class="terminal"><div class="terminal-bar"><span class="terminal-label">TERMINAL</span><span>find-robot-skills</span><span class="terminal-cross" aria-hidden="true">+</span></div><pre><code><span class="terminal-prompt">$</span> npx skills add Superfast-Robotics/robot-skill-hub \\
  --skill find-robot-skills

<span class="comment"># from the installed skill directory</span>
python scripts/rsh.py find "pick object" \\
  --runtime maniskill --robot panda --json</code></pre><p>Search needs no GPU or API key. Preparation and simulation are separate steps.</p></div></section>
<section class="contribution-section"><div><p class="eyebrow">03 / BUILD ON WHAT WORKS</p><h2>A useful fix deserves<br>a next run.</h2></div><div><p>Save the minimal patch and its real execution evidence locally. Allowed pilot agents can submit fixes to an internal draft PR in this public repository.</p><p class="muted">Submission → review → merge → catalog publication. Each state is reported separately. Public sharing permission and a scoped token are both required.</p><a class="text-link" href="{REPO}/blob/main/docs/contributing.md">Contribution guide ↗</a></div></section></main><script src="{esc(base)}/assets/catalog.js" defer></script>"""
    return shell("Robot Skill Hub — pinned robot manipulation recipes", "Find reusable robot code for your current environment, with pinned sources and runnable examples. ManiSkill Panda grasping and stacking Python recipes.", body, base)


def detail(r, base, hub_commit):
    c = r["compatibility"][0]
    fields = [("Runtime", c['runtime'] + " " + c['runtime_version']), ("Robot", c['robot']), ("Controller", c['controller']), ("Observation", c['observation']), ("OS / architecture", c['os'] + " / " + c.get('architecture', 'unknown')), ("Python", r['requirements']['python']), ("License", r['license']['spdx']), ("Record version", r['maintenance']['record_version'])]
    rows = "".join(f"<div><dt>{esc(k)}</dt><dd>{esc(v)}</dd></div>" for k, v in fields)
    commands = f"python /PATH_TO_SKILL/scripts/rsh.py inspect {r['id']} --json\npython /PATH_TO_SKILL/scripts/rsh.py prepare {r['id']} --project ./experiment --json"
    source_links = "".join(f"<li><a href=\"{esc(r['source']['repository'])}/blob/{esc(r['source']['commit'])}/{esc(p)}\">{esc(p)} ↗</a></li>" for p in r['source']['paths'])
    body = f"""<main id="main-content" class="detail"><a class="back" href="{esc(base)}/#catalog">← All recipes</a><p class="eyebrow">MANISKILL / PANDA / MOTION PLANNING</p><h1>{esc(r['name'])}</h1><p class="lead">{esc(r['summary'])}</p><div class="detail-actions"><a class="button" href="README.md">Markdown recipe ↓</a><a class="text-link" href="skill.json">Machine-readable JSON ↗</a></div><div class="notice"><strong>Runtime: {esc(r['evidence']['runtime_verification'])} / {esc(r['evidence']['level'])}</strong><p>{esc(r['evidence']['result'])}</p></div><div class="detail-layout"><article><section><h2>Exact environment</h2><dl class="facts">{rows}</dl><p>{esc(r['observation']['description'])}</p><p class="muted">Compatibility status: {esc(c['status'])}. A match does not establish successful execution. Other versions, controllers and operating systems are unsupported or unknown.</p></section><section><h2>Prepare in your project</h2><pre><code>{esc(commands)}</code></pre><p>Preparation downloads the pinned archive, verifies its SHA256 and creates an isolated Python environment. Add <code>--install-deps</code> to install dependencies explicitly. Simulation runs only when you invoke the returned command.</p><h3>Requirements</h3><ul>{''.join('<li>' + esc(x) + '</li>' for x in r['requirements']['hardware'])}</ul><p>{esc(r['requirements']['rendering'])}</p><p><code>{esc(', '.join(r['requirements']['packages']))}</code></p><p class="muted">{esc(r['requirements']['dependency_lock'])}</p></section><section><h2>Invocation and completion</h2><p>Entrypoint: <code>{esc(r['invocation']['entrypoint'])}</code></p><pre><code>{esc(json.dumps({'argv':r['invocation']['argv'],'inputs':r['invocation']['inputs'],'outputs':r['invocation']['outputs']}, indent=2))}</code></pre><p>{esc(r['completion']['success_condition'])}</p><p>Timeout: {esc(r['completion']['timeout_seconds'])} seconds. {esc(r['completion']['stop_condition'])}</p><h3>Failure modes</h3><ul>{''.join('<li>'+esc(x)+'</li>' for x in r['completion']['failure_modes'])}</ul></section><section><h2>Actual verification</h2><p>{esc(r['evidence']['verified_by'])} · {esc(r['evidence']['date'])}</p><ul>{''.join('<li>'+esc(x)+'</li>' for x in r['evidence']['commands'])}</ul><p>Runtime status: <code>{esc(r['evidence']['runtime_verification'])}</code>. Submitter reports and hub verification remain separate.</p></section></article><aside><div class="source-panel"><p class="eyebrow">SOURCE PROVENANCE</p><h3>ManiSkill contributors</h3><a href="{esc(r['source']['repository'])}">Original repository ↗</a><p>Commit</p><code class="hash">{esc(r['source']['commit'])}</code><p>Archive SHA256</p><code class="hash">{esc(r['source']['archive_sha256'])}</code><p><a href="{esc(r['license']['url'])}">{esc(r['license']['spdx'])} license ↗</a></p><ul>{source_links}</ul><hr><p>Hub commit</p><code class="hash">{esc(hub_commit)}</code><p><a href="{REPO}/blob/main/docs/contributing.md">Submit a reusable fix ↗</a></p></div></aside></div></main>"""
    structured = json.dumps({"@context":"https://schema.org","@type":"SoftwareSourceCode","name":r['name'],"description":r['summary'],"codeRepository":r['source']['repository'],"version":r['maintenance']['record_version'],"programmingLanguage":"Python","license":r['license']['url']}).replace("<", "\\u003c")
    return shell(r['name'] + " — Robot Skill Hub", r['summary'], body, base, "skills/"+r['id']+"/", '<script type="application/ld+json">'+structured+'</script>')


def git_commit():
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, stderr=subprocess.DEVNULL, text=True).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "uncommitted"


def build(args):
    records = load_records()
    if args.check:
        print(f"Validated {len(records)} canonical records and recipe files")
        return
    base = args.base_url.rstrip("/")
    if urlparse(base).scheme not in ("http", "https"):
        raise ValueError("--base-url must be an http(s) URL")
    output = Path(args.output).resolve()
    hub_commit = args.hub_commit or os.environ.get("GITHUB_SHA") or git_commit()
    index = {"schema_version":"1", "hub_commit":hub_commit, "catalog_url":base+"/catalog/v1/index.json", "records":records}
    write_json(output / "catalog/v1/index.json", index)
    write_json(ROOT / "skills/find-robot-skills/assets/catalog.snapshot.json", index)
    write(output / "index.html", home(records, base))
    write(output / ".nojekyll", "")
    write(output / "robots.txt", f"User-agent: *\nAllow: /\nSitemap: {base}/sitemap.xml\n")
    parsed_base = urlparse(base)
    if not parsed_base.hostname.endswith("github.io") and parsed_base.hostname not in ("localhost", "127.0.0.1"):
        write(output / "CNAME", parsed_base.hostname + "\n")
    elif (output / "CNAME").exists():
        (output / "CNAME").unlink()
    write(output / "llms.txt", f"# Robot Skill Hub\n\n> Find reusable robot code for your current environment, with pinned sources and runnable examples.\n\n- [Catalog JSON]({base}/catalog/v1/index.json)\n- [Agent quickstart]({base}/agent-quickstart.md)\n- [Publication manifest]({base}/catalog/v1/publication.json)\n\n" + "\n".join(f"- [{r['name']}]({base}/skills/{r['id']}/README.md)" for r in records) + "\n\nRuntime execution is unverified unless a record explicitly provides actual task evidence.\n")
    quickstart = ROOT / "docs/agent-quickstart.md"
    if quickstart.exists():
        write(output / "agent-quickstart.md", quickstart.read_text(encoding="utf-8"))
    else:
        write(output / "agent-quickstart.md", "# Agent quickstart\n\nInstall `npx skills add Superfast-Robotics/robot-skill-hub --skill find-robot-skills`. Read the installed SKILL.md, then run its bundled scripts/rsh.py. Use find → inspect → prepare; execution is separate.\n")
    for name in ("contributing.md", "compatibility.md"):
        document = ROOT / "docs" / name
        if document.exists():
            write(output / name, document.read_text(encoding="utf-8"))
    shutil.copytree(ROOT / "web", output / "assets", dirs_exist_ok=True)
    shutil.copytree(ROOT / "schemas", output / "schemas", dirs_exist_ok=True)
    publication_records = []
    receipts = [read_json(p) for p in sorted((ROOT / ".hub/submissions").glob("*.json"))]
    for r in records:
        folder = output / "skills" / r['id']
        write_json(folder / "skill.json", r)
        write(folder / "README.md", markdown(r, hub_commit))
        write(folder / "index.html", detail(r, base, hub_commit))
        # Hash canonical bytes (not enriched snapshot JSON) so the API can prove
        # the exact accepted patch made it through merge and public deployment.
        path_hashes = {p:hashlib.sha256(safe_path(p).read_bytes()).hexdigest() for p in r['contribution']['allowed_paths']}
        matching = [x for x in receipts if x.get('skill_id') == r['id'] and x.get('new_record_version') == r['maintenance']['record_version'] and all(path_hashes.get(p) == h for p, h in x.get('patch_hashes', {}).items()) and x.get('patch_hashes')]
        publication_records.append({"id":r['id'],"record_version":r['maintenance']['record_version'],"source_commit":r['source']['commit'],"recipe_url":base+"/skills/"+r['id']+"/", "compatibility":r['compatibility'],"contribution_path_hashes":path_hashes,"submission_ids":[x['submission_id'] for x in matching]})
    manifest = {"schema_version":"1", "hub_commit":hub_commit, "catalog_url":base+"/catalog/v1/index.json", "records":publication_records}
    write_json(output / "catalog/v1/publication.json", manifest)
    urls = [base+"/"] + [base+"/skills/"+r['id']+"/" for r in records]
    write(output / "sitemap.xml", '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + "\n".join(f"  <url><loc>{esc(url)}</loc></url>" for url in urls) + "\n</urlset>\n")
    print(f"Built {len(records)} recipes → {output}; hub_commit={hub_commit}; base={base}")


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
