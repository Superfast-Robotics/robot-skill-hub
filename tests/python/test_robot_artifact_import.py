"""Source/configuration provenance and static-only ingestion checks."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import import_robot_artifacts as importer


class RobotArtifactImportTests(unittest.TestCase):
    def fixture(self):
        source = b'<robot name="fixture"><link name="base"/></robot>\n'
        license_text = b'MIT License\nPermission is hereby granted, free of charge\nTHE SOFTWARE IS PROVIDED\n'
        project = {
            "id": "fixture", "name": "Fixture descriptions", "repository": "https://github.com/example/robot", "commit": "1" * 40,
            "ref": "reviewed-label", "stars": 0, "checked_at": "2026-10-18", "robot_types": ["arm"],
            "capabilities": ["robot-description"], "packages": ["Upstream robot package"], "environment": "Not loaded", "execution_domain": "configuration",
            "setup_url": "https://github.com/example/robot/blob/" + "1" * 40 + "/README.md",
            "licenses": {"LICENSE": {"spdx": "MIT", "sha256": importer.digest(license_text), "scope": "Description text only; adjacent assets have separate rights."}},
            "artifacts": [{"path": "urdf/arm.urdf", "sha256": importer.digest(source), "bytes": len(source), "kind": "robot_description", "format": "urdf", "license_path": "LICENSE"}],
        }
        return project, source, license_text

    def cached(self, cache, project, source, license_text):
        for path, data in [(project["artifacts"][0]["path"], source), ("LICENSE", license_text)]:
            target = importer.cache_path(cache, project, path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

    def test_exact_source_and_applicable_license_bytes_required(self):
        project, source, license_text = self.fixture()
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            self.cached(cache, project, source, license_text)
            importer.validate_project(project)
            importer.checked_licenses(project, cache)
            record = importer.make_record(project, project["artifacts"][0], cache)
            self.assertEqual("not_run", record["evidence"]["runtime_verification"])
            self.assertEqual("urdf", record["artifact"]["format"])
            self.assertFalse(record["access"]["hub_prepare"])
            self.assertIn(project["commit"], record["source"]["url"])
            importer.cache_path(cache, project, "urdf/arm.urdf").write_bytes(source + b" ")
            with self.assertRaisesRegex(ValueError, "checksum/size"):
                importer.make_record(project, project["artifacts"][0], cache)
            importer.cache_path(cache, project, "LICENSE").write_bytes(license_text + b" changed")
            with self.assertRaisesRegex(ValueError, "license checksum"):
                importer.checked_licenses(project, cache)

    def test_xml_is_parsed_without_resolving_adjacent_or_remote_files(self):
        source = b'<mujoco><include file="https://example.test/not-fetched.xml"/><asset><mesh file="../assets/mesh.stl"/></asset></mujoco>'
        with mock.patch.object(importer.urllib.request, "urlopen", side_effect=AssertionError("No network during static inspection")):
            result = importer.inspect_artifact("model/scene.xml", source)
        self.assertEqual("mjcf", result["format"])
        self.assertEqual(["../assets/mesh.stl", "https://example.test/not-fetched.xml"], result["references"])
        for data in [b'<!DOCTYPE robot [<!ENTITY x "a">]><robot name="&x;"/>', b'<html/>', b'<robot>', b'\x00binary', b'\xff']:
            with self.subTest(data=data), self.assertRaises((ValueError, UnicodeDecodeError, importer.ET.ParseError)):
                importer.inspect_artifact("urdf/arm.urdf", data)

    def test_xacro_and_yaml_are_not_evaluated_or_claimed_semantically_valid(self):
        result = importer.inspect_artifact("robot.urdf.xacro", b'<robot xmlns:xacro="http://www.ros.org/wiki/xacro"><xacro:include filename="$(find package)/other.xacro"/></robot>')
        self.assertEqual("xacro", result["format"])
        self.assertIn("not evaluated", result["inspection"])
        yaml = importer.inspect_artifact("config/limits.yaml", b'joint_limits:\n  joint1:\n    max_velocity: 2.0\n')
        self.assertEqual(["joint1", "joint_limits", "max_velocity"], yaml["keys"])
        self.assertIn("semantics", yaml["inspection"])
        self.assertIn("not evaluated", yaml["inspection"])
        with self.assertRaisesRegex(ValueError, "mapping keys"):
            importer.inspect_artifact("config/limits.yaml", b'# comments only\n')

    def test_project_rejects_mutable_refs_unknown_licenses_and_unsafe_paths(self):
        project, *_ = self.fixture()
        for edit in [lambda p:p.update(commit="main"), lambda p:p["artifacts"][0].update(path="../escape.urdf"),
                     lambda p:p["licenses"]["LICENSE"].update(spdx="LicenseRef-Unreviewed"),
                     lambda p:p["artifacts"][0].update(license_path="elsewhere/LICENSE"),
                     lambda p:p["artifacts"][0].update(bytes=importer.MAX_BYTES+1)]:
            changed = copy.deepcopy(project)
            edit(changed)
            with self.assertRaises(ValueError):
                importer.validate_project(changed)

    def test_foreign_records_preserved_and_duplicates_fail_closed(self):
        foreign = {"id":"existing","framework":"robot","source":{"repository":"https://github.com/example/robot","commit":"1"*40,"path":"old.py"}}
        owned = {**copy.deepcopy(foreign), "id":"owned", "source_registry":importer.REGISTRY}
        replacement = {**copy.deepcopy(owned), "source":{**owned["source"],"path":"new.urdf"}}
        combined = importer.merge_records([foreign,owned],[replacement])
        self.assertEqual(foreign, next(r for r in combined if r["id"]=="existing"))
        self.assertEqual("new.urdf", next(r for r in combined if r["id"]=="owned")["source"]["path"])
        with self.assertRaisesRegex(ValueError,"Duplicate"):
            importer.merge_records([foreign],[copy.deepcopy(foreign)])

    def test_empty_or_duplicate_project_manifests_cannot_drop_owned_records(self):
        project, *_ = self.fixture()
        for manifest in [{"schema_version":"1","projects":[]}, {"schema_version":"2","projects":[project]},
                         {"schema_version":"1","projects":[project,copy.deepcopy(project)]}]:
            with self.assertRaisesRegex(ValueError,"nonempty versioned manifest"):
                importer.build(manifest,Path("unused"),{"records":[]})

    def test_long_ids_are_stable_bounded_and_do_not_collide(self):
        project, source, license_text = self.fixture()
        artifact=project["artifacts"][0]
        with tempfile.TemporaryDirectory() as directory:
            cache=Path(directory)
            ids=[]
            for suffix in ("one", "two"):
                artifact["path"]="urdf/"+"shared-long-path-"*10+suffix+".urdf"
                self.cached(cache,project,source,license_text)
                record=importer.make_record(project,artifact,cache)
                self.assertLessEqual(len(record["id"]),80)
                ids.append(record["id"])
            self.assertNotEqual(*ids)

    def test_explicit_file_license_cannot_override_the_reviewed_license(self):
        project, _, license_text=self.fixture()
        source=b'<!-- SPDX-License-Identifier: Apache-2.0 --><robot name="arm"/>'
        artifact=project["artifacts"][0]
        artifact.update(sha256=importer.digest(source),bytes=len(source))
        with tempfile.TemporaryDirectory() as directory:
            self.cached(Path(directory),project,source,license_text)
            with self.assertRaisesRegex(ValueError,"per-file license"):
                importer.make_record(project,artifact,Path(directory))

    def test_matching_xml_license_and_model_specific_setup_are_preserved(self):
        project, _, license_text = self.fixture()
        source = b'<!-- SPDX-License-Identifier: MIT --><robot name="arm"/>'
        artifact = project["artifacts"][0]
        artifact.update(sha256=importer.digest(source), bytes=len(source), setup_path="urdf/README.md")
        with tempfile.TemporaryDirectory() as directory:
            self.cached(Path(directory), project, source, license_text)
            record = importer.make_record(project, artifact, Path(directory))
        self.assertTrue(record["access"]["setup_url"].endswith("/" + project["commit"] + "/urdf/README.md"))

    def test_published_artifact_inventory_matches_its_applicable_license_pins(self):
        manifest = json.loads((ROOT / "catalog/artifact-projects.json").read_text(encoding="utf-8"))
        references = json.loads((ROOT / "catalog/references.json").read_text(encoding="utf-8"))["records"]
        managed = {(r["source"]["repository"], r["source"]["commit"], r["source"]["path"]):r
                   for r in references if r.get("source_registry")==importer.REGISTRY}
        count = 0
        for project in manifest["projects"]:
            importer.validate_project(project)
            for artifact in project["artifacts"]:
                record = managed[project["repository"], project["commit"], artifact["path"]]
                license_info = project["licenses"][artifact["license_path"]]
                self.assertEqual(artifact["sha256"], record["source"]["sha256"])
                self.assertEqual(artifact["bytes"], record["source"]["bytes"])
                self.assertEqual(artifact["kind"], record["artifact"]["kind"])
                self.assertEqual(artifact["format"], record["artifact"]["format"])
                self.assertEqual(license_info["sha256"], record["license"]["sha256"])
                self.assertEqual(license_info["spdx"], record["license"]["spdx"])
                self.assertIn("/"+project["commit"]+"/"+artifact["license_path"], record["license"]["url"])
                self.assertEqual("not_run",record["evidence"]["runtime_verification"])
                self.assertFalse(record["access"]["hub_prepare"])
                count += 1
        self.assertEqual(len(managed), count)


if __name__ == "__main__":
    unittest.main()
