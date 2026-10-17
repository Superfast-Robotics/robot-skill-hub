"""Check source provenance and adapters with fake modules, without a simulator."""
import contextlib
import importlib.metadata
import io
import json
from pathlib import Path
import runpy
import sys
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import import_official_samples as importer


class Scalar:
    def __init__(self, value):
        self.value = value

    def item(self):
        return self.value


class BulkAdapterTests(unittest.TestCase):
    def invoke(self, sample, result):
        name = importer.solver_module(sample)
        modules = {}
        pieces = name.split(".")
        for n in range(1, len(pieces) + 1):
            module_name = ".".join(pieces[:n])
            module = types.ModuleType(module_name)
            module.__path__ = []
            modules[module_name] = module
            if n > 1:
                setattr(modules[".".join(pieces[:n-1])], pieces[n-1], module)
        envs = types.ModuleType("mani_skill.envs")
        modules["mani_skill.envs"] = envs
        modules["mani_skill"].envs = envs
        environment = types.SimpleNamespace(close=mock.Mock())
        gym = types.ModuleType("gymnasium")
        gym.make = mock.Mock(return_value=environment)
        modules["gymnasium"] = gym
        modules[name].solve = mock.Mock(return_value=result)
        script = ROOT / "recipes" / ("maniskill-" + sample[0]) / "run.py"
        output = io.StringIO()
        with mock.patch.dict(sys.modules, modules), mock.patch.object(importlib.metadata, "version", return_value="3.0.0b22"), \
                mock.patch.object(sys, "argv", [str(script), "--seed", "9"]), contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as exited:
                runpy.run_path(str(script), run_name="__main__")
        return json.loads(output.getvalue()), exited.exception.code, gym.make, modules[name].solve, environment

    def test_all_added_robot_task_pairs_preserve_explicit_simulation_contract(self):
        for sample in importer.SAMPLES:
            with self.subTest(sample=sample[0]):
                result = (None, None, Scalar(True), Scalar(False),
                          {"success": Scalar(True), "elapsed_steps": Scalar(15)})
                report, code, make, solve, env = self.invoke(sample, result)
                self.assertEqual(code, 0)
                self.assertEqual(make.call_args.args, (sample[2],))
                options = make.call_args.kwargs
                for key, expected in {"sim_backend": "cpu", "render_backend": "none", "render_mode": None,
                                      "obs_mode": "state", "control_mode": "pd_joint_pos", "reward_mode": "sparse",
                                      "max_episode_steps": 1000}.items():
                    self.assertEqual(options[key], expected)
                if sample[3] == "so100":
                    self.assertNotIn("robot_uids", options)  # SO100 subclass supplies this itself.
                else:
                    self.assertEqual(options["robot_uids"], sample[3])
                solve.assert_called_once_with(env, seed=9, debug=False, vis=False)
                env.close.assert_called_once()
                self.assertEqual(report["robot"], sample[3])
                self.assertEqual(report["task"], sample[2])
                self.assertTrue(report["success"])
                self.assertEqual(report["max_episode_steps"], 1000)
                self.assertTrue(report["terminated"])
                self.assertFalse(report["truncated"])

    def test_every_added_adapter_rejects_success_after_truncation_or_horizon(self):
        for sample in importer.SAMPLES:
            for truncated, elapsed, reason in ((True, 15, "episode_truncated"),
                                               (False, 1000, "horizon_exceeded"),
                                               (False, 0, "invalid_elapsed_steps")):
                with self.subTest(sample=sample[0], truncated=truncated, elapsed=elapsed):
                    result = (None, None, Scalar(True), Scalar(truncated),
                              {"success": Scalar(True), "elapsed_steps": Scalar(elapsed)})
                    report, code, _, _, env = self.invoke(sample, result)
                    self.assertEqual(code, 1)
                    self.assertEqual(report["status"], "failed")
                    self.assertTrue(report["success"])
                    self.assertEqual(report["reason_code"], reason)
                    env.close.assert_called_once()

    def test_generator_preserves_reviewed_adapter_horizon_safety(self):
        for sample in importer.SAMPLES:
            with self.subTest(sample=sample[0]):
                actual = (ROOT / "recipes" / ("maniskill-" + sample[0]) / "run.py").read_text(encoding="utf-8")
                self.assertEqual(importer.wrapper(sample), actual)

    def test_planning_failure_never_becomes_success(self):
        for sample in importer.SAMPLES:
            with self.subTest(sample=sample[0]):
                report, code, _, _, env = self.invoke(sample, -1)
                self.assertEqual(code, 1)
                self.assertEqual(report["reason_code"], "motion_plan_failed")
                self.assertNotIn("success", report)
                env.close.assert_called_once()

    def test_added_records_keep_source_only_evidence_and_special_requirements(self):
        for sample in importer.SAMPLES:
            record = json.loads((ROOT / "catalog/records" / ("maniskill-" + sample[0] + ".json")).read_text())
            self.assertEqual(record["invocation"]["entrypoint"], importer.solver_module(sample) + ":solve")
            self.assertEqual(record["source"]["commit"], importer.PIN)
            self.assertEqual(record["source"]["archive_sha256"], importer.ARCHIVE_SHA256)
            self.assertEqual(record["evidence"]["runtime_verification"], "not_run")
            self.assertEqual(record["compatibility"][0]["robot"], sample[3])
            if sample[2] == "DrawSVG-v1":
                self.assertIn("svgpathtools==1.6.1", record["requirements"]["packages"])

    def test_reference_examples_do_not_claim_hub_preparation(self):
        path = ROOT / "catalog/references.json"
        if not path.exists():
            self.skipTest("Reference index is not generated yet")
        records = json.loads(path.read_text())["records"]
        self.assertGreaterEqual(len(records), 30)
        self.assertEqual(len(records), len({r["id"] for r in records}))
        for record in records:
            self.assertEqual(record["access"]["mode"], "source_reference")
            self.assertFalse(record["access"]["hub_prepare"])
            source = record["source"]
            self.assertRegex(source["commit"], r"^[a-f0-9]{40}$")
            self.assertRegex(source["sha256"], r"^[a-f0-9]{64}$")
            self.assertEqual(source["url"], f"{source['repository']}/blob/{source['commit']}/{source['path']}")
            self.assertEqual(record["evidence"]["runtime_verification"], "not_run")


if __name__ == "__main__":
    unittest.main()
