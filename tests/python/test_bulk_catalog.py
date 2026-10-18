"""Check source provenance and adapters with fake modules, without a simulator."""
import contextlib
import hashlib
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

TRANSPORT_PROOF = ROOT / "evidence/runtime/panda-transport-39097136411"
TRANSPORT_PROOF_COMMIT = "039c103622c93e79d7b2ddb60dd0fc7345ebeab5"
STACKING_ID = "maniskill-panda-stack-pyramid"
STACKING_PROOF = ROOT / "evidence/runtime/panda-stacking-39100095436"
STACKING_PROOF_COMMIT = "e81d47efc18f98d811e12fea0b8b5622a2dbbeaf"
TRANSPORT_RESULTS = {
    "maniskill-panda-push-cube": ("PushCube-v1", 71),
    "maniskill-panda-pull-cube": ("PullCube-v1", 67),
    "maniskill-panda-lift-peg-upright": ("LiftPegUpright-v1", 176),
}


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

    def test_added_records_keep_pins_review_scope_and_special_requirements(self):
        for sample in importer.SAMPLES:
            record = json.loads((ROOT / "catalog/records" / ("maniskill-" + sample[0] + ".json")).read_text())
            self.assertEqual(record["invocation"]["entrypoint"], importer.solver_module(sample) + ":solve")
            self.assertEqual(record["source"]["commit"], importer.PIN)
            self.assertEqual(record["source"]["archive_sha256"], importer.ARCHIVE_SHA256)
            proven = record["id"] in TRANSPORT_RESULTS
            expected_runtime = "task_complete" if proven else "import_verified" if record["id"] == STACKING_ID else "not_run"
            self.assertEqual(record["evidence"]["runtime_verification"], expected_runtime)
            self.assertEqual(record["compatibility"][0]["status"], "hub_verified" if proven else "source_reviewed")
            self.assertEqual(record["compatibility"][0]["robot"], sample[3])
            if sample[2] == "DrawSVG-v1":
                self.assertIn("svgpathtools==1.6.1", record["requirements"]["packages"])

    def test_transport_promotion_matches_immutable_execution_evidence(self):
        manifest = json.loads((TRANSPORT_PROOF / "manifest.json").read_bytes())
        self.assertEqual(manifest["requested_skills"], list(TRANSPORT_RESULTS))
        self.assertEqual(manifest["original_artifact_id"], 12125411457)
        self.assertEqual(manifest["original_artifact_sha256"],
                         "a6714f527caad7a112451f940f5617dfc5173a286c42429847e877eb4e958257")
        self.assertTrue(manifest["provider_digest_verified"])
        for relative, digest in manifest["files_sha256"].items():
            self.assertEqual(hashlib.sha256((TRANSPORT_PROOF / relative).read_bytes()).hexdigest(), digest, relative)
        summary = json.loads((TRANSPORT_PROOF / "report.json").read_bytes())
        orchestration = json.loads((TRANSPORT_PROOF / "orchestration.json").read_bytes())
        self.assertEqual(summary["batch"], "panda-transport")
        self.assertEqual(summary["hub_commit"], manifest["verified_hub_commit"])
        self.assertFalse(orchestration["fresh_blind_context"])
        self.assertEqual(orchestration["orchestrator"], "same_maintainer_agent_explicit_named_batch")
        self.assertEqual(len(summary["recipes"]), 3)
        for ident, (task, steps) in TRANSPORT_RESULTS.items():
            with self.subTest(skill=ident):
                report = json.loads((TRANSPORT_PROOF / ident / "report.json").read_bytes())
                stdout = (TRANSPORT_PROOF / ident / "task.stdout.txt").read_text().splitlines()
                result = json.loads(stdout[-1])
                command = json.loads((TRANSPORT_PROOF / ident / "task.command.json").read_bytes())
                environment = json.loads((TRANSPORT_PROOF / ident / "environment.json").read_bytes())
                record = json.loads((ROOT / "catalog/records" / (ident + ".json")).read_bytes())
                evidence = record["evidence"]
                verified = evidence["hub_verification"]
                self.assertEqual(report["result"], result)
                self.assertIn(report, summary["recipes"])
                self.assertEqual(report["execution"], command)
                self.assertTrue(report["execution_performed"])
                self.assertTrue(report["contract_matches"])
                self.assertEqual(result["task"], task)
                self.assertEqual(result["elapsed_steps"], steps)
                self.assertTrue(result["success"])
                self.assertTrue(result["terminated"])
                self.assertFalse(result["truncated"])
                self.assertEqual(result["max_episode_steps"], 1000)
                self.assertGreater(steps, 0)
                self.assertLess(steps, result["max_episode_steps"])
                self.assertEqual(result["seed"], 0)
                self.assertEqual(result["sim_backend"], "cpu")
                self.assertEqual(result["render_backend"], "none")
                self.assertEqual(command["exit_code"], 0)
                self.assertTrue(command["started"])
                self.assertFalse(command["timed_out"])
                self.assertEqual(command["timeout_seconds"], 180)
                self.assertEqual(report["source_commit"], record["source"]["commit"])
                self.assertEqual(report["source_archive_sha256"], record["source"]["archive_sha256"])
                self.assertEqual(report["record_version"], record["maintenance"]["record_version"])
                adapter = ROOT / "recipes" / ident / "run.py"
                self.assertEqual(report["adapter_sha256"], hashlib.sha256(adapter.read_bytes()).hexdigest())
                for key in ("source_commit", "adapter_sha256", "record_version"):
                    self.assertEqual(verified[key], report[key])
                self.assertEqual(verified["verified_hub_commit"], summary["hub_commit"])
                self.assertEqual(verified["workflow_run_id"], "39097136411")
                self.assertEqual(verified["elapsed_steps"], steps)
                self.assertFalse(verified["physical_gpu_used"])
                self.assertEqual(evidence["level"], "task_complete")
                self.assertEqual(evidence["environment"]["packages"], environment["packages"])
                proof_url = ("https://raw.githubusercontent.com/Superfast-Robotics/robot-skill-hub/"
                             + TRANSPORT_PROOF_COMMIT + "/evidence/runtime/panda-transport-39097136411/manifest.json")
                self.assertIn(proof_url, evidence["artifacts"])
                self.assertIsNone(evidence["contributor_reported"])

    def test_failed_stacking_attempt_remains_explicit_without_success_promotion(self):
        manifest_bytes = (STACKING_PROOF / "manifest.json").read_bytes()
        self.assertEqual(hashlib.sha256(manifest_bytes).hexdigest(),
                         "5812c7e0daf44da92f0250b65bdc86236b7d04e5283071b7c01276458735b4e7")
        manifest = json.loads(manifest_bytes)
        self.assertEqual(manifest["task_outcome"], "failed")
        self.assertEqual(manifest["successful_tasks"], 0)
        self.assertTrue(manifest["provenance_verified"])
        self.assertTrue(manifest["provider_digest_verified"])
        self.assertEqual(manifest["requested_skills"], [STACKING_ID])
        for relative, digest in manifest["files_sha256"].items():
            self.assertEqual(hashlib.sha256((STACKING_PROOF / relative).read_bytes()).hexdigest(), digest, relative)
        raw = json.loads((STACKING_PROOF / STACKING_ID / "report.json").read_bytes())
        result = json.loads((STACKING_PROOF / STACKING_ID / "task.stdout.txt").read_text().splitlines()[-1])
        command = json.loads((STACKING_PROOF / STACKING_ID / "task.command.json").read_bytes())
        environment = json.loads((STACKING_PROOF / STACKING_ID / "environment.json").read_bytes())
        record = json.loads((ROOT / "catalog/records" / (STACKING_ID + ".json")).read_bytes())
        self.assertEqual(raw["result"], result)
        self.assertEqual(raw["status"], "failed")
        self.assertTrue(raw["execution_performed"])
        self.assertEqual(raw["runtime_verification"], "executed")
        self.assertEqual(raw["execution"], command)
        self.assertFalse(raw["success"])
        self.assertFalse(raw["contract_matches"])
        self.assertEqual(command["exit_code"], 1)
        self.assertFalse(command["timed_out"])
        self.assertEqual(command["duration_seconds"], 5.678)
        self.assertEqual(result["reason_code"], "task_objective_not_reached")
        self.assertFalse(result["success"])
        self.assertFalse(result["terminated"])
        self.assertFalse(result["truncated"])
        self.assertEqual(result["elapsed_steps"], 176)
        self.assertEqual(result["max_episode_steps"], 1000)
        self.assertEqual(raw["record_version"], record["maintenance"]["record_version"])
        self.assertEqual(raw["source_commit"], record["source"]["commit"])
        self.assertEqual(raw["adapter_sha256"], hashlib.sha256((ROOT / "recipes" / STACKING_ID / "run.py").read_bytes()).hexdigest())
        evidence = record["evidence"]
        self.assertEqual(evidence["level"], "import_verified")
        self.assertEqual(evidence["runtime_verification"], "import_verified")
        self.assertEqual(evidence["environment"]["packages"], environment["packages"])
        self.assertTrue(all(combination["status"] == "source_reviewed" for combination in record["compatibility"]))
        attempt = evidence["hub_verification"]["last_task_attempt"]
        self.assertEqual(attempt["status"], "failed")
        self.assertEqual(attempt["verified_hub_commit"], manifest["verified_hub_commit"])
        self.assertEqual(attempt["workflow_run_id"], "39100095436")
        self.assertEqual(attempt["record_version"], raw["record_version"])
        self.assertEqual(attempt["source_commit"], raw["source_commit"])
        for key in ("success", "reason_code", "seed", "elapsed_steps", "terminated", "truncated"):
            self.assertEqual(attempt[key], result[key], key)
        self.assertEqual(attempt["exit_code"], command["exit_code"])
        self.assertEqual(attempt["timed_out"], command["timed_out"])
        proof_url = ("https://raw.githubusercontent.com/Superfast-Robotics/robot-skill-hub/"
                     + STACKING_PROOF_COMMIT + "/evidence/runtime/panda-stacking-39100095436/manifest.json")
        self.assertIn(proof_url, evidence["artifacts"])
        self.assertIsNone(evidence["contributor_reported"])

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
