"""Index immutable official robot examples without importing or executing them.

The reviewed project manifest is the authority for upstream revisions, selection
roots, license checksums and source checksums. A normal build is offline. Fetch
only verifies those existing pins; --discover explicitly reviews the source tree
at a manifest's exact commit and updates its artifact list. No models, packages,
credentials, shell scripts or source modules are executed by this importer.
"""
from __future__ import annotations

import argparse
import ast
from concurrent.futures import ThreadPoolExecutor
from datetime import date
import fnmatch
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import urllib.parse
import urllib.request

from reference_index import check_source_index, write_source_index

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = "ecosystem-examples-v1"
MAX_SOURCE_BYTES = 4 * 1024 * 1024
SPDX_MARKERS = {"Apache-2.0": "Apache License", "MIT": "Permission is hereby granted",
                "BSD-2-Clause": "Redistribution and use", "BSD-3-Clause": "Redistribution and use",
                "GPL-2.0-only": "GNU GENERAL PUBLIC LICENSE", "GPL-2.0-or-later": "GNU GENERAL PUBLIC LICENSE"}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def reviewed_source_terms(license_info):
    """A local LicenseRef identifies pinned nonstandard terms, never a grant."""
    spdx = license_info["spdx"]
    terms = license_info.get("source_terms")
    if not isinstance(spdx, str):
        raise ValueError("License identity must be explicit text")
    if spdx in SPDX_MARKERS:
        if terms is not None:
            raise ValueError("Nonstandard source terms require an explicit local LicenseRef")
        return None
    if (not re.fullmatch(r"LicenseRef-[A-Za-z0-9][A-Za-z0-9.-]{0,119}", spdx)
            or license_info.get("verified") is not False
            or license_info.get("review_status") != "nonstandard_upstream_terms"
            or not isinstance(terms, dict) or set(terms) != {"identifier", "marker", "notes"}
            or not isinstance(terms.get("identifier"), str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}", terms["identifier"])
            or not isinstance(terms.get("marker"), str) or not terms["marker"].strip() or len(terms["marker"]) > 240
            or any(ord(char) < 32 for char in terms["marker"])
            or not isinstance(terms.get("notes"), str) or not terms["notes"].strip() or len(terms["notes"]) > 2000
            or license_info.get("package_declaration") is not None):
        raise ValueError("Nonstandard licenses need reviewed unverified source-only LicenseRef identity and terms")
    return terms


def source_license_record(project):
    info = project["license"]
    record = {"spdx": info["spdx"], "url": f"{project['repository']}/blob/{project['commit']}/{info['path']}",
              "sha256": info["sha256"], "scope": info["scope"]}
    terms = reviewed_source_terms(info)
    if terms:
        record.update(verified=False, review_status="nonstandard_upstream_terms", source_terms=dict(terms))
    return record


def safe_relative(value):
    path = PurePosixPath(value)
    if (not value or path.is_absolute() or "\\" in value or ":" in value or any(ord(c) < 32 for c in value)
            or any(p in ("", ".", "..") for p in value.split("/"))):
        raise ValueError(f"Unsafe source path: {value!r}")
    return path


def validate_project(project):
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", project["id"]):
        raise ValueError("Project id must be a stable lowercase identifier")
    if not re.fullmatch(r"https://github.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", project["repository"]):
        raise ValueError("Only explicitly reviewed public GitHub repositories are supported")
    if not re.fullmatch(r"[a-f0-9]{40}", project["commit"]):
        raise ValueError("A full immutable commit is required; branches and tags are labels only")
    safe_relative(project["license"]["path"])
    if not re.fullmatch(r"[a-f0-9]{64}", project["license"]["sha256"]):
        raise ValueError("A reviewed license checksum is required")
    reviewed_source_terms(project["license"])
    if not project.get("selection", {}).get("include"):
        raise ValueError("Explicit source selection roots are required")


def cache_path(cache, project, path):
    relative = safe_relative(path)
    def resolved(value):
        result = str(value.resolve())
        # Python 3.10 on Windows can return an extended-length prefix for a
        # concurrently created child while returning an ordinary parent path.
        # Normalize the equivalent spelling before checking containment.
        if os.name == "nt":
            if result.startswith("\\\\?\\UNC\\"):
                result = "\\\\" + result[8:]
            elif result.startswith("\\\\?\\"):
                result = result[4:]
        return Path(result)
    base = resolved(cache / project["id"] / project["commit"])
    target = base.joinpath(*relative.parts)
    if not resolved(target).is_relative_to(base):
        raise ValueError(f"Source cache symlink escapes its pinned project directory: {path}")
    return target


