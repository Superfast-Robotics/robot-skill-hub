"""Verify a finite set of official robot workflow entrypoints, without running them.

The reviewed manifest names every file at a full Git commit. Normal rebuilds
read the local source cache only; --fetch explicitly retrieves those frozen text
pins. Source modules, setup files, robot drivers, models and commands are never
imported or executed. This registry supplements the existing example registries.
"""
from __future__ import annotations

import argparse
import ast
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import urllib.parse
import urllib.request

import import_ecosystem_examples as examples
from reference_index import check_source_index, write_source_index

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = "official-robot-workflows-v1"
ROLES = {"policy-serving", "policy-training", "policy-evaluation", "policy-deployment",
         "dataset-conversion", "dataset-inspection", "dataset-preparation", "data-collection",
         "trajectory-playback", "teleoperation", "calibration", "motor-configuration",
         "joint-limits", "locomotion", "joint-control", "arm-control", "obstacle-avoidance",
         "controller-input", "robot-agent", "robot-agent-evaluation", "speech-inference",
         "human-robot-interaction", "navigation-policy-inference", "perception-inference",
         "semantic-mapping", "robot-navigation-data-collection", "robot-embodiment-preparation",
         "robot-embodiment-serving", "robot-document-retrieval-serving"}


def validate_pin(pin):
    examples.safe_relative(pin["path"])
    if (not re.fullmatch(r"[a-f0-9]{64}", pin["sha256"])
            or type(pin["bytes"]) is not int or not 0 < pin["bytes"] <= examples.MAX_SOURCE_BYTES):
        raise ValueError("Every source, license and supporting document needs an exact checksum and byte size")


def label_named_by_quote(label, quote):
    """Compare whole source words in order; SDK punctuation is a separator."""
    words = iter(re.sub(r"[^a-z0-9]+", " ", quote.casefold()).split())
    return all(any(word == token for word in words) for token in label.split("-"))


def validate_project(project):
    examples.validate_project(project)
    validate_pin(project["license"])
    if not project["license"].get("scope"):
        raise ValueError("Explicit source-only license scope is required")
    if (not project.get("authors") or any(not isinstance(author, str) or not author.strip() for author in project["authors"])
            or not project.get("evidence_files")):
        raise ValueError("Upstream attribution and pinned author/setup evidence are required")
    for pin in project["evidence_files"]:
        validate_pin(pin)
        if (not pin.get("purpose") or not isinstance(pin.get("contains"), list) or not pin["contains"]
                or any(not isinstance(anchor, str) or not anchor for anchor in pin["contains"])):
            raise ValueError("Supporting evidence requires its purpose and reviewed text anchors")
    if not project.get("artifacts"):
        raise ValueError("A finite reviewed list of workflow entrypoints is required")
    paths = []
    for artifact in project["artifacts"]:
        validate_pin(artifact)
        paths.append(artifact["path"])
        if artifact.get("entrypoint_kind") not in ("python_main", "python_console_script") or not examples.selected(project, artifact["path"]):
            raise ValueError("Only explicitly selected Python workflow entrypoints are supported")
        if artifact["entrypoint_kind"] == "python_console_script":
            console = artifact.get("console_script", {})
            validate_pin(console)
            examples.safe_relative(console["package_root"])
            if (console.get("format") != "setuptools_literal_console_scripts"
                    or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", console["name"])
                    or not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", console["module"])
                    or not re.fullmatch(r"[A-Za-z_]\w*", console["function"])
                    or artifact["path"] != console["package_root"] + "/" + console["module"].replace(".", "/") + ".py"):
                raise ValueError("Console source must match a reviewed literal setuptools registration and module path")
        if artifact.get("license_scope") is not None and not artifact["license_scope"].strip():
            raise ValueError("Per-file license scope cannot be empty")
        review = artifact.get("license_review")
        if review:
            if (review.get("spdx") not in {*examples.SPDX_MARKERS, "NOASSERTION"}
                    or type(review.get("verified")) is not bool or not review.get("scope")
                    or not review.get("review_status") or not review.get("declarations")):
                raise ValueError("Per-file license review needs an explicit disposition, scope and pinned declarations")
            if review["verified"] != (review["spdx"] != "NOASSERTION"):
                raise ValueError("Unresolved licenses must remain NOASSERTION and verified false")
            for declaration in review["declarations"]:
                validate_pin(declaration)
                if not declaration.get("spdx") or not declaration.get("scope") or not declaration.get("contains"):
                    raise ValueError("Each license declaration needs exact notice bytes, anchors and its own scope")
            if review["verified"] and any(d["spdx"] != review["spdx"] for d in review["declarations"]):
                raise ValueError("Mixed license declarations cannot be automatically cleared; retain NOASSERTION")
        requirements = artifact.get("requirements", {})
        if (set(requirements) - {"python", "packages", "environment", "notes"}
                or any(not isinstance(requirements[k], str) or not requirements[k].strip()
                       for k in requirements if k != "packages")
                or ("packages" in requirements and (not isinstance(requirements["packages"], list)
                    or any(not isinstance(package, str) or not package for package in requirements["packages"])))):
            raise ValueError("Artifact requirements must be explicit Python/packages/environment/notes declarations")
        if "limitations" in artifact and (not isinstance(artifact["limitations"], list)
                or any(not isinstance(value, str) or not value for value in artifact["limitations"])):
            raise ValueError("Known limitations must be explicit nonempty text items")
        discovery = artifact.get("robot_discovery")
        if discovery is not None:
            if not isinstance(discovery, dict) or not isinstance(discovery.get("evidence"), list):
                raise ValueError("Robot discovery must carry explicit reviewed evidence")
            for pin in discovery["evidence"]:
                validate_pin(pin)
        for pin in artifact.get("capability_evidence", []):
            validate_pin(pin)
            if (not pin.get("quote") or not pin.get("capabilities") or set(pin["capabilities"]) - set(artifact["capabilities"])
                    or any(not label_named_by_quote(value, pin["quote"]) for value in pin["capabilities"])):
                raise ValueError("Added capability terms need literal pinned source-text evidence")
        if artifact.get("role") not in ROLES or not artifact.get("summary") or not artifact.get("name"):
            raise ValueError("A reviewed workflow role, name and description are required")
        if not artifact.get("capabilities") or not artifact.get("robot_types") or not artifact.get("robot_scope"):
            raise ValueError("Per-entrypoint discovery labels and their limited scope are required")
    if len(paths) != len(set(paths)):
        raise ValueError("Duplicate workflow path")


