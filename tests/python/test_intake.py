"""New-reference sharing scope, pin identity and local-first retry behavior."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills/find-robot-skills/scripts"))
from rshlib import intake, memories
from rshlib.core import RshError, find, inspect
from tools.build_catalog import validate_schema

HUB, PIN, DIGEST = "a" * 40, "b" * 40, "c" * 64


def skill():
    return {"id": "ros2-panda-grasp", "name": "Panda grasp", "summary": "A ROS 2 grasp action source reference.", "framework": "ros2", "kind": "community_skill",
            "capabilities": ["grasp"], "aliases": [], "robots": ["panda"],
            "source": {"repository": "https://github.com/upstream/robot", "commit": PIN, "path": "examples/grasp.cpp", "url": f"https://github.com/upstream/robot/blob/{PIN}/examples/grasp.cpp", "sha256": DIGEST, "bytes": 2000, "authors": ["Upstream authors"]},
            "license": {"spdx": "Apache-2.0", "url": f"https://github.com/upstream/robot/blob/{PIN}/LICENSE", "scope": "Example source only."},
            "artifact": {"kind": "code", "format": "cpp"}, "requirements": {"python": None, "packages": [], "hardware": ["panda"], "system": ["ROS 2"], "notes": "Inspect upstream setup."},
            "invocation": {"entrypoint": "ROS 2 action client", "notes": "Inspect upstream before hardware operation."}, "setup_url": "https://docs.ros.org/en/rolling/",
            "compatibility": [{"runtime": "ros2", "runtime_version": "unknown", "robot": "panda", "controller": "unknown", "observation": "unknown", "os": "linux"}]}


class IntakeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.file = self.root / "skill.json"
        self.file.write_text(json.dumps(skill()), encoding="utf-8")
        self.catalog = {"schema_version": "1", "hub_commit": HUB, "records": []}

    def tearDown(self):
        self.temp.cleanup()

    def policy(self, **updates):
        publication = {"public_submission_allowed": True, "allowed_skill_ids": [skill()["id"]], "allowed_new_skill_ids": [skill()["id"]], "allowed_paths": ["catalog/intake/" + skill()["id"] + ".json"]}
        publication.update(updates)
        (self.root / ".robot-skill-hub.json").write_text(json.dumps({"publication": publication}), encoding="utf-8")

    def register(self, **kwargs):
        return intake.register(self.catalog, self.file, self.root, contributor="Test agent", **kwargs)

    def test_missing_or_patch_only_scope_saves_local_and_never_calls_api(self):
        for configure in (False, True):
            if configure:
                self.policy(allowed_new_skill_ids=[])
            with mock.patch.object(intake.contributions, "api_configuration", side_effect=AssertionError("No network or token access")):
                result = self.register()
            self.assertEqual(result["status"], "local_saved")
            self.assertFalse(result["network_performed"])
            bundle = json.loads(Path(result["bundle_path"]).read_text())
            self.assertFalse(bundle["publication"]["public_submission_allowed"])

    def test_explicit_new_id_scope_and_token_submit_only_the_supplied_record(self):
        self.policy()
        with mock.patch.object(intake.contributions, "api_configuration", return_value=("https://api.superfastrobotics.com", "private-token-value")), mock.patch.object(intake.contributions, "request_json", return_value={"status": "submitted", "submission_id": "sub_" + "d" * 64}) as request:
            first = self.register()
            self.catalog["hub_commit"] = "e" * 40
            second = self.register()
        self.assertEqual(first["idempotency_key"], second["idempotency_key"])
        method, url, token = request.call_args.args
        self.assertEqual((method, url), ("POST", "https://api.superfastrobotics.com/v1/skills"))
        payload = json.loads(request.call_args.kwargs["payload"])
        self.assertEqual(payload["skill"], skill())
        self.assertEqual(payload["base"]["hub_commit"], HUB)
        self.assertTrue(payload["publication"]["public_submission_allowed"])
        self.assertNotIn(token, Path(first["receipt_path"]).read_text())

    def test_draft_and_offline_modes_preserve_without_token_or_api(self):
        self.policy()
        for mode in ({"draft": True}, {"offline": True}):
            with mock.patch.object(intake.contributions, "api_configuration", side_effect=AssertionError("No network")):
                self.assertEqual(self.register(**mode)["status"], "local_saved")

    def test_lost_delivery_preserves_bundle_and_pretransmission_retry_identity(self):
        self.policy()
        with mock.patch.object(intake.contributions, "api_configuration", return_value=("https://api.superfastrobotics.com", "private-token-value")), mock.patch.object(intake.contributions, "request_json", side_effect=RshError("api_unavailable", "Offline")):
            with self.assertRaises(RshError):
                self.register()
        directory = self.root / ".robot-skill-hub/intake"
        bundle = json.loads((directory / "ros2-panda-grasp.json").read_text())
        receipt = json.loads((directory / "ros2-panda-grasp.receipt.json").read_text())
        self.assertEqual(receipt["status"], "sending")
        self.assertEqual(receipt["bundle_sha256"], receipt["idempotency_key"])
        self.assertEqual(bundle["base"]["hub_commit"], HUB)

    def test_non_python_artifact_content_revision_has_search_inspect_and_memory_identity(self):
        record = skill()
        del record["source"]["commit"]
        record["source"].update(revision="sha256:" + DIGEST, url="https://models.robotics.org/panda.onnx")
        record["artifact"] = {"kind": "policy", "format": "onnx"}
        intake.validate_skill(record)
        catalog = {**self.catalog, "references": {"records": [record]}}
        result = find(catalog, "panda grasp", {})["results"][0]
        self.assertFalse(result["hub_prepare"])
        self.assertEqual(result["source_commit"], "sha256:" + DIGEST)
        base = inspect(catalog, record["id"])["memory_base"]
        self.assertEqual(base, {"hub_commit": HUB, "record_version": "source-" + DIGEST, "source_commit": "sha256:" + DIGEST})
        self.assertEqual(memories.base_for(catalog, record["id"])[0], base)

    def test_unfamiliar_artifact_intake_preserves_optional_python_and_architecture(self):
        for kind, format_name in (("policy", "onnx"), ("model", "safetensors"), ("dataset", "parquet"), ("workflow", "yaml")):
            with self.subTest(kind=kind):
                record = skill()
                record["framework"], record["robots"] = "unfamiliar-runtime", ["custom-humanoid"]
                record["artifact"] = {"kind": kind, "format": format_name}
                del record["source"]["commit"]
                record["source"].update(repository="https://artifacts.robotics.org/custom-humanoid", revision="sha256:" + DIGEST,
                                        path=f"artifacts/{kind}.{format_name}", url=f"https://artifacts.robotics.org/sha256/{DIGEST}/{kind}.{format_name}")
                if kind in ("dataset", "model"):
                    record["source"]["bytes"] = (100 if kind == "dataset" else 64) * 1024 ** 3
                record["compatibility"] = [
                    {"runtime": "unfamiliar-runtime", "runtime_version": "1.2", "robot": "custom-humanoid", "controller": "joint-target", "observation": "depth", "os": "linux", "python": "3.11", "architecture": "arm64"},
                    {"runtime": "another-runtime", "runtime_version": "2", "robot": "custom-quadruped", "controller": "torque", "observation": "state", "os": "linux", "python": "3.10", "architecture": "x86_64"}]
                self.file.write_text(json.dumps(record), encoding="utf-8")
                with mock.patch.object(intake.contributions, "api_configuration", side_effect=AssertionError("Drafts require no credential")):
                    saved = self.register(draft=True)
                stored = json.loads(Path(saved["bundle_path"]).read_text())
                self.assertEqual(stored["skill"], record)
                self.assertFalse(saved["network_performed"])
                catalog = {**self.catalog, "references": {"records": [record]}}
                exact = {"runtime": "unfamiliar-runtime", "robot": "custom-humanoid", "python": "3.11", "architecture": "arm64"}
                found = find(catalog, "grasp", exact)
                self.assertEqual(found["total"], 1)
                self.assertFalse(found["results"][0]["hub_prepare"])
                self.assertEqual(find(catalog, "grasp", {**exact, "architecture": "x86_64"})["total"], 0)
                self.assertEqual(find(catalog, "grasp", {**exact, "python": "3.10"})["total"], 0)
                self.assertEqual(inspect(catalog, record["id"])["memory_base"]["source_commit"], "sha256:" + DIGEST)

    def test_declared_source_size_is_a_positive_exact_json_integer(self):
        record = skill()
        record["source"]["bytes"] = 2 ** 53 - 1
        intake.validate_skill(record)
        for count in (0, True, 1.5, 2 ** 53):
            record["source"]["bytes"] = count
            with self.subTest(count=count), self.assertRaises(RshError) as raised:
                intake.validate_skill(record)
            self.assertEqual(raised.exception.result["reason_code"], "invalid_source")

    def test_optional_compatibility_fields_retain_unknowns_without_relaxing_structure(self):
        schema = json.loads((ROOT / "schemas/intake.schema.json").read_text(encoding="utf-8"))
        for extra in ({"python": "3.11"}, {"architecture": "arm64"}, {"python": "unknown", "architecture": "unknown"}):
            record = skill()
            record["compatibility"][0].update(extra)
            intake.validate_skill(record)
            validate_schema(record["compatibility"][0], schema["$defs"]["compatibility"], schema)
            catalog = {**self.catalog, "references": {"records": [record]}}
            if extra.get("python") == "unknown":
                self.assertEqual(find(catalog, "grasp", {"python": "3.11"})["total"], 0)
        for field, value in (("python", None), ("architecture", []), ("python", ""), ("architecture", " "), ("python", "3.11\n"), ("architecture", "x" * 121)):
            record = skill()
            record["compatibility"][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(RshError):
                intake.validate_skill(record)
        record = skill()
        record["compatibility"][0].update(python="3.11", architecture="arm64")
        del record["compatibility"][0]["runtime"]
        with self.assertRaises(RshError):
            intake.validate_skill(record)

    def test_explicit_refresh_base_changes_identity_after_inspection(self):
        self.policy()
        self.register(draft=True)
        self.catalog["hub_commit"] = "e" * 40
        result = self.register(draft=True, refresh_base=True)
        self.assertEqual(json.loads(Path(result["bundle_path"]).read_text())["base"]["hub_commit"], "e" * 40)

    def test_generated_reference_cannot_smuggle_a_runtime_or_file_write_claim(self):
        record = skill()
        record["compatibility"][0].update(python="3.11", architecture="arm64")
        setup_url = record.pop("setup_url")
        record["license"]["verified"] = False
        record["compatibility"][0]["status"] = "contributor_reported"
        record.update(access={"mode": "source_reference", "hub_prepare": False, "instructions": "Inspect pinned upstream source before use.", "setup_url": setup_url},
                      evidence={"level": "contributor_reported", "runtime_verification": "not_run", "checked_at": "2026-10-18", "inspection": "Only data structure checked."},
                      maintenance={"record_version": "intake-123", "last_checked": "2026-10-18", "upstream_status": "contributor_reported"})
        intake.validate_published_reference(record)
        self.assertEqual(record["compatibility"][0]["python"], "3.11")
        self.assertEqual(record["compatibility"][0]["architecture"], "arm64")
        record["evidence"]["runtime_verification"] = "task_complete"
        with self.assertRaises(RshError):
            intake.validate_published_reference(record)

    def test_invalid_metadata_cannot_expand_verification_or_include_credentials(self):
        mutations = [lambda r: r.update(evidence={"level": "task_complete"}), lambda r: r.update(access={"hub_prepare": True}),
                     lambda r: r["source"].update(path="../private"), lambda r: r["source"].update(url="https://127.0.0.1/private"),
                     lambda r: r["source"].update(url="https://github.com/upstream/robot/blob/main/grasp.cpp"), lambda r: r["source"].update(revision="sha256:" + DIGEST)]
        for mutate in mutations:
            record = skill()
            mutate(record)
            with self.assertRaises(RshError):
                intake.validate_skill(record)
        record = skill()
        record["summary"] = "rsh_" + "x" * 43
        value = {"schema_version": "1", "base": {"hub_commit": HUB}, "skill": record, "attribution": {"contributor_label": "Agent", "preserve_upstream_attribution": True}, "publication": {"public_submission_allowed": True}}
        with self.assertRaises(RshError):
            intake.validate_bundle(value)

    def test_automatic_storage_rejects_symlink_escape(self):
        with tempfile.TemporaryDirectory() as outside:
            try:
                (self.root / ".robot-skill-hub").symlink_to(outside, target_is_directory=True)
            except OSError:
                self.skipTest("Symlink creation requires a Windows privilege on this host.")
            with self.assertRaises(RshError) as raised:
                self.register(draft=True)
            self.assertEqual(raised.exception.result["reason_code"], "intake_path_escape")
            self.assertEqual(list(Path(outside).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