def download(url):
    req = urllib.request.Request(url, headers={"User-Agent": "robot-skill-hub-source-index/1",
                                              "Accept": "application/json" if "api.github.com" in url else "*/*"})
    with urllib.request.urlopen(req, timeout=40) as response:
        data = response.read(MAX_SOURCE_BYTES + 1)
    if len(data) > MAX_SOURCE_BYTES:
        raise ValueError("Source exceeds the static inspection size limit")
    return data


def source_bytes(cache, project, path, fetch=False):
    target = cache_path(cache, project, path)
    if fetch:
        repo = project["repository"].removeprefix("https://github.com/")
        encoded = urllib.parse.quote(path, safe="/")
        data = download(f"https://raw.githubusercontent.com/{repo}/{project['commit']}/{encoded}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return data
    with target.open("rb") as stream:
        data = stream.read(MAX_SOURCE_BYTES + 1)
    if len(data) > MAX_SOURCE_BYTES:
        raise ValueError("Source exceeds the static inspection size limit")
    return data


def robot_discovery_pins(artifact):
    """Validate declared evidence before fetching its fixed source paths."""
    discovery = artifact.get("robot_discovery")
    if discovery is None:
        return []
    if not isinstance(discovery, dict):
        raise ValueError("Robot discovery must be a reviewed declaration")
    labels, scope, pins = discovery.get("labels"), discovery.get("scope"), discovery.get("evidence")
    if (not isinstance(labels, list) or not 0 < len(labels) <= 50
            or any(not isinstance(label, str) or len(label) > 120
                   or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", label) for label in labels)
            or len(labels) != len(set(labels)) or not isinstance(scope, str) or not 0 < len(scope) <= 1000
            or not isinstance(pins, list) or not 0 < len(pins) <= 20):
        raise ValueError("Robot discovery needs bounded names, scope and pinned evidence")
    covered = set()
    for pin in pins:
        if not isinstance(pin, dict):
            raise ValueError("Robot discovery evidence must be a pinned source")
        if not isinstance(pin.get("path"), str):
            raise ValueError("Robot discovery evidence needs a source path")
        safe_relative(pin["path"])
        quote, supported = pin.get("quote"), pin.get("labels")
        if (not re.fullmatch(r"[a-f0-9]{64}", str(pin.get("sha256", "")))
                or type(pin.get("bytes")) is not int or not 0 < pin["bytes"] <= MAX_SOURCE_BYTES
                or not isinstance(quote, str) or not 0 < len(quote) <= 1000
                or not isinstance(supported, list) or not supported
                or any(not isinstance(label, str) or label not in labels for label in supported)):
            raise ValueError("Robot discovery evidence needs exact bytes and a named quote")
        match_in = pin.get("match_in", "text")
        if match_in not in ("text", "source_path") or match_in == "source_path" and pin["path"] != artifact["path"]:
            raise ValueError("Path discovery evidence must be the selected source itself")
        normalized = re.sub(r"[^a-z0-9]+", " ", quote.casefold())
        for label in supported:
            if not re.search(r"\b" + r"\s+".join(map(re.escape, label.split("-"))) + r"\b", normalized):
                raise ValueError("Robot discovery quote does not name the complete robot label")
        covered.update(supported)
    if covered != set(labels):
        raise ValueError("Every robot discovery label needs a pinned declaration")
    return pins


def reviewed_robot_discovery(project, artifact, cache):
    """Preserve explicitly reviewed names as discovery data, never compatibility."""
    pins = robot_discovery_pins(artifact)
    if not pins:
        return None
    discovery = artifact["robot_discovery"]
    evidence = []
    for pin in pins:
        data = source_bytes(cache, project, pin["path"])
        if len(data) != pin["bytes"] or digest(data) != pin["sha256"]:
            raise ValueError("Robot discovery evidence checksum/size differs")
        match_in = pin.get("match_in", "text")
        text = pin["path"] if match_in == "source_path" else data.decode("utf-8-sig")
        if pin["quote"] not in text:
            raise ValueError("Robot discovery quote is absent from its pinned source")
        evidence.append({"url": f"{project['repository']}/blob/{project['commit']}/{urllib.parse.quote(pin['path'], safe='/')}",
                         "sha256": pin["sha256"], "bytes": pin["bytes"], "quote": pin["quote"],
                         "labels": pin["labels"], "match_in": match_in})
    return {"labels": discovery["labels"], "scope": discovery["scope"], "method": "reviewed_pinned_text_declaration",
            "compatibility_inferred": False, "evidence": evidence}


def inspect_source(path, data):
    """Require a real static entrypoint, not a library, helper or configuration."""
    text = data.decode("utf-8-sig")
    if path.endswith(".py"):
        tree = ast.parse(text, filename=path)
        imports = sorted({n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
                         | {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names})
        functions = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        guarded = any(isinstance(n, ast.If) and isinstance(n.test, ast.Compare)
                      and any(isinstance(v, ast.Name) and v.id == "__name__" for v in ast.walk(n.test))
                      and any(isinstance(v, ast.Constant) and v.value == "__main__" for v in ast.walk(n.test))
                      for n in tree.body)
        if "generate_launch_description" in functions and ("launch" in imports or any(x.startswith("launch.") for x in imports)):
            return {"kind": "ros2_launch", "imports": imports}
        if guarded:
            return {"kind": "python_main", "imports": imports}
        # Several canonical Pinocchio / Robotics Toolbox / Webots examples are
        # straight-line scripts. Require top-level operational calls AND a
        # relevant imported robotics library, not merely definitions/imports.
        robotics = ("pinocchio", "roboticstoolbox", "controller", "ompl", "pydrake", "lerobot", "pyrobosim", "isaaclab")
        operational = any(isinstance(n, (ast.Expr, ast.Assign, ast.AnnAssign, ast.For, ast.While, ast.With))
                          and any(isinstance(v, ast.Call) for v in ast.walk(n)) for n in tree.body)
        if operational and any(x.split(".")[0] in robotics for x in imports):
            return {"kind": "python_script", "imports": imports}
        raise ValueError("No supported runnable Python entrypoint")
    if path.endswith((".cpp", ".cc", ".c")):
        # Remove comments to avoid treating a commented example as an entrypoint.
        code = re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.S)
        if not re.search(r"\bint\s+main\s*\([^;]*\)\s*\{", code):
            raise ValueError("No native main entrypoint")
        return {"kind": "native_main", "imports": sorted(set(re.findall(r'^\s*#include\s+[<\"]([^>\"]+)', text, re.M)))}
    raise ValueError("Only reviewed Python, C and C++ entrypoints are selected")


def compatible_file_license(project, text):
    explicit = re.findall(r"SPDX-License-Identifier:\s*([^\r\n]+)", text[:6000])
    if explicit and any(x.strip().rstrip("*/ ") != project["license"]["spdx"] for x in explicit):
        return False
    if not project["license"]["spdx"].startswith("GPL-") and re.search(r"GNU General Public License", text[:6000], re.I):
        return False
    return True


def selected(project, path):
    config = project["selection"]
    name = PurePosixPath(path).name
    if name.startswith("_") or name == "setup.py" or name.startswith("test_"):
        return False
    if not path.endswith((".py", ".cpp", ".cc", ".c")):
        return False
    return (any(fnmatch.fnmatchcase(path, pattern) for pattern in config["include"])
            and not any(fnmatch.fnmatchcase(path, pattern) for pattern in config.get("exclude", [])))


def checked_license(project, cache, fetch=False):
    data = source_bytes(cache, project, project["license"]["path"], fetch)
    if digest(data) != project["license"]["sha256"]:
        raise ValueError(f"{project['id']}: license checksum changed; explicit review required")
    terms = reviewed_source_terms(project["license"])
    declaration = project["license"].get("package_declaration")
    if terms:
        text = data.decode("utf-8-sig")
        if terms["identifier"] not in text or terms["marker"] not in text:
            raise ValueError("Pinned nonstandard license identity or text marker is absent")
    elif declaration:
        package = source_bytes(cache, project, declaration["path"], fetch)
        if digest(package) != declaration["sha256"] or f"<license>{project['license']['spdx']}</license>" not in package.decode("utf-8-sig"):
            raise ValueError("Selected package license declaration did not match its reviewed pin")
        if project["license"]["spdx"] not in data.decode("utf-8-sig"):
            raise ValueError("Repository license notice does not include the selected package license")
    elif SPDX_MARKERS[project["license"]["spdx"]] not in data.decode("utf-8-sig"):
        raise ValueError(f"{project['id']}: expected license text missing")


def discover(project, cache):
    validate_project(project)
    checked_license(project, cache, True)
    repo = project["repository"].removeprefix("https://github.com/")
    tree = json.loads(download(f"https://api.github.com/repos/{repo}/git/trees/{project['commit']}?recursive=1"))
    if tree.get("truncated"):
        raise ValueError("Refusing incomplete upstream tree; narrow selection or implement tree pagination")
    paths = sorted(item["path"] for item in tree["tree"] if item["type"] == "blob" and selected(project, item["path"]))

    def inspect(path):
        data = source_bytes(cache, project, path, True)
        try:
            inspection = inspect_source(path, data)
        except (SyntaxError, ValueError) as error:
            return None, {"path": path, "reason": str(error).splitlines()[0]}
        if inspection["kind"] == "python_script" and not project["selection"].get("allow_straightline_scripts", False):
            return None, {"path": path, "reason": "No guarded entrypoint; straight-line scripts are not reviewed for this project"}
        if not compatible_file_license(project, data.decode("utf-8-sig")):
            return None, {"path": path, "reason": "Different per-file license requires a separate review policy"}
        return {"path": path, "sha256": digest(data), "bytes": len(data), "entrypoint_kind": inspection["kind"]}, None

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(inspect, paths))
    project["artifacts"] = [artifact for artifact, _ in results if artifact]
    project["selection_report"] = {"candidate_files": len(paths), "accepted_files": len(project["artifacts"]),
                                   "excluded_files": [excluded for _, excluded in results if excluded]}
    project["checked_at"] = date.today().isoformat()
    print(f"{project['id']}: statically indexed {len(project['artifacts'])}/{len(paths)} candidate entrypoints")


def topic(path):
    stem = PurePosixPath(path).stem.removesuffix(".launch")
    if stem in ("main", "demo", "simulate", "minimal", "client", "server", "rrbot"):
        stem = PurePosixPath(path).parent.parent.name + " " + stem
    stem = re.sub(r"([a-z])([A-Z])", r"\1 \2", stem)
    return re.sub(r"[_-]+", " ", stem).strip()


def capabilities(project, path):
    tags = set(project["capabilities"])
    lower = path.lower()
    words = {"inverse-kinematics": "inverse-kinematics", "inverse_kinematics": "inverse-kinematics", "kinematics": "kinematics", "navigation": "navigation", "nav_": "navigation",
             "grasp": "grasping", "gripper": "gripper", "allegro_hand": "dexterous-hand", "torque": "torque-control",
             "teleop": "teleoperation", "trajectory": "trajectory", "sensor": "sensing", "camera": "camera",
             "collision": "collision", "pick_and_place": "pick-and-place", "pick_place": "pick-and-place", "locomotion": "locomotion", "quadruped": "quadruped",
             "biped": "humanoid", "humanoid": "humanoid", "quadcopter": "aerial-robot", "multicopter": "aerial-robot",
             "dynamics": "dynamics", "train": "policy-training", "policy": "policy", "replay": "trajectory-playback",
             "contact": "contact", "pddl": "task-planning", "lidar": "lidar", "obstacle": "obstacle-avoidance"}
    for needle, tag in words.items():
        if needle in lower:
            tags.add(tag)
    if re.search(r"(?:^|[/_.-])ik(?:[/_.-]|$)|ikine", lower):
        tags.add("inverse-kinematics")
    return sorted(tags)


def robot_types(project, path):
    """Conservative discovery labels, never ecosystem-wide compatibility claims."""
    lower = path.lower()
    types = set()
    labels = {"arm": ("panda", "franka", "kuka", "iiwa", "jaco", "kinova", "so100", "so101", "scara", "puma", "rrbot", "r6bot", "manipulator", "/abb/", "/ur5", "/ur10", "/niryo/"),
              "wheeled": ("diffbot", "carlike", "turtlebot", "pioneer", "khepera", "e-puck", "vehicle", "two_wheels", "four_wheels", "line_follow", "lekiwi", "jetbot", "robotino", "mir100", "thymio", "boebot"),
              "legged": ("quadruped", "anymal", "spot", "solo", "salamander", "ghostdog", "bioloid_dog"),
              "humanoid": ("humanoid", "biped", "atlas", "cassie", "talos", "g1-", "h1_", "/nao", "hoap", "darwin", "op3_"),
              "aerial": ("quadcopter", "quadrotor", "multicopter", "crazyflie", "mavic", "blimp", "rotor"),
              "marine": ("heron", "usv"), "dexterous-hand": ("allegro", "/hands.", "hey5"),
              "mobile-manipulator": ("tiago", "youbot", "/pr2/", "fetch", "holistic_mm", "/mmc.")}
    for label, needles in labels.items():
        if any(needle in lower for needle in needles):
            types.add(label)
    if project["id"] == "crazyflie":
        types.add("aerial")
    if project["id"] == "nav2":
        types.add("mobile")
    return sorted(types) or ["source-defined"]


def invocation(project, path, kind):
    if project["id"] == "webots":
        return f"Webots controller: {path}; open the matching upstream .wbt world and select this controller"
    if kind == "ros2_launch":
        package = project.get("ros_package")
        if project["id"] == "ros2-control":
            package = "ros2_control_demo_" + path.split("/", 1)[0]
        if package:
            return f"ros2 launch {package} {PurePosixPath(path).name}"
    if project["id"] == "isaaclab":
        return f"./isaaclab.sh -p {path}"
    if kind.startswith("python_"):
        return f"python {path}"
    return f"Native main: {path}; build the target declared by the pinned upstream build files"


def make_record(project, artifact, cache):
    path = artifact["path"]
    data = source_bytes(cache, project, path)
    if digest(data) != artifact["sha256"] or len(data) != artifact["bytes"]:
        raise ValueError(f"{project['id']}:{path}: immutable source checksum/size mismatch")
    inspection = inspect_source(path, data)
    if inspection["kind"] != artifact["entrypoint_kind"] or not compatible_file_license(project, data.decode("utf-8-sig")):
        raise ValueError("Static entrypoint or per-file license evidence changed")
    if inspection["kind"] == "python_script" and not project["selection"].get("allow_straightline_scripts", False):
        raise ValueError("Straight-line entrypoint has not been reviewed for this project")
    # Include path and extension to prevent collisions among same-name demos.
    suffix = re.sub(r"[^a-z0-9]+", "-", path.lower()).strip("-")
    ident = project["id"] + "-" + suffix
    if len(ident) > 80:
        ident = ident[:67].rstrip("-") + "-" + digest(path.encode())[:12]
    source_url = f"{project['repository']}/blob/{project['commit']}/{path}"
    raw_url = project["repository"].replace("https://github.com/", "https://raw.githubusercontent.com/") + "/" + project["commit"] + "/" + urllib.parse.quote(path, safe="/")
    record = {"id": ident, "name": f"{project['name']}: {topic(path)}", "summary": f"Official {project['name']} {inspection['kind'].replace('_', ' ')} example for {topic(path)}. Inspect the pinned source and upstream setup before use.",
            "framework": project["id"], "kind": "official_example", "source_registry": REGISTRY,
            "capabilities": capabilities(project, path), "robot_types": robot_types(project, path),
            "robot_scope": "Discovery labels inferred from this source path; inspect its robot configuration for compatibility. Project-wide categories are not a supported-robot list.",
            "source": {"repository": project["repository"], "commit": project["commit"], "tag": project["ref"],
                       "path": path, "url": source_url, "raw_url": raw_url, "sha256": artifact["sha256"], "bytes": artifact["bytes"]},
            "license": source_license_record(project),
            "access": {"mode": "source_reference", "hub_prepare": False, "instructions": "Fetch the pinned repository, verify this source checksum, and use upstream installation and invocation. This record does not install or execute code.", "setup_url": project["setup_url"]},
            "requirements": {"python": project["requirements"]["python"], "packages": project["requirements"]["packages"],
                             "display": project["requirements"]["environment"], "execution_domain": project["execution_domain"], "source_imports": inspection["imports"]},
            "invocation": {"entrypoint": invocation(project, path, inspection["kind"]), "notes": project["invocation_notes"]},
            "popularity": {"metric": "github_stars", "repository_stars": project["stars"], "checked_at": project["checked_at"], "meaning": "Dated repository interest, not robot-skill usage, compatibility or runtime success."},
            "evidence": {"level": "source_reviewed", "runtime_verification": "not_run", "checked_at": project["checked_at"],
                         "inspection": "Fetched and SHA-256 checked this immutable source; statically parsed Python or located native main; verified pinned license bytes and checked explicit per-file license identifiers. No upstream code executed.",
                         "entrypoint_kind": inspection["kind"], "inspection_method": "automated_static"}}
    terms = reviewed_source_terms(project["license"])
    if terms:
        record["access"]["instructions"] = "Inspect the pinned source, nonstandard upstream terms and setup requirements. The Hub supplies a source link, not license clearance, installation or execution."
    discovery = reviewed_robot_discovery(project, artifact, cache)
    if discovery:
        record["robots"] = discovery.pop("labels")
        record["evidence"]["robot_discovery"] = discovery
    return record


def merge_records(existing, generated):
    retained = [r for r in existing if r.get("source_registry") != REGISTRY]
    combined = retained + generated
    ids = [r["id"] for r in combined]
    pins = [(r["source"]["repository"], r["source"]["commit"], r["source"]["path"]) for r in combined]
    if len(ids) != len(set(ids)) or len(pins) != len(set(pins)):
        raise ValueError("Duplicate example id or immutable source artifact; resolve ownership explicitly")
    return sorted(combined, key=lambda r: (r["framework"], r["id"]))


def build(manifest, cache, existing, fetch=False):
    generated = []
    for project in manifest["projects"]:
        validate_project(project)
        artifacts = project.get("artifacts", [])
        if not artifacts:
            raise ValueError(f"{project['id']}: discover and review entrypoints before building")
        paths = {artifact["path"] for artifact in artifacts}
        for artifact in artifacts:
            paths.update(pin["path"] for pin in robot_discovery_pins(artifact))
        checked_license(project, cache, fetch)
        if fetch:
            # License/package declaration bytes were already fetched and checked.
            paths.discard(project["license"]["path"])
            declaration = project["license"].get("package_declaration")
            if declaration:
                paths.discard(declaration["path"])
            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(lambda path: source_bytes(cache, project, path, True), sorted(paths)))
        generated.extend(make_record(project, artifact, cache) for artifact in artifacts)
    records = merge_records(existing["records"], generated)
    return {**existing, "checked_at": max(p["checked_at"] for p in manifest["projects"]),
            "description": "Immutable robot code, artifacts, workflows and agent-instruction source references. Hub preparation adapters are indexed separately.",
            "selection": "Explicit frozen repository/file manifests with artifact-specific static source, identity and license review. Coverage is finite; these manifests do not establish an exhaustive inventory of Internet robot skills or runtime compatibility.",
            "source_manifest": "source-projects.json", "records": records}


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / "catalog/source-projects.json")
    parser.add_argument("--cache", type=Path, default=ROOT / ".local/ecosystem-review")
    parser.add_argument("--output", type=Path, default=ROOT / "catalog/references.json")
    parser.add_argument("--fetch", action="store_true", help="Verify existing immutable pins from upstream; no discovery or execution")
    parser.add_argument("--discover", action="store_true", help="Explicitly discover/inspect runnable artifacts at the manifest's pinned commits and update its artifact list")
    parser.add_argument("--project", action="append", default=[], help="Limit discovery to named manifest projects (the build still validates all projects)")
    parser.add_argument("--check", action="store_true", help="Validate/rebuild in memory and reject catalog drift; do not write the index")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if args.discover:
        ids = {p["id"] for p in manifest["projects"]}
        if set(args.project) - ids:
            parser.error("Unknown project id")
        for project in manifest["projects"]:
            if not args.project or project["id"] in args.project:
                discover(project, args.cache)
                # Keep completed project inspections if a later network fetch
                # fails. A normal build still refuses any unreviewed project.
                write_json(args.manifest, manifest)
    existing = json.loads(args.output.read_text(encoding="utf-8"))
    output = build(manifest, args.cache, existing, args.fetch)
    if args.check:
        if output != existing:
            raise ValueError("Catalog differs from its reviewed source manifest")
        check_source_index(output["records"], args.output.parent / "source-index.json")
    else:
        write_json(args.output, output)
        write_source_index(output["records"], args.output.parent / "source-index.json")
    print(f"Validated {len(output['records'])} immutable examples; {len(manifest['projects'])} managed project manifests; no upstream code executed")


if __name__ == "__main__":
    main()