def source_bytes(cache, project, path, fetch=False):
    target = examples.cache_path(cache, project, path)
    if fetch:
        repo = project["repository"].removeprefix("https://github.com/")
        url = f"https://raw.githubusercontent.com/{repo}/{project['commit']}/{urllib.parse.quote(path, safe='/')}"
        request = urllib.request.Request(url, headers={"User-Agent": "robot-skill-hub-workflow-review/1",
                                                       "DNT": "1", "X-RSH-Telemetry": "off"})
        with urllib.request.urlopen(request, timeout=40) as response:
            data = response.read(examples.MAX_SOURCE_BYTES + 1)
        if len(data) > examples.MAX_SOURCE_BYTES:
            raise ValueError("Source exceeds the static text byte budget")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return data
    with target.open("rb") as stream:
        data = stream.read(examples.MAX_SOURCE_BYTES + 1)
    if len(data) > examples.MAX_SOURCE_BYTES:
        raise ValueError("Cached source exceeds the static text byte budget")
    return data


def checked_pin(cache, project, pin):
    data = source_bytes(cache, project, pin["path"])
    if examples.digest(data) != pin["sha256"] or len(data) != pin["bytes"]:
        raise ValueError(f"{project['id']}:{pin['path']}: immutable checksum/size mismatch")
    text = data.decode("utf-8-sig")
    if any(anchor not in text for anchor in pin.get("contains", [])):
        raise ValueError(f"{project['id']}:{pin['path']}: reviewed evidence anchor missing")
    return data


def file_url(project, path):
    return f"{project['repository']}/blob/{project['commit']}/{urllib.parse.quote(path, safe='/')}"


