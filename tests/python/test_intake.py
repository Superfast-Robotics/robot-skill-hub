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

    def test_explicit_refresh_base_changes_identity_after_inspection(self):
        self.policy()
        self.register(draft=True)
        self.catalog["hub_commit"] = "e" * 40
        result = self.register(draft=True, refresh_base=True)
        self.assertEqual(json.loads(Path(result["bundle_path"]).read_text())["base"]["hub_commit"], "e" * 40)

    def test_generated_reference_cannot_smuggle_a_runtime_or_file_write_claim(self):
        record = skill()
        setup_url = record.pop("setup_url")
        record["license"]["verified"] = False
        record["compatibility"][0]["status"] = "contributor_reported"
        record.update(access={"mode": "source_reference", "hub_prepare": False, "instructions": "Inspect pinned upstream source before use.", "setup_url": setup_url},
                      evidence={"level": "contributor_reported", "runtime_verification": "not_run", "checked_at": "2026-10-18", "inspection": "Only data structure checked."},
                      maintenance={"record_version": "intake-123", "last_checked": "2026-10-18", "upstream_status": "contributor_reported"})
        intake.validate_published_reference(record)
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
