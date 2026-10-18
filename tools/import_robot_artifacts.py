"""Verify reviewed robot model/configuration references without running them.

The explicit artifact manifest pins every source and its applicable license.
Normal builds are offline. --fetch retrieves only those text files at full
immutable commits; it never expands Xacro, resolves XML includes, loads a model,
installs a package, downloads weights/meshes, or executes upstream code.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from import_ecosystem_examples import cache_path, safe_relative
from reference_index import check_source_index, write_source_index

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = "official-robot-artifacts-v1"
MAX_BYTES = 2 * 1024 * 1024
LICENSE_MARKERS = {
    "Apache-2.0": ("Apache License", "Version 2.0"),
    "MIT": ("Permission is hereby granted, free of charge", "THE SOFTWARE IS PROVIDED"),
    "BSD-2-Clause": ("Redistribution and use", "THIS SOFTWARE IS PROVIDED"),
    "BSD-3-Clause": ("Redistribution and use", "Neither the name"),
    "BSD-3-Clause-Clear": ("The Clear BSD License", "NO EXPRESS OR IMPLIED LICENSES"),
}
KINDS = {"robot_model", "simulation_scene", "robot_description", "semantic_description", "control_configuration", "robot_configuration", "workflow"}
BT_FORMAT = "behaviortree-cpp-xml"
BT_MAX_NODES, BT_MAX_DEPTH, BT_MAX_INVENTORY_BYTES = 512, 64, 32 * 1024


def digest(data):
    return hashlib.sha256(data).hexdigest()


def validate_pin(pin):
    safe_relative(pin["path"])
    if (not re.fullmatch(r"[a-f0-9]{64}", pin["sha256"]) or type(pin["bytes"]) is not int
            or not 0 < pin["bytes"] <= MAX_BYTES):
        raise ValueError("Supporting text needs an exact bounded checksum and size")


def support_pins(project):
    pins = list(project.get("evidence_files", []))
    for info in project["licenses"].values():
        if info.get("binding"):
            pins.extend([info["binding"]["package"], info["binding"]["terms"]])
    return pins


def validate_project(project):
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", project["id"]):
        raise ValueError("Invalid artifact project id")
    if not re.fullmatch(r"https://github.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", project["repository"]):
        raise ValueError("Only reviewed public GitHub repositories are supported")
    if not re.fullmatch(r"[a-f0-9]{40}", project["commit"]):
        raise ValueError("A full immutable commit is required")
    if not project.get("artifacts") or not project.get("licenses"):
        raise ValueError("Explicit artifact and license pins are required")
    for path, license_info in project["licenses"].items():
        safe_relative(path)
        if license_info["spdx"] not in LICENSE_MARKERS or not re.fullmatch(r"[a-f0-9]{64}", license_info["sha256"]):
            raise ValueError("A reviewed license identity and SHA-256 are required")
        if not license_info.get("scope"):
            raise ValueError("License scope is required")
        binding = license_info.get("binding")
        if binding is not None:
            if (not isinstance(binding, dict) or set(binding) != {"kind", "package", "package_name", "unmarked_file_quote", "terms"}
                    or binding["kind"] != "package_with_unmarked_file_fallback"
                    or not re.fullmatch(r"[a-z][a-z0-9_]*", binding["package_name"])
                    or PurePosixPath(binding["package"]["path"]).name != "package.xml"):
                raise ValueError("Unsupported package license binding")
            expected = f"For files that are not otherwise marked, they are provided under the {license_info['spdx']} license."
            if " ".join(binding["unmarked_file_quote"].split()) != expected:
                raise ValueError("An explicit matching otherwise-unmarked license rule is required")
            validate_pin({"path": path, "sha256": license_info["sha256"], "bytes": license_info["bytes"]})
    if not isinstance(project.get("evidence_files", []), list) or len(project.get("evidence_files", [])) > 20:
        raise ValueError("Supporting evidence must be finite")
    seen_support = {}
    for pin in support_pins(project):
        validate_pin(pin)
        if pin["path"] in seen_support and (pin["sha256"], pin["bytes"]) != seen_support[pin["path"]]:
            raise ValueError("Conflicting supporting file identity")
        seen_support[pin["path"]] = (pin["sha256"], pin["bytes"])
    paths = []
    for artifact in project["artifacts"]:
        safe_relative(artifact["path"])
        if artifact.get("setup_path"):
            safe_relative(artifact["setup_path"])
        paths.append(artifact["path"])
        if artifact["license_path"] not in project["licenses"]:
            raise ValueError("Artifact has no applicable reviewed license")
        if (artifact["kind"] not in KINDS or not re.fullmatch(r"[a-f0-9]{64}", artifact["sha256"])
                or type(artifact["bytes"]) is not int or not 0 < artifact["bytes"] <= MAX_BYTES):
            raise ValueError("Invalid artifact kind, checksum or byte size")
        if artifact["kind"] == "workflow" or artifact["format"] == BT_FORMAT:
            if artifact["kind"] != "workflow" or artifact["format"] != BT_FORMAT or not artifact["path"].endswith(".xml"):
                raise ValueError("Workflow kind requires the reviewed behavior-tree XML format")
            if any(not isinstance(artifact.get(key), str) or not 0 < len(artifact[key]) <= limit for key, limit in (("name", 150), ("summary", 1000))):
                raise ValueError("A reviewed workflow name and source-only summary are required")
    if len(paths) != len(set(paths)):
        raise ValueError("Duplicate artifact path in project manifest")


def source_bytes(cache, project, path, fetch=False):
    target = cache_path(cache, project, path)
    if not fetch:
        with target.open("rb") as stream:
            data = stream.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError("Cached artifact exceeds static text byte budget")
        return data
    repo = project["repository"].removeprefix("https://github.com/")
    url = f"https://raw.githubusercontent.com/{repo}/{project['commit']}/{urllib.parse.quote(path, safe='/')}"
    req = urllib.request.Request(url, headers={"User-Agent": "robot-skill-hub-artifact-review/1", "DNT": "1", "X-RSH-Telemetry": "off"})
    with urllib.request.urlopen(req, timeout=40) as response:
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("Artifact exceeds static text byte budget")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return data


def inspect_artifact(path, data):
    """Inspect syntax/structure only; never evaluate includes or configuration."""
    if not data or len(data) > MAX_BYTES or b"\0" in data:
        raise ValueError("Artifact must be bounded UTF-8 text")
    text = data.decode("utf-8-sig")
    if path.endswith((".xml", ".urdf", ".srdf", ".xacro")):
        if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", text, re.I):
            raise ValueError("XML DTD/entity declarations are not accepted")
        root = ET.fromstring(text)
        if root.tag == "root":
            return inspect_behavior_tree(root)
        tag = root.tag.rsplit("}", 1)[-1]
        if tag not in ("robot", "mujoco", "mujocoinclude"):
            raise ValueError("Not a reviewed robot/model XML root")
        fmt = "xacro" if path.endswith(".xacro") else "mjcf" if tag.startswith("mujoco") else "srdf" if path.endswith(".srdf") else "urdf"
        references = sorted({value for node in root.iter() for key, value in node.attrib.items()
                             if key in ("file", "filename", "meshdir", "texturedir")})
        return {"format": fmt, "root": tag, "references": references[:40],
                "references_truncated": len(references) > 40,
                "inspection": "Parsed XML syntax and recorded direct file references; includes, Xacro expressions and model dynamics were not evaluated."}
    if path.endswith((".yaml", ".yml")):
        # Deliberately no YAML constructor/loader: ROS/Xacro configuration may
        # carry custom tags. This is a text-shape check, not parser validation.
        keys = sorted(set(re.findall(r"^\s*([A-Za-z_][A-Za-z0-9_./-]*)\s*:", text, re.M)))
        if not keys:
            raise ValueError("Configuration has no recognizable YAML mapping keys")
        return {"format": "yaml", "keys": keys[:40], "keys_truncated": len(keys) > 40,
                "inspection": "Inspected UTF-8 configuration text and mapping-key shape; YAML semantics and ROS parameter compatibility were not evaluated."}
    raise ValueError("Only reviewed XML, URDF, SRDF, Xacro and YAML text artifacts are supported")


def inspect_behavior_tree(root):
    """Inventory one bounded literal BTCPP4 tree; no node/port/runtime validation."""
    name = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,79}")
    main = root.get("main_tree_to_execute", "")
    trees = list(root)
    if (set(root.attrib) != {"BTCPP_format", "main_tree_to_execute"} or root.get("BTCPP_format") != "4"
            or not name.fullmatch(main) or len(trees) != 1 or trees[0].tag != "BehaviorTree"
            or trees[0].attrib != {"ID": main} or len(trees[0]) != 1):
        raise ValueError("Unsupported behavior-tree root/version/main tree/body structure")
    nodes, references = [], set()
    stack = [(trees[0][0], 1)]
    while stack:
        node, depth = stack.pop()
        if (not name.fullmatch(node.tag) or node.tag.lower() in {"root", "behaviortree", "include", "subtree", "subtreeplus", "treenodesmodel"}
                or depth > BT_MAX_DEPTH or len(nodes) >= BT_MAX_NODES or len(node.attrib) > 32
                or any(not name.fullmatch(key) or len(value) > 4096 for key, value in node.attrib.items())
                or (node.text and node.text.strip()) or (node.tail and node.tail.strip())):
            raise ValueError("Unsupported behavior-tree node/namespace/include/subtree or graph bound")
        nodes.append({"tag": node.tag, "attributes": dict(node.attrib), "children": len(node)})
        references.update(token for value in node.attrib.values() for token in re.findall(r"\{[^{}]+\}", value))
        stack.extend((child, depth + 1) for child in reversed(list(node)))
    if (root.text and root.text.strip()) or (trees[0].text and trees[0].text.strip()) or (trees[0].tail and trees[0].tail.strip()):
        raise ValueError("Unsupported behavior-tree text content")
    result = {"format": BT_FORMAT, "root": "root", "BTCPP_format": "4", "main_tree": main,
              "nodes": nodes, "node_count": len(nodes), "blackboard_references": sorted(references),
              "inspection": "Inventoried one bounded BTCPP4 XML tree and parsed literal attributes. Node availability, ports, blackboard expressions, timing and runtime behavior were not evaluated."}
    if len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > BT_MAX_INVENTORY_BYTES:
        raise ValueError("Behavior-tree inventory exceeds its byte budget")
    return result


def checked_pin(project, cache, pin):
    data = source_bytes(cache, project, pin["path"])
    if len(data) != pin["bytes"] or digest(data) != pin["sha256"]:
        raise ValueError("Supporting file checksum/size mismatch: " + pin["path"])
    text = data.decode("utf-8-sig")
    if "\0" in text or any(quote not in text for quote in pin.get("quotes", [])):
        raise ValueError("Supporting text/anchor differs: " + pin["path"])
    return text


def checked_licenses(project, cache):
    for path, info in project["licenses"].items():
        data = source_bytes(cache, project, path)
        text = data.decode("utf-8-sig")
        binding = info.get("binding")
        terms = text
        if binding:
            if len(data) != info["bytes"] or binding["unmarked_file_quote"] not in text:
                raise ValueError("Package fallback license index/quote differs")
            package_text = checked_pin(project, cache, binding["package"])
            if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", package_text, re.I):
                raise ValueError("Package XML DTD/entity is unsupported")
            package = ET.fromstring(package_text)
            if (package.tag != "package" or [n.text for n in package.findall("name")] != [binding["package_name"]]
                    or [n.text for n in package.findall("license")] != [info["spdx"]]):
                raise ValueError("Selected package name/license declaration differs")
            terms = checked_pin(project, cache, binding["terms"])
        if digest(data) != info["sha256"] or not all(marker in terms for marker in LICENSE_MARKERS[info["spdx"]]):
            raise ValueError(f"{project['id']}:{path}: license checksum or reviewed text mismatch")
        if info["spdx"] == "BSD-2-Clause" and re.search(r"Neither the name", terms, re.I):
            raise ValueError("Three-clause BSD notice cannot be labeled BSD-2-Clause")
        if info["spdx"] == "BSD-3-Clause" and "The Clear BSD License" in terms:
            raise ValueError("Clear BSD notice requires its own license identity")


def make_record(project, artifact, cache):
    path = artifact["path"]
    data = source_bytes(cache, project, path)
    if digest(data) != artifact["sha256"] or len(data) != artifact["bytes"]:
        raise ValueError(f"{project['id']}:{path}: immutable artifact checksum/size mismatch")
    inspection = inspect_artifact(path, data)
    if inspection["format"] != artifact["format"]:
        raise ValueError("Artifact format changed from reviewed manifest")
    license_info = project["licenses"][artifact["license_path"]]
    binding = license_info.get("binding")
    if binding:
        directory = str(PurePosixPath(binding["package"]["path"]).parent)
        if directory != "." and not path.startswith(directory + "/"):
            raise ValueError("Selected artifact escapes the bound package")
        # This opt-in rule covers otherwise-unmarked files only. Marked files
        # require their own explicit review, even when their declaration agrees.
        if re.search(r"\b(?:SPDX-License-Identifier|copyright|licen[cs](?:e|ed|ing))\b", data.decode("utf-8-sig"), re.I):
            raise ValueError("Package fallback requires an unmarked file; review its per-file notice")
    explicit = re.findall(r"SPDX-License-Identifier:\s*([^\r\n<>]+)", data.decode("utf-8-sig")[:6000])
    if any(value.strip().rstrip("*/ -") != license_info["spdx"] for value in explicit):
        raise ValueError("Conflicting explicit per-file license requires review")
    suffix = re.sub(r"[^a-z0-9]+", "-", path.lower()).strip("-")
    ident = project["id"] + "-artifact-" + suffix
    if len(ident) > 80:
        ident = ident[:67].rstrip("-") + "-" + digest(path.encode())[:12]
    title = path.removesuffix(".xacro").replace("_", " ")
    source = f"{project['repository']}/blob/{project['commit']}/{path}"
    robot_types = artifact.get("robot_types", project["robot_types"])
    record = {
        "id": ident, "name": f"{project['name']}: {title}",
        "summary": f"Official pinned {artifact['kind'].replace('_', ' ')} text for {title}. Inspect the upstream package and adjacent assets before use.",
        "framework": project["id"], "kind": "official_example", "source_registry": REGISTRY,
        "artifact": {"kind": artifact["kind"], "format": inspection["format"],
                     "role": "Source/configuration reference; not an executable Hub skill", "structure": {k:v for k,v in inspection.items() if k not in ("format", "inspection")}},
        "capabilities": sorted(set(project["capabilities"] + artifact.get("capabilities", []) + [artifact["kind"].replace("_", "-")])),
        "robot_types": robot_types,
        "robot_scope": "Labels identify this description/configuration source; they do not establish runtime, controller or physical-robot compatibility.",
        "source": {"repository": project["repository"], "commit": project["commit"], "tag": project["ref"], "path": path,
                   "url": source, "raw_url": project["repository"].replace("https://github.com/", "https://raw.githubusercontent.com/") + "/" + project["commit"] + "/" + urllib.parse.quote(path, safe="/"),
                   "sha256": artifact["sha256"], "bytes": artifact["bytes"]},
        "license": {"spdx": license_info["spdx"], "url": f"{project['repository']}/blob/{project['commit']}/{artifact['license_path']}",
                    "sha256": license_info["sha256"], "scope": license_info["scope"]},
        "access": {"mode": "source_reference", "hub_prepare": False,
                   "instructions": "Inspect this checksum-pinned text in the full upstream checkout. Resolve adjacent definitions/assets and their separate licenses using upstream instructions. The Hub does not load or execute this artifact.",
                   "setup_url": (f"{project['repository']}/blob/{project['commit']}/{artifact['setup_path']}"
                                 if artifact.get("setup_path") else project["setup_url"])},
        "requirements": {"python": "Not a Python entrypoint; follow the pinned upstream package requirements", "packages": project["packages"],
                         "display": project["environment"], "execution_domain": project["execution_domain"], "source_imports": []},
        "invocation": {"entrypoint": f"Data/configuration artifact: {path}; use its upstream loader or package integration after inspection",
                       "notes": "This file is not a standalone program. No Xacro expansion, include resolution, model loading, configuration deployment or robot execution was performed."},
        "popularity": {"metric": "github_stars", "repository_stars": project["stars"], "checked_at": project["checked_at"],
                       "meaning": "Dated repository interest, not artifact use or runtime success."},
        "evidence": {"level": "source_reviewed", "runtime_verification": "not_run", "checked_at": project["checked_at"],
                     "inspection": "Verified exact source and applicable license SHA-256 bytes. " + inspection["inspection"],
                     "inspection_method": "automated_static", "artifact_kind": artifact["kind"]},
    }
    if artifact.get("robots"):
        record["robots"] = artifact["robots"]
    if binding:
        def declaration(pin):
            return {"path": pin["path"], "url": f"{project['repository']}/blob/{project['commit']}/{pin['path']}",
                    "sha256": pin["sha256"], "bytes": pin["bytes"]}
        record["license"]["binding"] = {"kind": binding["kind"], "package": {**declaration(binding["package"]), "name": binding["package_name"], "declared_spdx": license_info["spdx"]},
                                         "unmarked_file_quote": binding["unmarked_file_quote"], "terms": {**declaration(binding["terms"]), "scope": "Complete standard terms text only; the selected package and root index supply the source-license binding."}}
    if inspection["format"] == BT_FORMAT:
        record["name"], record["summary"] = artifact["name"], artifact["summary"]
        record["requirements"]["python"] = None
        record["artifact"]["role"] = "Declarative upstream workflow source; not an executable Hub skill"
        record["invocation"]["notes"] = "A complete configured upstream BT host loads this XML. Its action/service node implementations can command hardware; fetching this inert file does not load a host, validate ports or establish task success, timing, stopping or robot compatibility."
        if artifact.get("notes"):
            record["invocation"]["notes"] += " " + artifact["notes"]
        record["evidence"]["setup_evidence"] = [{"path": pin["path"], "sha256": pin["sha256"], "bytes": pin["bytes"], "url": f"{project['repository']}/blob/{project['commit']}/{pin['path']}"} for pin in project.get("evidence_files", [])]
    return record


def merge_records(existing, generated):
    combined = [r for r in existing if r.get("source_registry") != REGISTRY] + generated
    ids = [r["id"] for r in combined]
    pins = [(r["source"]["repository"], r["source"]["commit"], r["source"]["path"]) for r in combined]
    if len(ids) != len(set(ids)) or len(pins) != len(set(pins)):
        raise ValueError("Duplicate reference id or immutable artifact; resolve ownership explicitly")
    return sorted(combined, key=lambda r: (r["framework"], r["id"]))


def build(manifest, cache, existing, fetch=False):
    projects = manifest.get("projects", [])
    if (manifest.get("schema_version") != "1" or not projects
            or len({p["id"] for p in projects}) != len(projects)):
        raise ValueError("A nonempty versioned manifest with unique projects is required")
    generated = []
    for project in projects:
        validate_project(project)
        if fetch:
            paths = sorted(set(project["licenses"]) | {a["path"] for a in project["artifacts"]} | {pin["path"] for pin in support_pins(project)})
            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(lambda path: source_bytes(cache, project, path, True), paths))
        checked_licenses(project, cache)
        for pin in project.get("evidence_files", []):
            checked_pin(project, cache, pin)
        generated.extend(make_record(project, artifact, cache) for artifact in project["artifacts"])
    return {**existing, "checked_at": max([existing.get("checked_at", "")] + [p["checked_at"] for p in manifest["projects"]]),
            "artifact_manifest": "artifact-projects.json", "records": merge_records(existing["records"], generated)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / "catalog/artifact-projects.json")
    parser.add_argument("--cache", type=Path, default=ROOT / ".local/artifact-review")
    parser.add_argument("--output", type=Path, default=ROOT / "catalog/references.json")
    parser.add_argument("--fetch", action="store_true", help="Fetch only existing immutable source/license pins, without executing or resolving them")
    parser.add_argument("--check", action="store_true", help="Rebuild in memory and reject canonical or index drift")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    existing = json.loads(args.output.read_text(encoding="utf-8"))
    output = build(manifest, args.cache, existing, args.fetch)
    if args.check:
        if output != existing:
            raise ValueError("Artifact catalog differs from its reviewed manifest")
        check_source_index(output["records"], args.output.parent / "source-index.json")
    else:
        args.output.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        write_source_index(output["records"], args.output.parent / "source-index.json")
    print(json.dumps({"artifact_references":sum(len(p["artifacts"]) for p in manifest["projects"]), "projects":len(manifest["projects"]),
                      "all_official_references":len(output["records"]), "upstream_code_executed":False}))


if __name__ == "__main__":
    main()
