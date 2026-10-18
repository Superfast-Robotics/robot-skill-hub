"""Evidence acceptance and timeout behavior; these do not run a simulator."""
import importlib.util
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

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
        self.record = {"invocation": {"inputs": {"task": "PickCube-v1", "max_episode_steps": 1000,
            "seed": 0, "robot": "panda", "controller": "pd_joint_pos", "obs_mode": "state",
            "sim_backend": "cpu", "render_backend": "none"}}}
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

    def test_every_published_recipe_has_one_bounded_explicit_batch(self):
        selected = []
        for batch, ids in VERIFIER.BATCHES.items():
            self.assertGreater(len(ids), 0)
            self.assertLessEqual(len(ids), 3)
            records = VERIFIER.load_runtime_records(batch)
            self.assertEqual(list(ids), [record["id"] for record in records])
            selected.extend(ids)
        self.assertEqual(len(selected), len(set(selected)))
        self.assertEqual({p.stem for p in (ROOT / "catalog/records").glob("*.json")}, set(selected))

    def test_named_plan_never_runs_commands_downloads_or_creates_projects(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "not-created"
            stdout = io.StringIO()
            with mock.patch.object(VERIFIER, "run_command", side_effect=AssertionError("No process")), \
                    mock.patch.object(VERIFIER.subprocess, "check_output", side_effect=AssertionError("No Git process")), \
                    mock.patch.object(socket, "getaddrinfo", side_effect=AssertionError("No DNS")), \
                    mock.patch.object(socket, "create_connection", side_effect=AssertionError("No network")), \
                    redirect_stdout(stdout):
                code = VERIFIER.main(["--batch", "xarm6-basic", "--plan", "--output", str(destination),
                                      "--work-dir", str(destination)])
            result = json.loads(stdout.getvalue())
            self.assertEqual(0, code)
            self.assertFalse(destination.exists())
            self.assertFalse(result["execution_performed"])
            self.assertFalse(result["network_performed"])
            self.assertEqual(["xarm6_robotiq"] * 3, [r["inputs"]["robot"] for r in result["recipes"]])
        with self.assertRaises(ValueError):
            VERIFIER.load_runtime_records("unreviewed-task")

    def test_execution_acceptance_uses_selected_robot_and_controller(self):
        self.record["invocation"]["inputs"]["robot"] = "xarm6_robotiq"
        self.assertFalse(self.assess()["success"])
        self.result["robot"] = "xarm6_robotiq"
        self.assertTrue(self.assess()["success"])
        self.result["controller"] = "wrong-controller"
        self.assertFalse(self.assess()["success"])

    def test_plain_python_plan_does_not_write_import_bytecode_in_a_fresh_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            checkout = Path(directory)
            tools = checkout / "tools"
            tools.mkdir()
            runner = tools / "run_runtime_verification.py"
            runner.write_bytes((ROOT / "tools/run_runtime_verification.py").read_bytes())
            records = VERIFIER.load_runtime_records("xarm6-basic")
            # A fresh local publisher and sibling force normal source imports.
            # No copied source is robot code, and the fixture never reaches execution.
            (tools / "plan_fixture_dependency.py").write_text(
                "import json\nRECORDS=json.loads(" + repr(json.dumps(records)) + ")\n", encoding="utf-8")
            (tools / "build_catalog.py").write_text(
                "from plan_fixture_dependency import RECORDS\ndef load_records(): return RECORDS\n", encoding="utf-8")
            before = {p.relative_to(checkout) for p in checkout.rglob("*")}
            environment = {key: os.environ[key] for key in ("PATH", "SystemRoot", "WINDIR", "TEMP", "TMP") if key in os.environ}
            environment["PYTHONIOENCODING"] = "utf-8"
            process = subprocess.run([sys.executable, "-s", str(runner), "--batch", "xarm6-basic", "--plan"],
                cwd=checkout, env=environment, capture_output=True, timeout=10)
            self.assertEqual(0, process.returncode, process.stderr.decode("utf-8", "replace"))
            self.assertEqual("planned", json.loads(process.stdout)["status"])
            self.assertEqual(before, {p.relative_to(checkout) for p in checkout.rglob("*")})

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
