"""Wrapper contract checks with fake dependencies, never a simulator task run."""
import contextlib
import importlib.metadata
import io
import json
import runpy
import subprocess
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]


class Scalar:
    def __init__(self, value):
        self.value = value

    def item(self):
        return self.value


class AdapterContractTests(unittest.TestCase):
    def run_fake_adapter(self, task, *, failure=None, success=True, version="3.0.0b22",
                         terminated=True, truncated=False, elapsed_steps=12):
        solver_name = "pick_cube" if task == "pick-cube" else "stack_cube"
        full_name = "mani_skill.examples.motionplanning.panda.solutions." + solver_name
        modules = {}
        for name in ("mani_skill", "mani_skill.envs", "mani_skill.examples", "mani_skill.examples.motionplanning",
                     "mani_skill.examples.motionplanning.panda", "mani_skill.examples.motionplanning.panda.solutions", full_name):
            module = types.ModuleType(name)
            module.__path__ = []
            modules[name] = module
            if "." in name:
                parent, attribute = name.rsplit(".", 1)
                setattr(modules[parent], attribute, module)
        environment = types.SimpleNamespace(close=mock.Mock())
        gym = types.ModuleType("gymnasium")
        gym.make = mock.Mock(return_value=environment)
        modules["gymnasium"] = gym
        returned = (None, None, Scalar(terminated), Scalar(truncated),
                    {"success": Scalar(success), "elapsed_steps": Scalar(elapsed_steps)})
        solve = mock.Mock(return_value=returned, side_effect=failure)
        modules[full_name].solve = solve
        output = io.StringIO()
        script = ROOT / "recipes" / ("maniskill-panda-" + task) / "run.py"
        with mock.patch.dict(sys.modules, modules), mock.patch.object(importlib.metadata, "version", return_value=version), \
                mock.patch.object(sys, "argv", [str(script), "--seed", "7"]), contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as exit_signal:
                runpy.run_path(str(script), run_name="__main__")
        return json.loads(output.getvalue()), exit_signal.exception.code, gym.make, solve, environment

    def test_cpu_state_recipe_explicitly_disables_renderer(self):
        for task in ("pick-cube", "stack-cube"):
            with self.subTest(task=task):
                report, code, make, solve, environment = self.run_fake_adapter(task)
                self.assertEqual(make.call_args.kwargs["sim_backend"], "cpu")
                self.assertEqual(make.call_args.kwargs["render_backend"], "none")
                self.assertIsNone(make.call_args.kwargs["render_mode"])
                self.assertEqual(make.call_args.kwargs["obs_mode"], "state")
                self.assertEqual(make.call_args.kwargs["max_episode_steps"], 1000)
                solve.assert_called_once_with(environment, seed=7, debug=False, vis=False)
                environment.close.assert_called_once()
                self.assertEqual(code, 0)
                self.assertEqual(report["status"], "task_complete")
                self.assertEqual(report["seed"], 7)
                self.assertEqual(report["max_episode_steps"], 1000)
                self.assertTrue(report["terminated"])
                self.assertFalse(report["truncated"])

    def test_truncation_or_horizon_exhaustion_never_reports_task_complete(self):
        cases = ({"truncated": True, "elapsed_steps": 74, "reason": "episode_truncated"},
                 {"truncated": False, "elapsed_steps": 1000, "reason": "horizon_exceeded"},
                 {"truncated": False, "elapsed_steps": 1001, "reason": "horizon_exceeded"},
                 {"truncated": False, "elapsed_steps": 0, "reason": "invalid_elapsed_steps"})
        for task in ("pick-cube", "stack-cube"):
            for case in cases:
                with self.subTest(task=task, case=case):
                    report, code, _, _, environment = self.run_fake_adapter(
                        task, success=True, truncated=case["truncated"], elapsed_steps=case["elapsed_steps"])
                    self.assertTrue(report["success"])  # Preserve the raw objective observation.
                    self.assertEqual(report["status"], "failed")
                    self.assertEqual(report["reason_code"], case["reason"])
                    self.assertEqual(report["elapsed_steps"], case["elapsed_steps"])
                    self.assertEqual(code, 1)
                    environment.close.assert_called_once()

    def test_successful_termination_inside_horizon_is_valid(self):
        for task in ("pick-cube", "stack-cube"):
            with self.subTest(task=task):
                report, code, _, _, _ = self.run_fake_adapter(task, terminated=True, elapsed_steps=999)
                self.assertEqual(report["status"], "task_complete")
                self.assertEqual(code, 0)
                self.assertNotIn("reason_code", report)

    def test_solver_failure_closes_environment_and_preserves_json_failure(self):
        for task in ("pick-cube", "stack-cube"):
            with self.subTest(task=task):
                report, code, make, solve, environment = self.run_fake_adapter(task, failure=RuntimeError("fixture planning failure"))
                self.assertEqual(code, 1)
                self.assertEqual(report["status"], "failed")
                self.assertEqual(report["error_type"], "RuntimeError")
                environment.close.assert_called_once()

    def test_false_success_and_wrong_version_are_not_task_complete(self):
        report, code, _, _, _ = self.run_fake_adapter("pick-cube", success=False)
        self.assertEqual(code, 1)
        self.assertEqual(report["status"], "failed")
        report, code, make, solve, _ = self.run_fake_adapter("stack-cube", version="99.0.0")
        self.assertEqual(code, 1)
        self.assertEqual(report["error_type"], "RuntimeError")
        make.assert_not_called()
        solve.assert_not_called()

    def test_missing_distribution_returns_json_in_real_python_process(self):
        for task in ("pick-cube", "stack-cube"):
            with self.subTest(task=task):
                script = ROOT / "recipes" / ("maniskill-panda-" + task) / "run.py"
                executed = subprocess.run([sys.executable, "-S", str(script), "--seed", "0"],
                                          stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=15)
                report = json.loads(executed.stdout)
                self.assertEqual(executed.returncode, 1)
                self.assertEqual(report["status"], "failed")
                self.assertEqual(report["error_type"], "PackageNotFoundError")
                self.assertNotIn("Traceback", executed.stderr)


if __name__ == "__main__":
    unittest.main()
