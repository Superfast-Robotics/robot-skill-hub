"""Evidence acceptance and timeout behavior; these do not run a simulator."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("runtime_verifier", ROOT / "tools/run_runtime_verification.py")
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)


class RuntimeEvidenceTests(unittest.TestCase):
    def test_runtime_catalog_embeds_the_exact_preparation_files(self):
        records = VERIFIER.load_runtime_records()
        self.assertEqual([record["id"] for record in records], list(VERIFIER.SKILLS))
        for record in records:
            files = record["preparation"]["files"]
            self.assertEqual(set(files), {"run.py", "requirements.txt"})
            for name, content in files.items():
                self.assertEqual(content, (ROOT / record["preparation"]["recipe_path"] / name).read_text(encoding="utf-8"))

    def setUp(self):
        self.record = {"invocation": {"inputs": {"task": "PickCube-v1", "max_episode_steps": 1000}}}
        self.execution = {"started": True, "exit_code": 0, "timed_out": False}
        self.result = {"status": "task_complete", "success": True, "elapsed_steps": 12,
                       "max_episode_steps": 1000, "terminated": True, "truncated": False,
                       "task": "PickCube-v1", "seed": 0, "runtime": "3.0.0b22", "robot": "panda",
                       "controller": "pd_joint_pos", "observation": "state", "sim_backend": "cpu", "render_backend": "none"}

    def assess(self):
        return VERIFIER.assess_result(self.record, self.execution, "diagnostic\n" + json.dumps(self.result) + "\n")

    def test_success_requires_actual_exit_and_exact_contract(self):
        self.assertEqual(self.assess()["status"], "task_complete")
        for key, value in (("exit_code", 1), ("timed_out", True), ("started", False)):
            with self.subTest(key=key):
                execution = {**self.execution, key: value}
                self.assertFalse(VERIFIER.assess_result(self.record, execution, json.dumps(self.result))["success"])
        self.result["render_backend"] = "gpu"
        self.assertFalse(self.assess()["success"])

    def test_preparation_and_failed_tasks_are_never_success(self):
        for result in ({"status": "ready", "execution_performed": False},
                       {**self.result, "success": False}, {**self.result, "elapsed_steps": True}):
            self.assertFalse(VERIFIER.assess_result(self.record, self.execution, json.dumps(result))["success"])

    def test_objective_after_truncation_or_unknown_episode_flags_is_not_success(self):
        for changes in ({"truncated": True}, {"elapsed_steps": 1000}, {"elapsed_steps": 1001},
                        {"max_episode_steps": 50}, {"terminated": None}, {"truncated": 0}):
            with self.subTest(changes=changes):
                result = {**self.result, **changes}
                self.assertFalse(VERIFIER.assess_result(self.record, self.execution, json.dumps(result))["success"])
        for field in ("max_episode_steps", "terminated", "truncated"):
            with self.subTest(missing=field):
                result = {k: v for k, v in self.result.items() if k != field}
                self.assertFalse(VERIFIER.assess_result(self.record, self.execution, json.dumps(result))["success"])

    def test_external_timeout_preserves_both_logs(self):
        with tempfile.TemporaryDirectory() as directory:
            prefix = Path(directory) / "timeout"
            execution, stdout = VERIFIER.run_command(
                [sys.executable, "-u", "-c", "import sys,time; print('started'); print('diagnostic',file=sys.stderr); time.sleep(10)"],
                prefix, timeout=0.4)
            self.assertTrue(execution["timed_out"])
            self.assertNotEqual(execution["exit_code"], 0)
            self.assertIn("started", stdout)
            self.assertIn("diagnostic", prefix.with_suffix(".stderr.txt").read_text())


if __name__ == "__main__":
    unittest.main()