def require_unique_literal_binding(tree, name, expected):
    """Reject shadowing rather than resolve Python scopes or evaluate source.

    Inspect module bindings and expressions evaluated while defining functions
    or classes, not their later function bodies. Class-local names are separate
    bindings, but mutation of the selected imported object remains ambiguous.
    """
    def definition_expressions(node):
        yield from node.decorator_list
        if isinstance(node, ast.ClassDef):
            yield from node.bases
            yield from (keyword.value for keyword in node.keywords)
        else:
            yield from node.args.defaults
            yield from (value for value in node.args.kw_defaults if value is not None)
            for argument in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs,
                             node.args.vararg, node.args.kwarg]:
                if argument is not None and argument.annotation is not None:
                    yield argument.annotation
            if node.returns is not None:
                yield node.returns

    def evaluated_nodes(node, module_binding=True):
        yield node, module_binding
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for expression in definition_expressions(node):
                yield from evaluated_nodes(expression, module_binding)
            if isinstance(node, ast.ClassDef):
                for statement in node.body:
                    yield from evaluated_nodes(statement, False)
        elif isinstance(node, ast.Lambda):
            for expression in [*node.args.defaults, *node.args.kw_defaults]:
                if expression is not None:
                    yield from evaluated_nodes(expression, module_binding)
        else:
            for child in ast.iter_child_nodes(node):
                yield from evaluated_nodes(child, module_binding)

    nodes = list(evaluated_nodes(tree))
    namespace_apis = {"exec", "eval", "globals", "locals", "vars", "setattr", "delattr", "__import__"}
    namespace_names = namespace_apis | {
        alias.asname or alias.name for node, _ in nodes if isinstance(node, ast.ImportFrom)
        and node.level == 0 and node.module == "builtins" for alias in node.names if alias.name in namespace_apis}
    namespace_modules = {alias.asname or alias.name for node, _ in nodes if isinstance(node, ast.Import)
                         for alias in node.names if alias.name == "builtins"}
    bindings = []
    for node, module_binding in nodes:
        if module_binding and isinstance(node, ast.Name) and node.id == name and isinstance(node.ctx, (ast.Store, ast.Del)):
            bindings.append(node)
        elif module_binding and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == name:
            bindings.append(node)
        elif module_binding and isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.name == "*":
                    raise ValueError("Wildcard imports make the console binding ambiguous")
                bound = alias.asname or (alias.name.split(".")[0] if isinstance(node, ast.Import) else alias.name)
                if bound == name:
                    bindings.append(alias)
        elif module_binding and (isinstance(node, ast.ExceptHandler) and node.name == name
              or isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name == name
              or isinstance(node, ast.MatchMapping) and node.rest == name):
            bindings.append(node)
        elif isinstance(node, (ast.Global, ast.Nonlocal)) and name in node.names:
            raise ValueError("Dynamic scope declarations make the console binding ambiguous")
        elif isinstance(node, (ast.Attribute, ast.Subscript)) and isinstance(node.ctx, (ast.Store, ast.Del)):
            receiver = node.value
            while isinstance(receiver, (ast.Attribute, ast.Subscript)):
                receiver = receiver.value
            if isinstance(receiver, ast.Name) and receiver.id == name:
                raise ValueError("Mutating the console binding is outside the reviewed literal subset")
        elif isinstance(node, ast.Attribute) and node.attr == "__dict__":
            receiver = node.value
            while isinstance(receiver, (ast.Attribute, ast.Subscript)):
                receiver = receiver.value
            if isinstance(receiver, ast.Name) and receiver.id == name:
                raise ValueError("Dynamic console binding dictionaries are outside the reviewed literal subset")
        elif (isinstance(node, ast.Call)
              and (isinstance(node.func, ast.Name) and node.func.id in namespace_names
                   or isinstance(node.func, ast.Attribute) and node.func.attr in namespace_apis
                   and isinstance(node.func.value, ast.Name) and node.func.value.id in namespace_modules)):
            raise ValueError("Dynamic namespace APIs make the console binding ambiguous")
    if len(bindings) != 1 or bindings[0] is not expected:
        raise ValueError("Console binding is ambiguous, reassigned or deleted")
    if isinstance(expected, (ast.FunctionDef, ast.AsyncFunctionDef)) and expected.decorator_list:
        raise ValueError("Decorated console targets are outside the reviewed literal subset")


