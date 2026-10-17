"""Verify a finite set of official robot workflow entrypoints, without running them.

The reviewed manifest names every file at a full Git commit. Normal rebuilds
read the local source cache only; --fetch explicitly retrieves those frozen text
pins. Source modules, setup files, robot drivers, models and commands are never
imported or executed. This registry supplements the existing example registries.
"""
from __future__ import annotations

import argparse
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
         "controller-input"}


def validate_pin(pin):
    examples.safe_relative(pin["path"])
    if (not re.fullmatch(r"[a-f0-9]{64}", pin["sha256"])
            or type(pin["bytes"]) is not int or not 0 < pin["bytes"] <= examples.MAX_SOURCE_BYTES):
        raise ValueError("Every source, license and supporting document needs an exact checksum and byte size")


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
        if artifact.get("entrypoint_kind") != "python_main" or not examples.selected(project, artifact["path"]):
            raise ValueError("Only explicitly selected guarded Python workflow entrypoints are supported")
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


def make_record(project, artifact, cache):
    data = checked_pin(cache, project, artifact)
    inspection = examples.inspect_source(artifact["path"], data)
    if inspection["kind"] != "python_main" or not examples.compatible_file_license(project, data.decode("utf-8-sig")):
        raise ValueError("Workflow entrypoint or applicable per-file license differs from its reviewed manifest")
    record = examples.make_record(project, artifact, cache)
    record.update(name=f"{project['name']}: {artifact['name']}", summary=artifact["summary"],
                  source_registry=REGISTRY, capabilities=sorted(set(artifact["capabilities"])),
                  robot_types=artifact["robot_types"], robot_scope=artifact["robot_scope"],
                  artifact={"kind": "workflow", "format": "python", "workflow_role": artifact["role"]})
    record["source"]["authors"] = project["authors"]
    record["license"]["bytes"] = project["license"]["bytes"]
    record["access"]["setup_evidence"] = [
        {"path": pin["path"], "url": file_url(project, pin["path"]), "sha256": pin["sha256"],
         "bytes": pin["bytes"], "purpose": pin["purpose"]} for pin in project["evidence_files"]]
    if artifact.get("entrypoint"):
        record["invocation"]["entrypoint"] = artifact["entrypoint"]
    record["invocation"]["notes"] = artifact.get("invocation_notes", project["invocation_notes"])
    record["requirements"]["execution_domain"] = artifact.get("execution_domain", project["execution_domain"])
    record["evidence"]["inspection"] = (
        "Verified exact source, applicable license and author/setup document bytes at a full Git commit; "
        "parsed the Python AST and reviewed this guarded operational entrypoint and its explicit license notices. "
        "No upstream code, installation, robot command, dataset, mesh or checkpoint was executed or loaded.")
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
