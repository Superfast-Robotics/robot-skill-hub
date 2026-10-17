"""Pin upstream robot-agent instruction bundles as data-only source references.

Only bounded text is read. Frontmatter is inspected, never evaluated or adopted
as instructions. Normal publication uses canonical JSON without fetching sources.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import urllib.request

from import_ecosystem_examples import safe_relative
from reference_index import check_source_index, write_source_index

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = "robot-agent-instruction-sources-v1"
MAX_BYTES = 256 * 1024
SHA = re.compile(r"[a-f0-9]{64}")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def instruction_frontmatter(data):
    if not data or len(data) > MAX_BYTES or b"\0" in data:
        raise ValueError("Instruction source must be bounded text")
    text = data.decode("utf-8-sig")
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        raise ValueError("Instruction source needs bounded frontmatter")
    return text[4:].split("\n---\n", 1)[0]


def inspect_instruction(data):
    frontmatter = instruction_frontmatter(data)
    name = re.search(r"^name:\s*([a-z0-9]+(?:-[a-z0-9]+)*)\s*$", frontmatter, re.M)
    if not name or not re.search(r"^description:\s*\S", frontmatter, re.M):
        raise ValueError("Instruction source lacks a scalar name/description")
    declared = re.search(r"^license:\s*([A-Za-z0-9.-]+)\s*$", frontmatter, re.M)
    if re.search(r"^license:", frontmatter, re.M) and not declared:
        raise ValueError("Unsupported license declaration; inspect it explicitly")
    tags = re.search(r"\btags:\s*\[([^\]]*)\]", frontmatter)
    environment = set()
    for block in re.findall(r"\benv(?:_any)?:\s*\[([^\]]*)\]", frontmatter, re.S):
        environment.update(re.findall(r"\b[A-Z][A-Z0-9_]{1,79}\b", block))
    return {"name": name[1], "declared_license": declared[1] if declared else None,
            "tags": sorted(set(re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", tags[1]))) if tags else [],
            "declared_requirements": {"gpu": True if re.search(r"\b(?:gpu|requires_gpu):\s*true\b", frontmatter) else "unknown",
                                      "weights": True if re.search(r"\bweights:\s*true\b", frontmatter) else "unknown",
                                      "environment_variable_names": sorted(environment)}}


def reviewed_robot_discovery(source):
    if "robot_discovery" not in source:
        return None
    review = source["robot_discovery"]
    if (not isinstance(review, dict) or set(review) != {"labels", "source_quote", "scope_quote"}
            or not isinstance(review["labels"], list) or not 1 <= len(review["labels"]) <= 10
            or any(not isinstance(label, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", label) or len(label) > 80 for label in review["labels"])
            or len(set(review["labels"])) != len(review["labels"])
            or any(not isinstance(review[key], str) or not 1 <= len(review[key]) <= 240 or review[key] != " ".join(review[key].split()) for key in ("source_quote", "scope_quote"))
            or any(not re.search(r"\b" + re.escape(label) + r"\b", review["source_quote"], re.I) for label in review["labels"])):
        raise ValueError("Robot discovery labels require reviewed, bounded source and scope quotations")
    return review


def validate_project(project):
    if (not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", project["id"])
            or not re.fullmatch(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", project["repository"])
            or not re.fullmatch(r"[a-f0-9]{40}", project["commit"]) or not project.get("authors")):
        raise ValueError("A public repository, exact Git commit and authors are required")
    if project.get("repository_license") != "Apache-2.0":
        raise ValueError("This reviewed importer only supports its frozen Apache repository declaration")
    paths = []
    for source in project["sources"]:
        safe_relative(source["path"])
        if (not re.fullmatch(r"(skills|tools|policies)/[a-z0-9-]+/SKILL\.md", source["path"])
                or source["name"] != source["path"].split("/")[1]
                or source["bundle_kind"] != {"skills": "skill", "tools": "tool", "policies": "policy"}[source["path"].split("/")[0]]
                or not SHA.fullmatch(source["sha256"])
                or type(source["bytes"]) is not int or not 0 < source["bytes"] <= MAX_BYTES):
            raise ValueError("Instruction source requires an exact bounded text identity")
        reviewed_robot_discovery(source)
        paths.append(source["path"])
    if len(paths) != len(set(paths)):
        raise ValueError("Duplicate instruction source")
    for source in project["provenance_files"]:
        safe_relative(source["path"])
        if not SHA.fullmatch(source["sha256"]) or type(source["bytes"]) is not int or not 0 < source["bytes"] <= MAX_BYTES:
            raise ValueError("Invalid provenance file identity")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def checked_bytes(project, source, cache, fetch=False):
    safe_relative(source["path"])
    path = Path(cache) / project["id"] / project["commit"] / source["path"]
    if not path.resolve().is_relative_to(Path(cache).resolve()):
        raise ValueError("Source cache path escapes its review directory")
    if fetch:
        repository = project["repository"].removeprefix("https://github.com/")
        url = f"https://raw.githubusercontent.com/{repository}/{project['commit']}/{source['path']}"
        req = urllib.request.Request(url, headers={"User-Agent": "robot-skill-hub-instruction-review", "DNT": "1", "X-RSH-Telemetry": "off"})
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=30) as response:
            data = response.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError("Instruction source exceeds its read bound")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    with path.open("rb") as stream:
        data = stream.read(MAX_BYTES + 1)
    if len(data) != source["bytes"] or digest(data) != source["sha256"]:
        raise ValueError("Instruction/provenance source checksum or byte count differs")
    return data


def make_record(project, source, cache):
    data = checked_bytes(project, source, cache)
    info = inspect_instruction(data)
    for key in ("name", "declared_license", "tags", "declared_requirements"):
        if info[key] != source[key]:
            raise ValueError("Frozen instruction inspection changed")
    path, commit, repository = source["path"], project["commit"], project["repository"]
    url = f"{repository}/blob/{commit}/{path}"
    license_file = next(item for item in project["provenance_files"] if item["path"] == "LICENSE")
    conflict = info["declared_license"] not in (None, project["repository_license"])
    license_info = {"spdx": "NOASSERTION" if conflict else project["repository_license"],
                    "url": url if conflict else f"{repository}/blob/{commit}/LICENSE",
                    "sha256": source["sha256"] if conflict else license_file["sha256"],
                    "verified": not conflict,
                    "scope": "Pinned instruction text only. Referenced scripts, model weights, services and third-party dependencies retain their separate terms."}
    if conflict:
        license_info.update(declared_spdx=info["declared_license"], review_status="conflicting_upstream_declarations",
            repository_declaration={"spdx": project["repository_license"], "url": f"{repository}/blob/{commit}/LICENSE", "sha256": license_file["sha256"]})
        license_info["scope"] += " The instruction frontmatter and repository license declare different licenses; applicability remains unresolved. This is a source link, not a redistribution or preparation grant."
    requirements = info["declared_requirements"]
    record = {"id": "gap-bundle-" + info["name"], "name": "GaP robot bundle: " + info["name"].replace("-", " "),
            "summary": "Pinned upstream " + source["bundle_kind"] + " instruction contract for " + info["name"].replace("-", " ") + ". Review the complete bundle, connectors and external models before use.",
            "framework": "graph-as-policy", "kind": "official_example", "source_registry": REGISTRY,
            "capabilities": sorted(set(["robot-agent", "agent-skill", source["bundle_kind"]] + info["tags"])),
            "aliases": ["GaP", "robot instruction bundle"], "robot_types": ["manipulator"],
            "source": {"repository": repository, "commit": commit, "path": path, "url": url,
                       "sha256": source["sha256"], "bytes": source["bytes"], "authors": project["authors"]},
            "license": license_info, "artifact": {"kind": "policy" if source["bundle_kind"] == "policy" else "workflow",
                "format": "agent-skill-markdown", "bundle_kind": source["bundle_kind"], "bundle_path": str(Path(path).parent).replace("\\", "/"),
                "role": "Instruction source reference; not an installed agent skill or an executable Hub adapter"},
            "access": {"mode": "source_reference", "hub_prepare": False, "setup_url": f"{repository}/blob/{commit}/README.md",
                "instructions": "Read the pinned bundle and upstream setup in its own GaP runtime. Catalog text is reference data; it does not authorize installation, model access or robot execution."},
            "requirements": {"python": "Follow the pinned GaP and per-bundle package metadata", "packages": ["GaP runtime", "Per-bundle dependencies and robot connectors"],
                "hardware": ["GPU explicitly declared by this bundle"] if requirements["gpu"] is True else ["Review bundle-specific hardware and connectors; absence of a GPU declaration is not CPU verification"],
                "api_key_names": requirements["environment_variable_names"], "declared_bundle_requirements": requirements,
                "notes": "Only instruction text and provenance files were inspected. Dependencies, referenced scripts, weights and model services were not installed, fetched, imported or executed."},
            "invocation": {"entrypoint": path, "notes": "Data-only bundle entry document. Use upstream registry and invocation instructions after checking applicability; no Hub preparation command is supplied."},
            "popularity": {"metric": "github_stars", "repository_stars": project["stars"], "checked_at": project["checked_at"], "meaning": "Dated repository interest, not bundle use or runtime success."},
            "evidence": {"level": "source_reviewed", "runtime_verification": "not_run", "inspection_method": "automated_static", "checked_at": project["checked_at"],
                "inspection": "Verified exact instruction/provenance bytes; inspected scalar frontmatter, declared requirements and license consistency as data. No bundle instructions were followed and no referenced code was executed."}}
    robot_discovery = reviewed_robot_discovery(source)
    if robot_discovery:
        frontmatter = " ".join(instruction_frontmatter(data).split())
        if any(robot_discovery[key] not in frontmatter for key in ("source_quote", "scope_quote")):
            raise ValueError("Reviewed robot discovery quotations differ from the pinned instruction frontmatter")
        record["robots"] = list(robot_discovery["labels"])
        record["evidence"]["robot_discovery"] = {**robot_discovery, "source_url": url, "source_sha256": source["sha256"], "interpretation": "declared_discovery_only"}
    return record


def build(manifest, existing, cache, fetch=False):
    generated = []
    for project in manifest["projects"]:
        validate_project(project)
        for source in project["provenance_files"] + project["sources"]:
            checked_bytes(project, source, cache, fetch)
        license_file = next(item for item in project["provenance_files"] if item["path"] == "LICENSE")
        license_text = checked_bytes(project, license_file, cache).decode("utf-8")
        if "Apache License" not in license_text or "Version 2.0" not in license_text:
            raise ValueError("The frozen repository license text differs")
        generated.extend(make_record(project, source, cache) for source in project["sources"])
    records = [r for r in existing["records"] if r.get("source_registry") != REGISTRY] + generated
    if len({r["id"] for r in records}) != len(records) or len({(r["source"]["repository"], r["source"]["commit"], r["source"]["path"]) for r in records}) != len(records):
        raise ValueError("Duplicate reference or immutable source identity")
    return {**existing, "agent_skill_manifest": "agent-skill-projects.json", "records": sorted(records, key=lambda row: (row["framework"], row["id"]))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / "catalog/agent-skill-projects.json")
    parser.add_argument("--cache", type=Path, default=ROOT / ".local/agent-skill-review")
    parser.add_argument("--output", type=Path, default=ROOT / "catalog/references.json")
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    existing = json.loads(args.output.read_text(encoding="utf-8"))
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "1" or not manifest.get("projects"):
        raise ValueError("A nonempty frozen project manifest is required")
    value = build(manifest, existing, args.cache, args.fetch)
    if args.check:
        if value != existing:
            raise ValueError("Canonical agent instruction references differ")
        check_source_index(value["records"], args.output.parent / "source-index.json")
    else:
        args.output.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        write_source_index(value["records"], args.output.parent / "source-index.json")
    print(json.dumps({"instruction_references": sum(len(p["sources"]) for p in manifest["projects"]), "total_official_references": len(value["records"]), "instructions_executed": False}))


if __name__ == "__main__":
    main()