def inspect_console_source(project, artifact, cache, data):
    """Read a literal setup declaration and target AST; never evaluate setup.py."""
    console = artifact["console_script"]
    setup_tree = ast.parse(checked_pin(cache, project, console).decode("utf-8-sig"), filename=console["path"])
    setup_names = {alias.asname or alias.name: (node, alias) for node in setup_tree.body if isinstance(node, ast.ImportFrom)
                   and node.level == 0 and node.module == "setuptools" for alias in node.names if alias.name == "setup"}
    module_names = {alias.asname or alias.name: (node, alias) for node in setup_tree.body if isinstance(node, ast.Import)
                    for alias in node.names if alias.name == "setuptools"}
    for name, (_, alias) in {**setup_names, **module_names}.items():
        require_unique_literal_binding(setup_tree, name, alias)
    registrations = []
    for node in setup_tree.body:
        if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
            continue
        call = node.value
        imported_setup = (isinstance(call.func, ast.Name) and call.func.id in setup_names
                          or isinstance(call.func, ast.Attribute) and call.func.attr == "setup"
                          and isinstance(call.func.value, ast.Name) and call.func.value.id in module_names)
        if not imported_setup:
            continue
        binding = (setup_names[call.func.id][0] if isinstance(call.func, ast.Name)
                   else module_names[call.func.value.id][0])
        if (call.lineno, call.col_offset) <= (binding.lineno, binding.col_offset):
            raise ValueError("Console setup alias must be imported before its literal call")
        if any(keyword.arg is None for keyword in call.keywords):
            raise ValueError("Dynamic setuptools keyword expansion is outside the reviewed console subset")
        for keyword in call.keywords:
            if keyword.arg != "entry_points":
                continue
            if not isinstance(keyword.value, ast.Dict):
                raise ValueError("Console entry_points must be a literal setuptools dictionary")
            for key, value in zip(keyword.value.keys, keyword.value.values):
                if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                    raise ValueError("Dynamic console registration keys are outside the reviewed literal subset")
                if key.value != "console_scripts":
                    continue
                if not isinstance(value, (ast.List, ast.Tuple)) or any(not isinstance(item, ast.Constant) or not isinstance(item.value, str) for item in value.elts):
                    raise ValueError("Every relevant console registration must be a literal string")
                registrations.extend(item.value for item in value.elts)
    pattern = re.compile(r"\s*" + re.escape(console["name"]) + r"\s*=\s*" + re.escape(console["module"])
                         + ":" + re.escape(console["function"]) + r"\s*")
    command_pattern = re.compile(r"\s*([A-Za-z0-9][A-Za-z0-9_.-]*)\s*=\s*(.+?)\s*")
    parsed = [command_pattern.fullmatch(value) for value in registrations]
    if any(value is None for value in parsed):
        raise ValueError("Malformed literal console registration is outside the reviewed subset")
    named = [value for value, parsed_value in zip(registrations, parsed) if parsed_value[1] == console["name"]]
    if len(named) != 1 or not pattern.fullmatch(named[0]):
        raise ValueError("Exact literal setuptools console registration is missing or ambiguous")
    tree = ast.parse(data.decode("utf-8-sig"), filename=artifact["path"])
    functions = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == console["function"]]
    if not functions:
        raise ValueError("Registered console target is not a top-level source function")
    require_unique_literal_binding(tree, console["function"], functions[0])
    imports = sorted({node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
                     | {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names})
    return {"kind": "python_console_script", "imports": imports}


def observed_license_identifiers(text):
    identifiers = set(re.findall(r"SPDX-License-Identifier:\s*([^\r\n]+)", text[:6000]))
    identifiers = {value.strip().rstrip("*/ ") for value in identifiers}
    if re.search(r"^#\s*MIT License\s*$", text[:6000], re.M):
        identifiers.add("MIT")
    if re.search(r"^#\s*Licensed under the Apache License, Version 2\.0", text[:6000], re.M):
        identifiers.add("Apache-2.0")
    return identifiers


def reviewed_license(project, artifact, cache, text):
    review = artifact.get("license_review")
    observed = observed_license_identifiers(text)
    if not review:
        if observed - {project["license"]["spdx"]} or not examples.compatible_file_license(project, text):
            raise ValueError("Unreviewed different or mixed source license; explicit scoped review is required")
        return None
    declarations = review["declarations"]
    for declaration in declarations:
        checked_pin(cache, project, declaration)
    if observed - {declaration["spdx"] for declaration in declarations}:
        raise ValueError("Explicit source license is missing from the pinned per-file review")
    if review["verified"]:
        marker = examples.SPDX_MARKERS[review["spdx"]]
        if not any(marker in checked_pin(cache, project, pin).decode("utf-8-sig") for pin in declarations):
            raise ValueError("Resolved license review lacks its pinned license text")
    # Unresolved source is linked, with both declarations retained; no grant is inferred.
    identity = declarations[0] if review["verified"] else artifact
    return {"spdx": review["spdx"], "url": file_url(project, identity["path"]),
            "sha256": identity["sha256"], "bytes": identity["bytes"], "verified": review["verified"],
            "scope": review["scope"], "review_status": review["review_status"],
            "upstream_declarations": [{"spdx": pin["spdx"], "scope": pin["scope"], "url": file_url(project, pin["path"]),
                                       "sha256": pin["sha256"], "bytes": pin["bytes"]} for pin in declarations]}


def static_source_record(project, artifact, inspection):
    """The normal example record shape for separately reviewed console/notice cases."""
    path = artifact["path"]
    suffix = re.sub(r"[^a-z0-9]+", "-", path.lower()).strip("-")
    ident = project["id"] + "-" + suffix
    if len(ident) > 80:
        ident = ident[:67].rstrip("-") + "-" + examples.digest(path.encode())[:12]
    return {"id": ident, "framework": project["id"], "kind": "official_example",
            "source": {"repository": project["repository"], "commit": project["commit"], "tag": project["ref"], "path": path,
                       "url": file_url(project, path), "raw_url": project["repository"].replace("https://github.com/", "https://raw.githubusercontent.com/")
                       + "/" + project["commit"] + "/" + urllib.parse.quote(path, safe="/"), "sha256": artifact["sha256"], "bytes": artifact["bytes"]},
            "license": {"spdx": project["license"]["spdx"], "url": file_url(project, project["license"]["path"]),
                        "sha256": project["license"]["sha256"], "scope": project["license"]["scope"]},
            "access": {"mode": "source_reference", "hub_prepare": False,
                       "instructions": "Fetch the pinned repository, verify this source checksum, and use upstream installation and invocation. This record does not install or execute code.",
                       "setup_url": project["setup_url"]},
            "requirements": {"python": project["requirements"]["python"], "packages": project["requirements"]["packages"],
                             "display": project["requirements"]["environment"], "execution_domain": project["execution_domain"], "source_imports": inspection["imports"]},
            "invocation": {"entrypoint": artifact.get("entrypoint", "python " + path), "notes": project["invocation_notes"]},
            "popularity": {"metric": "github_stars", "repository_stars": project["stars"], "checked_at": project["checked_at"],
                           "meaning": "Dated repository interest, not robot-skill usage, compatibility or runtime success."},
            "evidence": {"level": "source_reviewed", "runtime_verification": "not_run", "checked_at": project["checked_at"],
                         "entrypoint_kind": inspection["kind"], "inspection_method": "automated_static"}}


def make_record(project, artifact, cache):
    data = checked_pin(cache, project, artifact)
    inspection = (inspect_console_source(project, artifact, cache, data) if artifact["entrypoint_kind"] == "python_console_script"
                  else examples.inspect_source(artifact["path"], data))
    if inspection["kind"] != artifact["entrypoint_kind"]:
        raise ValueError("Workflow entrypoint differs from its reviewed manifest")
    license_info = reviewed_license(project, artifact, cache, data.decode("utf-8-sig"))
    record = (examples.make_record(project, artifact, cache) if inspection["kind"] == "python_main" and license_info is None
              else static_source_record(project, artifact, inspection))
    record.update(name=f"{project['name']}: {artifact['name']}", summary=artifact["summary"],
                  source_registry=REGISTRY, capabilities=sorted(set(artifact["capabilities"])),
                  robot_types=artifact["robot_types"], robot_scope=artifact["robot_scope"],
                  artifact={"kind": "workflow", "format": "python", "workflow_role": artifact["role"]})
    record["source"]["authors"] = artifact.get("authors", project["authors"])
    record["license"]["bytes"] = project["license"]["bytes"]
    if artifact.get("license_scope"):
        record["license"]["scope"] = artifact["license_scope"]
    if license_info:
        record["license"] = license_info
    record["access"]["setup_evidence"] = [
        {"path": pin["path"], "url": file_url(project, pin["path"]), "sha256": pin["sha256"],
         "bytes": pin["bytes"], "purpose": pin["purpose"]} for pin in project["evidence_files"]]
    if artifact.get("entrypoint"):
        record["invocation"]["entrypoint"] = artifact["entrypoint"]
    record["invocation"]["notes"] = artifact.get("invocation_notes", project["invocation_notes"])
    record["requirements"]["execution_domain"] = artifact.get("execution_domain", project["execution_domain"])
    for key, value in artifact.get("requirements", {}).items():
        record["requirements"]["display" if key == "environment" else key] = value
    if artifact.get("declared_requirements"):
        record["requirements"]["declared_requirements"] = artifact["declared_requirements"]
    if artifact.get("limitations"):
        record["evidence"]["limitations"] = artifact["limitations"]
    discovery = examples.reviewed_robot_discovery(project, artifact, cache)
    if discovery is not None:
        record["robots"] = discovery.pop("labels")
        record["evidence"]["robot_discovery"] = discovery
    for pin in artifact.get("capability_evidence", []):
        if pin["quote"] not in checked_pin(cache, project, pin).decode("utf-8-sig"):
            raise ValueError("Capability evidence quote is absent from its pinned source")
    record["evidence"]["inspection"] = (
        "Verified exact source, applicable license and author/setup document bytes at a full Git commit; "
        "parsed the Python AST and reviewed this guarded operational entrypoint and its explicit license notices. "
        "No upstream code, installation, robot command, dataset, mesh or checkpoint was executed or loaded.")
    if inspection["kind"] == "python_console_script":
        record["evidence"]["inspection"] = (
            "Verified exact source, setup registration, scoped license notice and author/setup bytes at a full Git commit; "
            "parsed Python AST and matched a literal setuptools console registration to its top-level source function. "
            "No setup file, source module, installation, robot command, dataset, mesh or checkpoint was executed or loaded.")
        record["evidence"]["console_registration"] = {"url": file_url(project, artifact["console_script"]["path"]),
            "sha256": artifact["console_script"]["sha256"], "bytes": artifact["console_script"]["bytes"],
            "name": artifact["console_script"]["name"], "target": artifact["console_script"]["module"] + ":" + artifact["console_script"]["function"]}
    return record


def merge_records(existing, generated):
    retained = [record for record in existing if record.get("source_registry") != REGISTRY]
    records = retained + generated
    ids = [record["id"] for record in records]
    pins = [(record["source"]["repository"], record["source"].get("commit", record["source"].get("revision")),
             record["source"]["path"]) for record in records]
    if len(ids) != len(set(ids)) or len(pins) != len(set(pins)):
        raise ValueError("Duplicate reference id or immutable artifact; resolve ownership before import")
    return sorted(records, key=lambda record: (record["framework"], record["id"]))


def build(manifest, cache, existing, fetch=False):
    if manifest.get("schema_version") != "1":
        raise ValueError("Unsupported workflow manifest schema")
    projects = manifest["projects"]
    if len({project["id"] for project in projects}) != len(projects):
        raise ValueError("Duplicate workflow project id")
    generated = []
    for project in projects:
        validate_project(project)
        pins = [project["license"], *project["evidence_files"], *project["artifacts"]]
        for artifact in project["artifacts"]:
            if artifact.get("console_script"):
                pins.append(artifact["console_script"])
            pins.extend(artifact.get("license_review", {}).get("declarations", []))
            pins.extend(artifact.get("robot_discovery", {}).get("evidence", []))
            pins.extend(artifact.get("capability_evidence", []))
        if fetch:
            # Fetch only predeclared bounded text pins. No upstream tree discovery.
            paths = sorted({pin["path"] for pin in pins})
            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(lambda path: source_bytes(cache, project, path, True), paths))
        for pin in pins:
            checked_pin(cache, project, pin)
        examples.checked_license(project, cache)
        generated.extend(make_record(project, artifact, cache) for artifact in project["artifacts"])
    return {**existing, "workflow_manifest": "workflow-projects.json",
            "records": merge_records(existing["records"], generated)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / "catalog/workflow-projects.json")
    parser.add_argument("--cache", type=Path, default=ROOT / ".local/workflow-review")
    parser.add_argument("--output", type=Path, default=ROOT / "catalog/references.json")
    parser.add_argument("--fetch", action="store_true", help="Explicitly fetch only the manifest's immutable text pins")
    parser.add_argument("--check", action="store_true", help="Offline comparison against the published references/index; write nothing")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    existing = json.loads(args.output.read_text(encoding="utf-8"))
    result = build(manifest, args.cache, existing, args.fetch)
    if args.check:
        if result != existing:
            raise ValueError("Catalog differs from its reviewed robot workflow manifest")
        check_source_index(result["records"], args.output.parent / "source-index.json")
    else:
        examples.write_json(args.output, result)
        write_source_index(result["records"], args.output.parent / "source-index.json")
    count = sum(len(project["artifacts"]) for project in manifest["projects"])
    print(f"Validated {count} official workflow entrypoints across {len(manifest['projects'])} frozen project selections; no upstream code executed")


if __name__ == "__main__":
    main()
