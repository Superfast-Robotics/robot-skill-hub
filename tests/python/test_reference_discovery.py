"""Agent-facing search and no-adapter behavior for immutable source references."""
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills/find-robot-skills/scripts"
sys.path.insert(0, str(SCRIPTS))
from rshlib.core import RshError, find, lookup_preparation
preparation = importlib.import_module("rshlib.prepare")


def reference():
    return {"id": "pybullet-fixture-ik", "name": "KUKA inverse kinematics", "summary": "Compute end-effector joint targets.",
            "framework": "pybullet", "capabilities": ["inverse-kinematics"], "robots": ["kuka"],
            "source": {"repository": "https://github.com/example/robot", "commit": "a" * 40,
                       "path": "example.py", "url": "https://github.com/example/robot/blob/" + "a" * 40 + "/example.py", "sha256": "b" * 64},
            "access": {"mode": "source_reference", "hub_prepare": False, "setup_url": "https://github.com/example/robot/setup"},
            "evidence": {"level": "source_reviewed", "runtime_verification": "not_run"}}


def catalog(*references):
    return {"schema_version": "1", "hub_commit": "c" * 40, "records": [],
            "references": {"schema_version": "1", "records": list(references)}}


class ReferenceDiscoveryTests(unittest.TestCase):
    def test_query_requires_every_term_for_references_and_recipes(self):
        partial = reference()
        partial.update(id="pybullet-fixture-dynamics", name="KUKA inverse dynamics", capabilities=["inverse-dynamics"])
        data = catalog(reference(), partial)
        self.assertEqual(["pybullet-fixture-ik"], [r["id"] for r in find(data, "kuka inverse kinematics", {}, 50)["results"]])
        self.assertEqual([], find(data, "kuka inverse kinematics missingterm", {}, 50)["results"])
        self.assertEqual([], find(data, "없는스킬", {}, 50)["results"])
        self.assertEqual(["pybullet-fixture-ik"], [r["id"] for r in find(data, "kuka/inverse_kinematics", {}, 50)["results"]])
        data["records"] = [{"id": "fixture-pick", "name": "Pick object", "summary": "Reach a cube", "capabilities": ["pick"],
                            "compatibility": [{"runtime": "fixture", "runtime_version": "1", "robot": "panda", "controller": "position", "observation": "state", "os": "linux"}],
                            "requirements": {"python": ">=3.10"}, "source": {"commit": "a" * 40}, "maintenance": {"record_version": "1"}, "evidence": {"level": "not_run"}}]
        self.assertEqual([], find(data, "pick missingterm", {}, 50)["results"])
        self.assertEqual("fixture-pick", find(data, "pick object", {}, 50)["results"][0]["id"])

    def test_single_robot_filter_requires_an_explicit_discovery_fact(self):
        unknown = reference()
        unknown["id"] = "robot-unknown"
        unknown.pop("robots")
        data = catalog(reference(), unknown)
        results = find(data, "inverse kinematics", {"robot": "KUKA"}, 50)["results"]
        self.assertEqual(["pybullet-fixture-ik"], [r["id"] for r in results])
        self.assertEqual("unknown", results[0]["compatibility_status"])
        self.assertFalse(results[0]["hub_prepare"])
        self.assertEqual([], find(data, "inverse kinematics", {"robot": "panda"}, 50)["results"])

    def test_single_runtime_filter_accepts_framework_or_explicit_runtime_only(self):
        row = reference()
        self.assertEqual(1, find(catalog(row), "inverse kinematics", {"runtime": "PYBULLET"})["total"])
        self.assertEqual(0, find(catalog(row), "inverse kinematics", {"runtime": "unknown-framework"})["total"])
        row["runtime"] = "explicit-runtime"
        self.assertEqual(1, find(catalog(row), "inverse kinematics", {"runtime": "explicit-runtime"})["total"])

    def test_unknown_values_do_not_become_verified_compatibility(self):
        for environment in ({}, {"robot": "unknown"}, {"runtime": "UNKNOWN", "controller": ""}):
            with self.subTest(environment=environment):
                result = find(catalog(reference()), "inverse kinematics", environment)["results"][0]
                self.assertEqual("unknown", result["compatibility_status"])
                self.assertEqual(["upstream_environment_review"], result["missing_requirements"])

    def test_multiple_filters_cannot_be_synthesized_from_individual_discovery_labels(self):
        self.assertEqual(0, find(catalog(reference()), "inverse kinematics", {"runtime": "pybullet", "robot": "kuka"})["total"])
        for field, value in (("controller", "position"), ("observation", "state"), ("os", "linux"), ("runtime_version", "3.25"), ("python", "3.10"), ("architecture", "x86_64")):
            with self.subTest(field=field):
                self.assertEqual(0, find(catalog(reference()), "inverse kinematics", {field: value})["total"])

    def test_filters_must_match_one_whole_declared_combination(self):
        row = reference()
        row["compatibility"] = [
            {"runtime": "pybullet", "runtime_version": "3.25", "robot": "kuka", "controller": "torque", "observation": "state", "os": "linux"},
            {"runtime": "pybullet", "runtime_version": "3.25", "robot": "panda", "controller": "position", "observation": "rgb", "os": "windows"}]
        data = catalog(row)
        for split in ({"robot": "kuka", "controller": "position"}, {"controller": "torque", "os": "windows"}, {"robot": "panda", "observation": "state"}):
            with self.subTest(split=split):
                self.assertEqual(0, find(data, "inverse kinematics", split)["total"])
        exact = find(data, "inverse kinematics", {"runtime": "pybullet", "robot": "kuka", "controller": "torque", "observation": "state", "os": "linux"})
        self.assertEqual(1, exact["total"])
        self.assertEqual("unknown", exact["results"][0]["compatibility_status"])
        self.assertEqual(0, find(data, "inverse kinematics", {"runtime": "pybullet", "python": "3.10"})["total"])

    def test_source_reference_preparation_stops_before_download_or_environment_work(self):
        row = reference()
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "not-created"
            with mock.patch.object(preparation, "download_archive") as download, mock.patch.object(preparation, "local_environment") as host, mock.patch.object(preparation.venv, "EnvBuilder") as environment:
                with self.assertRaises(RshError) as error:
                    preparation.prepare(catalog(row), row["id"], project, {}, plan=True)
            result = error.exception.result
            self.assertEqual(("unsupported", "source_reference_no_adapter", "open_source_reference"), (result["status"], result["reason_code"], result["next_action"]))
            self.assertEqual(row["source"]["url"], result["source_url"])
            self.assertEqual(row["access"]["setup_url"], result["setup_url"])
            self.assertFalse(result["source_download_performed"])
            self.assertFalse(result["environment_created"])
            self.assertFalse(result["execution_performed"])
            self.assertFalse(project.exists())
            download.assert_not_called()
            host.assert_not_called()
            environment.assert_not_called()
        with self.assertRaises(RshError) as missing:
            lookup_preparation(catalog(row), "missing-id")
        self.assertEqual("skill_not_found", missing.exception.result["reason_code"])

    def test_real_cli_prepare_plan_reports_known_source_and_setup_instructions(self):
        row = reference()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            path.write_text(json.dumps(catalog(row)), encoding="utf-8")
            project = Path(directory) / "project"
            result = subprocess.run([sys.executable, str(SCRIPTS / "rsh.py"), "--catalog", str(path), "--offline", "--json", "prepare", row["id"], "--project", str(project), "--plan"], capture_output=True, text=True, env={**os.environ, "RSH_TELEMETRY": "off"})
            self.assertEqual(2, result.returncode, result.stderr)
            response = json.loads(result.stdout)
            self.assertEqual("source_reference_no_adapter", response["reason_code"])
            self.assertEqual(row["source"]["url"], response["source_url"])
            self.assertEqual("open_source_reference", response["next_action"])
            self.assertFalse(project.exists())

    def test_reviewed_kuka_sources_have_only_source_backed_robot_labels(self):
        records = json.loads((ROOT / "catalog/references.json").read_text(encoding="utf-8"))["records"]
        kuka = [row for row in records if row["framework"] == "pybullet" and "kuka" in row["capabilities"]]
        self.assertEqual(4, len(kuka))
        self.assertTrue(all(row.get("robots") == ["kuka"] for row in kuka))
        data = catalog(*records)
        result = find(data, "inverse kinematics", {"robot": "kuka"}, 50)
        self.assertEqual({"pybullet-inverse-kinematics", "pybullet-ik-end-effector-orientation"}, {r["id"] for r in result["results"]})


if __name__ == "__main__":
    unittest.main()
