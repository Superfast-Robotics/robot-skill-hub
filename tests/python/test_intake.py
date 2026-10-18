"""New-reference sharing scope, pin identity and local-first retry behavior."""
from contextlib import redirect_stdout
import hashlib
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
sys.path.insert(0, str(ROOT / "skills/find-robot-skills/scripts"))
import rsh
from rshlib import intake, memories, remote_catalog
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

    def cli_arguments(self):
        path = self.root / "catalog.json"
        path.write_text(json.dumps(self.catalog), encoding="utf-8")
        return ["--catalog", str(path), "register", str(self.file), "--project", str(self.root),
                "--contributor=Test agent", "--json"]

    def cli_result(self, arguments):
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = rsh.main(arguments)
        return code, json.loads(stdout.getvalue())

    def saved_without_token(self):
        self.policy()
        with mock.patch.dict(os.environ, {"RSH_TELEMETRY": "off"}, clear=True), mock.patch.object(
                intake.contributions, "request_json", side_effect=AssertionError("No automatic delivery")):
            code, result = self.cli_result(self.cli_arguments())
        self.assertEqual((0, "local_saved", "missing_submission_token"), (code, result["status"], result["reason_code"]))
        arguments = result["delivery_recovery"]["register_args"]
        self.assertEqual(str(self.root / ".robot-skill-hub.json"), arguments[arguments.index("--policy") + 1])
        return result

    def test_native_cli_missing_token_keeps_durable_identity_and_safe_explicit_recovery(self):
        self.policy()
        policy = self.root / "separate policy.json"
        (self.root / ".robot-skill-hub.json").replace(policy)
        self.cli_arguments()
        environment = {key: value for key, value in os.environ.items() if not key.upper().startswith("RSH_")}
        environment.update(RSH_TELEMETRY="off", RSH_CACHE_DIR=str(self.root / "cache"),
                           RSH_API_URL="https://environment.example.org", PYTHONDONTWRITEBYTECODE="1")
        process = subprocess.run([sys.executable, "-B", str(ROOT / "skills/find-robot-skills/scripts/rsh.py"),
            "--catalog", "catalog.json", "register", "skill.json", "--project", ".", "--contributor=--Agent label",
            "--policy", policy.name, "--output", "saved packet.json", "--api-url", "https://selected.example.org/pilot/", "--json"],
            cwd=self.root, env=environment, input=b"", capture_output=True, timeout=10)
        self.assertEqual(0, process.returncode, (process.stdout + process.stderr).decode("utf-8", "replace"))
        result = json.loads(process.stdout)
        self.assertEqual(("local_saved", "missing_submission_token", "continue_user_task"),
                         (result["status"], result["reason_code"], result["next_action"]))
        self.assertFalse(result["network_performed"])
        path = self.root / "saved packet.json"
        bundle = json.loads(path.read_bytes())
        digest = hashlib.sha256(intake.contributions.canonical_bytes(bundle)).hexdigest()
        self.assertEqual(str(path), result["bundle_path"])
        self.assertEqual((digest, digest), (result["bundle_sha256"], result["idempotency_key"]))
        self.assertFalse(path.with_name("saved packet.receipt.json").exists())
        recovery = result["delivery_recovery"]
        self.assertFalse(recovery["automatic_retry"])
        self.assertEqual("RSH_SUBMISSION_TOKEN_FILE", recovery["credential_setup"]["token_file_environment"])
        self.assertIn("operator-issued scoped Hub token", recovery["credential_setup"]["message"])
        self.assertIn("private one-line UTF-8 file", recovery["credential_setup"]["message"])
        self.assertEqual("https://hub.superfastrobotics.com/new-skills.md", recovery["documentation_url"])
        self.assertEqual(["register", str(self.file), "--project", str(self.root), "--contributor=--Agent label",
            "--output", str(path), "--expected-bundle-sha256", digest, "--api-url", "https://selected.example.org/pilot",
            "--policy", str(policy), "--json"], recovery["register_args"])

    def test_returned_cli_retry_delivers_exact_saved_base_and_identity_without_catalog_read_or_rewrite(self):
        saved = self.saved_without_token()
        path = Path(saved["bundle_path"])
        original = path.read_bytes()
        self.catalog["hub_commit"] = "e" * 40
        self.cli_arguments()  # The original selector now describes a later generation.
        with mock.patch.dict(os.environ, {"RSH_SUBMISSION_TOKEN": "test-scoped-token-0123456789-abcdef"}, clear=True), \
                mock.patch.object(rsh, "load_discovery", side_effect=AssertionError("No catalog read")), \
                mock.patch.object(remote_catalog, "current_catalog", side_effect=AssertionError("No catalog request")), \
                mock.patch.object(socket, "getaddrinfo", side_effect=AssertionError("No DNS")), \
                mock.patch.object(intake.contributions, "request_json", return_value={"status": "submitted", "submission_id": "sub_" + "d" * 64}) as request:
            code, result = self.cli_result(saved["delivery_recovery"]["register_args"])
        self.assertEqual((0, "submitted"), (code, result["status"]))
        self.assertEqual(1, request.call_count)
        self.assertEqual(("POST", "https://api.superfastrobotics.com/v1/skills"), request.call_args.args[:2])
        self.assertEqual(HUB, json.loads(request.call_args.kwargs["payload"])["base"]["hub_commit"])
        self.assertEqual(intake.contributions.canonical_bytes(json.loads(original)), request.call_args.kwargs["payload"])
        self.assertEqual(saved["idempotency_key"], request.call_args.kwargs["idempotency_key"])
        self.assertEqual(original, path.read_bytes())

    def test_guarded_cli_retry_refuses_changed_inputs_selection_or_base_before_write_or_credentials(self):
        saved = self.saved_without_token()
        path = Path(saved["bundle_path"])
        original = path.read_bytes()
        source = self.file.read_bytes()
        args = saved["delivery_recovery"]["register_args"]
        cases = ["malformed_digest", "wrong_digest", "source", "contributor", "output", "saved_base", "missing_bundle", "refresh_base"]
        for case in cases:
            with self.subTest(case=case):
                path.write_bytes(original)
                self.file.write_bytes(source)
                arguments = list(args)
                expected = "intake_bundle_changed"
                if case in ("malformed_digest", "wrong_digest"):
                    arguments[arguments.index("--expected-bundle-sha256") + 1] = "bad" if case == "malformed_digest" else "0" * 64
                    if case == "malformed_digest":
                        expected = "invalid_intake_bundle_sha256"
                elif case == "source":
                    value = json.loads(source)
                    value["source"]["bytes"] += 1
                    self.file.write_text(json.dumps(value), encoding="utf-8")
                elif case == "contributor":
                    arguments[arguments.index("--contributor=Test agent")] = "--contributor=Different agent"
                elif case == "output":
                    arguments[arguments.index("--output") + 1] = str(self.root / "different.json")
                elif case == "saved_base":
                    value = json.loads(original)
                    value["base"]["hub_commit"] = "e" * 40
                    path.write_text(json.dumps(value), encoding="utf-8")
                elif case == "missing_bundle":
                    path.unlink()
                elif case == "refresh_base":
                    arguments.append("--refresh-base")
                    expected = "invalid_arguments"
                before = path.read_bytes() if path.exists() else None
                with mock.patch.object(intake, "_write", side_effect=AssertionError("No writes")), \
                        mock.patch.object(intake.contributions, "api_configuration", side_effect=AssertionError("No credentials")), \
                        mock.patch.object(intake.contributions, "request_json", side_effect=AssertionError("No HTTP")), \
                        mock.patch.object(rsh, "load_discovery", side_effect=AssertionError("No catalog read")), \
                        mock.patch.object(remote_catalog, "current_catalog", side_effect=AssertionError("No catalog request")):
                    code, result = self.cli_result(arguments)
                self.assertEqual((2, expected), (code, result["reason_code"]))
                self.assertEqual(before, path.read_bytes() if path.exists() else None)
                self.assertFalse((self.root / "different.json").exists())

    def test_guarded_cli_retry_rechecks_revoked_scope_without_rewriting_the_allowed_packet(self):
        saved = self.saved_without_token()
        path = Path(saved["bundle_path"])
        original = path.read_bytes()
        self.policy(public_submission_allowed=False)
        with mock.patch.object(intake, "_write", side_effect=AssertionError("No writes")), \
                mock.patch.object(intake.contributions, "api_configuration", side_effect=AssertionError("No credentials")), \
                mock.patch.object(intake.contributions, "request_json", side_effect=AssertionError("No HTTP")):
            code, result = self.cli_result(saved["delivery_recovery"]["register_args"])
        self.assertEqual((0, "local_saved", "sharing_not_allowed"), (code, result["status"], result["reason_code"]))
        self.assertEqual("continue_user_task", result["next_action"])
        self.assertFalse(result["public_submission_allowed"])
        self.assertFalse(result["network_performed"])
        self.assertNotIn("delivery_recovery", result)
        self.assertEqual(saved["idempotency_key"], result["idempotency_key"])
        self.assertEqual(original, path.read_bytes())
        self.assertTrue(json.loads(original)["publication"]["public_submission_allowed"])

    def test_missing_token_recovery_does_not_echo_unsafe_api_or_supplied_error_text(self):
        self.policy()
        secret = "rsh_" + "x" * 43
        for api in ("https://operator:private-value@example.org", "https://api.example.org?token=private-value",
                    "https://api.example.org/" + secret):
            with self.subTest(api=api), mock.patch.object(intake.contributions, "api_configuration",
                    side_effect=RshError("missing_submission_token", secret, next_action=secret)), \
                    mock.patch.object(intake.contributions, "request_json", side_effect=AssertionError("No HTTP")):
                result = self.register(api_url=api)
            recovery = result["delivery_recovery"]
            self.assertEqual("local_saved", result["status"])
            self.assertTrue(recovery["api_configuration_required"])
            self.assertNotIn("register_args", recovery)
            self.assertNotIn("private-value", json.dumps(result))
            self.assertNotIn(secret, json.dumps(result))

    def test_other_credential_and_transport_failures_do_not_become_missing_token_success(self):
        self.policy()
        with mock.patch.object(intake.contributions, "api_configuration",
                side_effect=RshError("invalid_submission_token_format", "Invalid fixture credential", status="blocked")):
            code, result = self.cli_result(self.cli_arguments())
        self.assertEqual((2, "invalid_submission_token_format"), (code, result["reason_code"]))
        self.assertNotIn("delivery_recovery", result)
        with mock.patch.object(intake.contributions, "api_configuration", return_value=("https://api.example.org", "fixture-placeholder")), \
                mock.patch.object(intake.contributions, "request_json", side_effect=RshError("api_unavailable", "Fixture unavailable", status="blocked")):
            code, result = self.cli_result(self.cli_arguments())
        self.assertEqual((2, "api_unavailable"), (code, result["reason_code"]))
        self.assertNotIn("delivery_recovery", result)

    def test_missing_or_patch_only_scope_saves_local_and_never_calls_api(self):
        for configure in (False, True):
            if configure:
                self.policy(allowed_new_skill_ids=[])
            with mock.patch.object(intake.contributions, "api_configuration", side_effect=AssertionError("No network or token access")):
                result = self.register()
            self.assertEqual(result["status"], "local_saved")
            self.assertFalse(result["network_performed"])
            self.assertNotIn("delivery_recovery", result)
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
