"""Workflow pin, attribution and additive ownership checks; no upstream runtime."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import import_robot_workflows as importer


class RobotWorkflowImportTests(unittest.TestCase):
    def fixture(self):
        files = {"scripts/train.py": b"raise RuntimeError('source must never execute')\nif __name__ == '__main__':\n    main()\n",
                 "LICENSE": b"MIT License\nCopyright Example Robotics\nPermission is hereby granted, free of charge\n",
                 "README.md": b"# Setup\nExample Robotics team\nPython 3.12\n"}

        def pin(path):
            return {"path": path, "sha256": importer.examples.digest(files[path]), "bytes": len(files[path])}

        artifact = {**pin("scripts/train.py"), "entrypoint_kind": "python_main", "role": "policy-training",
                    "name": "Policy training", "summary": "Train a configured policy.", "capabilities": ["policy-training"],
                    "robot_types": ["source-defined"], "robot_scope": "The selected task determines compatibility."}
        project = {"id": "fixture", "name": "Example Robotics", "repository": "https://github.com/example/robot",
                   "commit": "1" * 40, "ref": "main", "stars": 0, "checked_at": "2026-10-18",
                   "authors": ["Example Robotics team"], "capabilities": ["policy-training"], "execution_domain": "computation",
                   "requirements": {"python": "3.12", "packages": [], "environment": "Configured task and dataset"},
                   "setup_url": "https://github.com/example/robot/blob/" + "1" * 40 + "/README.md",
                   "invocation_notes": "Requires upstream configuration.", "selection": {"include": ["scripts/train.py"]},
                   "license": {**pin("LICENSE"), "spdx": "MIT", "scope": "Selected workflow source only"},
                   "evidence_files": [{**pin("README.md"), "purpose": "author and setup", "contains": ["Example Robotics team", "Python 3.12"]}],
                   "artifacts": [artifact]}
        return {"schema_version": "1", "projects": [project]}, files

    def populate(self, cache, project, files):
        for path, data in files.items():
            target = importer.examples.cache_path(cache, project, path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

    def test_offline_build_verifies_pins_without_executing_or_network(self):
        manifest, files = self.fixture()
        project = manifest["projects"][0]
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            self.populate(cache, project, files)
            with mock.patch.object(importer.urllib.request, "urlopen", side_effect=AssertionError("offline")):
                record = importer.build(manifest, cache, {"records": []})["records"][0]
            self.assertEqual("not_run", record["evidence"]["runtime_verification"])
            self.assertFalse(record["access"]["hub_prepare"])
            self.assertEqual(["Example Robotics team"], record["source"]["authors"])
            self.assertEqual(len(files["LICENSE"]), record["license"]["bytes"])
            self.assertEqual("workflow", record["artifact"]["kind"])
            self.assertEqual(project["evidence_files"][0]["sha256"], record["access"]["setup_evidence"][0]["sha256"])
            self.assertEqual({"records": [record]}, importer.build(manifest, cache, {"records": [record]}))

    def test_tampered_source_license_or_author_setup_document_is_rejected(self):
        for path in ["scripts/train.py", "LICENSE", "README.md"]:
            with self.subTest(path=path), tempfile.TemporaryDirectory() as directory:
                manifest, files = self.fixture()
                cache = Path(directory)
                project = manifest["projects"][0]
                self.populate(cache, project, files)
                importer.examples.cache_path(cache, project, path).write_bytes(files[path] + b"changed")
                with self.assertRaisesRegex(ValueError, "checksum/size"):
                    importer.build(manifest, cache, {"records": []})

    def test_library_source_and_different_per_file_license_are_rejected(self):
        for source in [b"def main():\n    pass\n", b"# SPDX-License-Identifier: GPL-3.0-only\nif __name__ == '__main__':\n    main()\n"]:
            with self.subTest(source=source), tempfile.TemporaryDirectory() as directory:
                manifest, files = self.fixture()
                project = manifest["projects"][0]
                files["scripts/train.py"] = source
                project["artifacts"][0].update(sha256=importer.examples.digest(source), bytes=len(source))
                cache = Path(directory)
                self.populate(cache, project, files)
                with self.assertRaises(ValueError):
                    importer.build(manifest, cache, {"records": []})

    def test_missing_byte_pin_and_missing_attribution_anchor_are_rejected(self):
        manifest, files = self.fixture()
        project = manifest["projects"][0]
        bad = copy.deepcopy(project)
        bad["license"]["bytes"] = 0
        with self.assertRaisesRegex(ValueError, "byte size"):
            importer.validate_project(bad)
        project["evidence_files"][0]["contains"] = ["Unsubstantiated author"]
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            self.populate(cache, project, files)
            with self.assertRaisesRegex(ValueError, "anchor missing"):
                importer.build(manifest, cache, {"records": []})

    def test_merge_preserves_foreign_records_and_rejects_shared_immutable_source(self):
        foreign = {"id": "existing", "framework": "intake", "source_registry": "community-intake-v1",
                   "source": {"repository": "https://github.com/example/robot", "commit": "1" * 40, "path": "client.py"},
                   "evidence": {"runtime_verification": "not_run"}}
        original = copy.deepcopy(foreign)
        new = {**copy.deepcopy(foreign), "id": "new", "source_registry": importer.REGISTRY,
               "source": {**foreign["source"], "path": "server.py"}}
        merged = importer.merge_records([foreign], [new])
        self.assertEqual(original, next(record for record in merged if record["id"] == "existing"))
        duplicate = {**copy.deepcopy(new), "source": copy.deepcopy(foreign["source"])}
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            importer.merge_records([foreign], [duplicate])

    def test_reviewed_manifest_is_unique_and_does_not_duplicate_other_registries(self):
        manifest = json.loads((ROOT / "catalog/workflow-projects.json").read_text(encoding="utf-8"))
        source_pins = []
        for project in manifest["projects"]:
            importer.validate_project(project)
            source_pins.extend((project["repository"], project["commit"], artifact["path"]) for artifact in project["artifacts"])
        self.assertEqual(len(source_pins), len(set(source_pins)))
        published = json.loads((ROOT / "catalog/references.json").read_text(encoding="utf-8"))["records"]
        foreign = {(r["source"]["repository"], r["source"].get("commit"), r["source"]["path"])
                   for r in published if r.get("source_registry") != importer.REGISTRY}
        self.assertFalse(set(source_pins) & foreign)


if __name__ == "__main__":
    unittest.main()
