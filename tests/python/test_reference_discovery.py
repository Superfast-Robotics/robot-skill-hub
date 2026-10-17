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
from rshlib.core import RshError, find, inspect, lookup_preparation
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
    def page_catalog(self):
        rows = [{**reference(), "id": "fixture-ik-" + str(index)} for index in reversed(range(8))]
        return catalog(*rows)

    def test_local_search_slices_sorted_pages_and_preserves_filters_and_effective_pin(self):
        data = self.page_catalog()
        first = find(data, "inverse kinematics", {"robot": "kuka"})
        next_page = first["next"]
        second = find(data, next_page["q"], {"robot": next_page["robot"]}, next_page["limit"],
                      offset=next_page["offset"], hub_commit=next_page["hub_commit"])
        last = find(data, "inverse kinematics", {"robot": "kuka"}, offset=6, hub_commit=data["hub_commit"])
        self.assertEqual((0, 3, 8), (first["offset"], first["limit"], first["total"]))
        self.assertEqual(["fixture-ik-0", "fixture-ik-1", "fixture-ik-2"], [row["id"] for row in first["results"]])
        self.assertEqual(["fixture-ik-3", "fixture-ik-4", "fixture-ik-5"], [row["id"] for row in second["results"]])
        self.assertEqual({"q": "inverse kinematics", "robot": "kuka", "offset": 3, "limit": 3, "hub_commit": data["hub_commit"]}, next_page)
        self.assertEqual("single_generation", second["pagination_stability"])
        self.assertEqual(2, len(last["results"]))
        self.assertIsNone(last["next"])
        empty = find(data, "inverse kinematics", {}, offset=1000000)
        self.assertEqual([], empty["results"])
        self.assertEqual(8, empty["total"])
        self.assertIsNone(empty["next"])

    def test_local_pinned_search_requires_both_recipe_and_reference_generations(self):
        data = self.page_catalog()
        expected = data["hub_commit"]
        data["references"]["hub_commit"] = "d" * 40
        for pin in (expected, "d" * 40):
            with self.subTest(pin=pin), self.assertRaises(RshError) as error:
                find(data, "inverse kinematics", {}, offset=3, hub_commit=pin)
            self.assertEqual("catalog_generation_changed", error.exception.result["reason_code"])
        data["references"]["hub_commit"] = expected
        self.assertEqual(3, len(find(data, "inverse kinematics", {}, offset=3, hub_commit=expected)["results"]))

    def test_mixed_or_unknown_local_generations_keep_origins_and_require_snapshot_for_stable_pages(self):
        data = self.page_catalog()
        data.update(catalog_origin="bundled", references_origin="cache")
        data["references"]["hub_commit"] = "d" * 40
        result = find(data, "inverse kinematics", {}, offset=3)
        self.assertEqual("bundled", result["catalog_origin"])
        self.assertEqual("cache", result["references_origin"])
        self.assertEqual(data["hub_commit"], result["catalog_hub_commit"])
        self.assertEqual("d" * 40, result["references_hub_commit"])
        self.assertNotIn("hub_commit", result["next"])
        self.assertEqual("snapshot_required", result["pagination_stability"])
        self.assertIn("catalog snapshot", result["pagination_note"])
        self.assertTrue(all(row["memory_base"]["hub_commit"] == "d" * 40 for row in result["results"]))
        data.pop("hub_commit")
        data["references"].pop("hub_commit")
        unknown = find(data, "inverse kinematics", {})
        self.assertNotIn("hub_commit", unknown["next"])
        self.assertEqual("snapshot_required", unknown["pagination_stability"])

    def test_local_search_rejects_invalid_bounds_and_commit_pins(self):
        for arguments in ({"offset": -1}, {"offset": 1000001}, {"offset": True}, {"offset": "3"},
                          {"limit": 0}, {"limit": 51}, {"limit": True}, {"hub_commit": "main"}, {"hub_commit": 42}):
            with self.subTest(arguments=arguments), self.assertRaises(RshError):
                find(self.page_catalog(), "inverse kinematics", {}, **arguments)

    def test_real_cli_local_second_page_and_generation_error_are_structured(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            data = self.page_catalog()
            path.write_text(json.dumps(data), encoding="utf-8")
            command = [sys.executable, str(SCRIPTS / "rsh.py"), "--catalog", str(path), "--offline", "--json",
                       "find", "inverse kinematics", "--offset", "3", "--hub-commit", data["hub_commit"]]
            env = {**os.environ, "RSH_TELEMETRY": "off"}
            page = subprocess.run(command, capture_output=True, text=True, env=env)
            self.assertEqual(0, page.returncode, page.stdout + page.stderr)
            self.assertEqual(["fixture-ik-3", "fixture-ik-4", "fixture-ik-5"], [row["id"] for row in json.loads(page.stdout)["results"]])
            data["references"]["hub_commit"] = "d" * 40
            path.write_text(json.dumps(data), encoding="utf-8")
            changed = subprocess.run(command, capture_output=True, text=True, env=env)
            self.assertEqual(2, changed.returncode, changed.stdout + changed.stderr)
            self.assertEqual("catalog_generation_changed", json.loads(changed.stdout)["reason_code"])

    def test_inspected_reference_routes_real_cli_to_pinned_source_only_plan(self):
        row = reference()
        row["source"]["bytes"] = 23
        row["license"] = {"spdx": "NOASSERTION", "verified": False,
                          "notes": "Review upstream terms before use."}
        data = catalog(row)
        detail = inspect(data, row["id"])
        self.assertEqual(row["source"], detail["source_acquisition"]["source"])
        self.assertEqual(row["license"], detail["source_acquisition"]["license"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            project = Path(directory) / "not-created"
            command = [sys.executable, str(SCRIPTS / "rsh.py"), "--catalog", str(path), "--offline", "--json",
                       *detail["fetch_source_args"], "--project", str(project), "--plan"]
            result = subprocess.run(command, capture_output=True, text=True,
                                    env={**os.environ, "RSH_TELEMETRY": "off"})
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            plan = json.loads(result.stdout)
            self.assertEqual("source_acquisition_plan", plan["reason_code"])
            self.assertEqual(row["source"]["commit"], plan["source_revision"])
            self.assertEqual(row["source"]["sha256"], plan["source_sha256"])
            self.assertFalse(plan["source_request_performed"])
            self.assertFalse(plan["execution_performed"])
            self.assertFalse(plan["environment_created"])
            self.assertFalse(plan["installed_as_skill"])
            self.assertFalse(project.exists())
            # Reusing the returned pins against a changed selection must fail,
            # even in plan mode, rather than silently choosing another file.
            data["references"]["records"][0]["source"]["sha256"] = "e" * 64
            path.write_text(json.dumps(data), encoding="utf-8")
            changed = subprocess.run(command, capture_output=True, text=True,
                                     env={**os.environ, "RSH_TELEMETRY": "off"})
            self.assertEqual(2, changed.returncode, changed.stdout + changed.stderr)
            self.assertEqual("selected_source_changed", json.loads(changed.stdout)["reason_code"])
            self.assertFalse(project.exists())

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

    def test_word_prefixes_reject_hardware_substrings_and_keep_declared_acronyms(self):
        algorithm = {**reference(), "id": "fixture-local-planner", "name": "Dynamic Window Approach", "aliases": ["DWA"]}
        hardware = {**reference(), "id": "fixture-hardware", "name": "Hardware controller", "summary": "Hardware setup example."}
        data = catalog(algorithm, hardware)
        self.assertEqual([algorithm["id"]], [row["id"] for row in find(data, "DWA", {}, 50)["results"]])
        self.assertEqual([hardware["id"]], [row["id"] for row in find(data, "hardw", {}, 50)["results"]])
        self.assertEqual([], find(data, "dwa impossible", {}, 50)["results"])
        self.assertEqual("all_terms_word_prefix", find(data, "DWA", {})["search_semantics"])

    def symbolic_planners_catalog(self):
        return catalog(
            {**reference(), "id": "fixture-astar", "name": "Hybrid AStar grid planner", "summary": "Grid route",
             "aliases": ["AStar", "A*", "Hybrid AStar"]},
            {**reference(), "id": "fixture-dstar", "name": "DStarLite incremental planner", "summary": "Incremental route",
             "aliases": ["DStarLite", "D* Lite"]},
            {**reference(), "id": "fixture-ordinary", "name": "Algebra dynamics",
             "summary": "Ordinary algorithm terms and literal A* D* text",
             "aliases": ["RA", "A B", "D B", "A variable", "\u00e9A", "\uB85C\uBD07A", "A*", "D*"]})

    def test_symbolic_queries_are_canonical_only_at_algorithm_boundaries(self):
        data = self.symbolic_planners_catalog()
        cases = [
            *[(q, ["fixture-astar"]) for q in ("A*", "a*", "!!!A*!!!", "(A*)/grid", "AStar grid", "Hybrid A*")],
            *[(q, ["fixture-dstar"]) for q in ("D*", "d* lite", "(D*)/incremental", "DStarLite")],
            *[(q, ["fixture-ordinary"]) for q in ("RA*", "A*B", "D*B", "a_variable*", "\u00e9A*", "\uB85C\uBD07A*", "algebra dynamics")],
            *[(q, ["fixture-astar", "fixture-ordinary"]) for q in ("A**", "*A*", "_A*", "A*_", "\u0301A*", "A*\u0301", "a")],
            ("D**", ["fixture-dstar", "fixture-ordinary"]), ("A* impossible", []), ("A* OR dynamics", [])]
        for query, expected in cases:
            with self.subTest(query=query):
                found = find(data, query, {}, 50)
                self.assertEqual(expected, [row["id"] for row in found["results"]])
                self.assertEqual(len(expected), found["total"])
                self.assertEqual("all_terms_word_prefix", found["search_semantics"])
                self.assertFalse(found["execution_performed"])
        self.assertEqual(0, find(data, "A*", {"runtime": "unknown-framework"})["total"])
        # The ordinary row's literal A* does not acquire an AStar document token.
        self.assertEqual(["fixture-astar"], [row["id"] for row in find(data, "astar", {})["results"]])

    def test_real_offline_cli_handles_literal_planners_without_single_letter_noise(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            path.write_text(json.dumps(self.symbolic_planners_catalog()), encoding="utf-8")
            for query, expected in (("A*", ["fixture-astar"]), ("D* Lite", ["fixture-dstar"]),
                                    ("Hybrid A*", ["fixture-astar"]), ("A**", ["fixture-astar", "fixture-ordinary"]),
                                    ("A*B", ["fixture-ordinary"]), ("algebra dynamics", ["fixture-ordinary"])):
                with self.subTest(query=query):
                    command = [sys.executable, str(SCRIPTS / "rsh.py"), "--catalog", str(path), "--offline", "--json", "find", query]
                    result = subprocess.run(command, capture_output=True, text=True, env={**os.environ, "RSH_TELEMETRY": "off"})
                    self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                    found = json.loads(result.stdout)
                    self.assertEqual(expected, [row["id"] for row in found["results"]])
                    self.assertEqual(len(expected), found["total"])
                    self.assertFalse(found["execution_performed"])

    def test_punctuation_does_not_become_catalog_browsing_and_unicode_words_remain_terms(self):
        accented = {**reference(), "id": "fixture-accent", "name": "Caf\u00e9 control"}
        data = catalog(reference(), accented)
        for query in ("---", "!!!", "\U0001f9be", "\u672a\u77e5"):
            with self.subTest(query=query):
                result = find(data, query, {}, offset=5)
                self.assertEqual((0, [], None, 5), (result["total"], result["results"], result["next"], result["offset"]))
        self.assertEqual(2, find(data, "  ", {}, 50)["total"])
        self.assertEqual(2, find(data, "!!!KUKA/inverse_kinematics!!!", {}, 50)["total"])
        self.assertEqual([accented["id"]], [row["id"] for row in find(data, "Caf\u00e9", {}, 50)["results"]])
        self.assertEqual(0, find(data, "cafe", {}, 50)["total"], "Local matching does not emulate unicode61 accent removal")

    def test_exact_source_id_ranks_before_prepared_recipe_and_continuation_keeps_order(self):
        source = {**reference(), "id": "fixture-target"}
        data = catalog(source)
        data["records"] = [{"id": "aaa-fixture-target", "name": "Fixture target", "summary": "Planning fixture", "capabilities": ["planning"],
                            "compatibility": [{"runtime": "fixture", "runtime_version": "1", "robot": "panda", "controller": "position", "observation": "state", "os": "linux"}],
                            "requirements": {"python": ">=3.10"}, "source": {"commit": "a" * 40}, "maintenance": {"record_version": "1"}, "evidence": {"level": "not_run"}}]
        first = find(data, source["id"], {}, 1)
        self.assertEqual(source["id"], first["results"][0]["id"])
        second = find(data, first["next"]["q"], {}, 1, offset=first["next"]["offset"], hub_commit=first["next"]["hub_commit"])
        self.assertEqual("aaa-fixture-target", second["results"][0]["id"])

    def test_reviewed_classical_planning_metadata_supports_natural_mpc_terms_without_hardware_noise(self):
        rows = json.loads((ROOT / "catalog/references.json").read_text(encoding="utf-8"))["records"]
        data = catalog(*rows)
        mpc = "pythonrobotics-pathtracking-model-predictive-speed-and-steer-contro-0c8264bec4bc"
        for query in ("model-predictive speed/steering", "model predictive speed steering", "MPC path tracking"):
            with self.subTest(query=query):
                found = find(data, query, {}, 3)
                self.assertEqual([mpc], [row["id"] for row in found["results"]])
                self.assertEqual(1, found["total"])
                self.assertFalse(found["execution_performed"])
                self.assertFalse(found["results"][0]["hub_prepare"])
        dwa = find(data, "DWA", {}, 3)
        self.assertEqual(["pythonrobotics-pathplanning-dynamicwindowapproach-dynamic-window-approach-py"], [row["id"] for row in dwa["results"]])
        self.assertEqual(1, dwa["total"])

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

    def test_declared_robot_types_are_searchable_without_becoming_environment_constraints(self):
        records = json.loads((ROOT / "catalog/references.json").read_text(encoding="utf-8"))["records"]
        classified = [row for row in records if "humanoid" in row.get("robot_types", [])
                      and "locomotion" in row.get("capabilities", [])]
        self.assertTrue(classified)
        result = find(catalog(*classified), "humanoid locomotion", {}, 50)
        self.assertEqual({row["id"] for row in classified}, {row["id"] for row in result["results"]})
        self.assertTrue(all(row["robot_types"] == ["humanoid"] and not row["hub_prepare"]
                            and row["compatibility_status"] == "unknown" for row in result["results"]))
        # A class label is neither an exact robot model nor an environment tuple.
        for environment in ({"robot": "humanoid"}, {"os": "linux"},
                            {"runtime": "isaaclab", "robot": "h1"}):
            with self.subTest(environment=environment):
                self.assertEqual(0, find(catalog(*classified), "humanoid locomotion", environment)["total"])

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
