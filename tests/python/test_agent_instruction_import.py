"""Instruction source ingestion preserves provenance without executing bundles."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import import_agent_skill_sources as importer
sys.path.insert(0, str(ROOT / "skills/find-robot-skills/scripts"))
from rshlib.core import find


class AgentInstructionImportTests(unittest.TestCase):
    def fixture(self, license_line="Apache-2.0"):
        source = ("---\nname: fixture\ndescription: A robot instruction fixture.\nlicense: " + license_line + "\n"
                  "metadata: {tags: [perception, api]}\ngap:\n  requires: {gpu: true, env_any: [MODEL_API_KEY]}\n---\n"
                  "# Instruction source\nRun an external command only in its authorized upstream environment.\n").encode()
        license_text = b"Apache License\nVersion 2.0\n"
        info = importer.inspect_instruction(source)
        row = {"path": "skills/fixture/SKILL.md", "sha256": importer.digest(source), "bytes": len(source), "bundle_kind": "skill", **info}
        project = {"id": "fixture", "repository": "https://github.com/example/robot-bundles", "commit": "a" * 40,
                   "authors": ["Fixture authors"], "repository_license": "Apache-2.0", "checked_at": "2026-10-18", "stars": 0,
                   "provenance_files": [{"path": "LICENSE", "sha256": importer.digest(license_text), "bytes": len(license_text)}], "sources": [row]}
        return project, source, license_text

    def cache(self, directory, project, source, license_text):
        root = Path(directory) / project["id"] / project["commit"]
        path = root / project["sources"][0]["path"]
        path.parent.mkdir(parents=True)
        path.write_bytes(source)
        (root / "LICENSE").write_bytes(license_text)
        return path

    def test_source_is_data_and_declared_requirements_are_not_runtime_claims(self):
        project, source, license_text = self.fixture()
        with tempfile.TemporaryDirectory() as directory:
            self.cache(directory, project, source, license_text)
            with mock.patch.object(importer.urllib.request, "build_opener", side_effect=AssertionError("Offline inspection cannot contact services")):
                value = importer.build({"projects": [project]}, {"schema_version": "1", "records": []}, directory)
        record = value["records"][0]
        self.assertEqual(record["requirements"]["api_key_names"], ["MODEL_API_KEY"])
        self.assertTrue(record["requirements"]["declared_bundle_requirements"]["gpu"])
        self.assertEqual(record["evidence"]["runtime_verification"], "not_run")
        self.assertFalse(record["access"]["hub_prepare"])
        self.assertNotIn("compatibility", record)
        self.assertEqual(record["artifact"]["format"], "agent-skill-markdown")

    def test_disagreeing_component_license_stays_unresolved_and_source_only(self):
        project, source, license_text = self.fixture("MIT")
        with tempfile.TemporaryDirectory() as directory:
            self.cache(directory, project, source, license_text)
            record = importer.make_record(project, project["sources"][0], directory)
        self.assertEqual(record["license"]["spdx"], "NOASSERTION")
        self.assertEqual(record["license"]["declared_spdx"], "MIT")
        self.assertFalse(record["license"]["verified"])
        self.assertEqual(record["license"]["repository_declaration"]["spdx"], "Apache-2.0")
        self.assertFalse(record["access"]["hub_prepare"])

    def test_source_and_provenance_byte_drift_fail_before_publication(self):
        project, source, license_text = self.fixture()
        with tempfile.TemporaryDirectory() as directory:
            path = self.cache(directory, project, source, license_text)
            path.write_bytes(source + b" ")
            with self.assertRaisesRegex(ValueError, "checksum or byte"):
                importer.build({"projects": [project]}, {"records": []}, directory)
            path.write_bytes(source)
            path.parents[2].joinpath("LICENSE").write_bytes(license_text + b"drift")
            with self.assertRaisesRegex(ValueError, "checksum or byte"):
                importer.build({"projects": [project]}, {"records": []}, directory)

    def test_unknown_declaration_and_path_cannot_be_normalized_into_safe_metadata(self):
        for source in (b"---\nname: bad\ndescription: x\nlicense: !!python/object x\n---\n", b"---\nname: ../bad\ndescription: x\n---\n", b"\x00not-text"):
            with self.subTest(source=source), self.assertRaises(ValueError):
                importer.inspect_instruction(source)
        project, _, _ = self.fixture()
        for mutation in (lambda p: p.update(id="../../outside"), lambda p: p["sources"][0].update(path="../SKILL.md"), lambda p: p["sources"][0].update(name="other")):
            wrong = copy.deepcopy(project)
            mutation(wrong)
            with self.assertRaises(ValueError):
                importer.validate_project(wrong)

    def test_existing_sources_are_preserved_and_duplicate_identity_is_rejected(self):
        project, source, license_text = self.fixture()
        existing = {"id": "prior", "framework": "other", "source": {"repository": "https://github.com/example/other", "commit": "b" * 40, "path": "main.py"}}
        with tempfile.TemporaryDirectory() as directory:
            self.cache(directory, project, source, license_text)
            value = importer.build({"projects": [project]}, {"records": [existing]}, directory)
            self.assertEqual(existing, next(row for row in value["records"] if row["id"] == "prior"))
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                importer.build({"projects": [project, project]}, {"records": []}, directory)

    def test_reviewed_robot_labels_are_searchable_without_inventing_compatibility(self):
        project, source, license_text = self.fixture()
        source = source.replace(b"A robot instruction fixture.", b"A Franka Panda robot instruction fixture; excludes non-Franka embodiments.")
        row = project["sources"][0]
        row.update(sha256=importer.digest(source), bytes=len(source), robot_discovery={"labels": ["franka", "panda"], "source_quote": "Franka Panda", "scope_quote": "non-Franka embodiments"})
        with tempfile.TemporaryDirectory() as directory:
            self.cache(directory, project, source, license_text)
            value = importer.build({"projects": [project]}, {"records": []}, directory)
            record = value["records"][0]
            catalog = {"schema_version": "1", "hub_commit": "a" * 40, "records": [], "references": value}
            self.assertEqual(find(catalog, "panda", {"runtime": "graph-as-policy"})["total"], 1)
            self.assertEqual(find(catalog, "fixture", {"robot": "franka"})["total"], 1)
            self.assertEqual(find(catalog, "fixture", {"runtime": "graph-as-policy", "robot": "panda"})["total"], 0)
            self.assertEqual(record["evidence"]["robot_discovery"]["source_sha256"], importer.digest(source))
            self.assertNotIn("compatibility", record)
            self.assertFalse(record["access"]["hub_prepare"])
            self.assertEqual(record["evidence"]["runtime_verification"], "not_run")
            row["robot_discovery"]["scope_quote"] = "works with every robot"
            with self.assertRaisesRegex(ValueError, "quotations differ"):
                importer.build({"projects": [project]}, {"records": []}, directory)


if __name__ == "__main__":
    unittest.main()
