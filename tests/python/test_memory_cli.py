"""Local-first memory delivery and public discovery contracts, without live writes."""
import copy
from contextlib import redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from test_rsh import fixture_catalog, HUB, PIN, ROOT, SKILL
from rshlib import acquisition, contributions, discovery, memories
from rshlib.core import RshError, find, inspect


def finding(**changes):
    value = {"kind": "missing_requirement", "summary": "The solver needs an optional dependency",
             "observation": "The drawing task imports an optional package before creating its scene.",
             "resolution": "Install the documented optional parser in the isolated environment.",
             "environment": {"runtime": "fixture", "robot": "panda", "python": "3.10", "package.optional_parser": "1.0"},
             "evidence": {"level": "contributor_reported", "command": "python example.py",
                          "result": "A minimal import reproduction failed before scene creation.", "reported_by": "submitter"}}
    value.update(changes)
    return value


def reference_catalog():
    catalog = fixture_catalog()
    catalog["references"] = {"schema_version": "1", "records": [{"id": "pybullet-ik", "name": "PyBullet inverse kinematics",
                "summary": "Move an arm using inverse kinematics", "framework": "pybullet", "capabilities": ["kinematics"],
                "source": {"commit": "d" * 40, "sha256": "e" * 64, "url": "https://example.test/pinned-source"}}]}
    return catalog


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.input = self.root / "finding.json"
        self.write_finding(finding())
        self.env = mock.patch.dict(os.environ, {"RSH_SUBMISSION_TOKEN": "test-scoped-token-0123456789-abcdef", "RSH_API_URL": "https://api.example.test"})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def write_finding(self, value):
        self.input.write_text(json.dumps(value), encoding="utf-8")

    def policy(self, **updates):
        value = {"memory": {"public_save_allowed": True, "allowed_skill_ids": ["fixture-pick"],
                            "allowed_kinds": ["missing_requirement"]}}
        value["memory"].update(updates)
        (self.project / ".robot-skill-hub.json").write_text(json.dumps(value))

    def response(self, method, url, token, **kwargs):
        payload = json.loads(kwargs["payload"])
        return {"status": "stored", "memory_id": "mem_" + "1" * 64,
                "fingerprint": memories.fingerprint(payload), "pr_url": "https://github.com/example/hub/pull/1",
                "content_sha256": "e" * 64}

    def save(self, catalog=None):
        return memories.save(catalog or fixture_catalog(), "fixture-pick", self.project, self.input)

    def cli_result(self, args, cli=None):
        cli = cli or runpy.run_path(str(SKILL / "scripts/rsh.py"), run_name="rsh_memory_test")
        output = io.StringIO()
        with redirect_stdout(output):
            code = cli["main"](args)
        return code, json.loads(output.getvalue())

    def acquire_reference(self):
        catalog = reference_catalog()
        record = catalog["references"]["records"][0]
        body = b"# Synthetic source fixture; never executed.\n"
        record["source"].update(repository="https://github.com/example/robot", path="example.py",
            url="https://github.com/example/robot/blob/" + "d" * 40 + "/example.py",
            sha256=hashlib.sha256(body).hexdigest(), bytes=len(body))
        record["license"] = {"spdx": "NOASSERTION", "verified": False, "scope": "Synthetic fixture terms remain unresolved."}
        record["access"] = {"mode": "source_reference", "hub_prepare": False}
        with mock.patch.object(acquisition, "_download", return_value=body):
            result = acquisition.fetch_source(catalog, record["id"], self.project)
        return catalog, result

    def test_source_manifest_save_and_recall_preserve_used_source_without_latest_discovery(self):
        catalog, acquired = self.acquire_reference()
        self.write_finding(finding(environment={"runtime": "pybullet", "robot": "kuka"}))
        self.policy(allowed_skill_ids=["pybullet-ik"])
        newer = copy.deepcopy(catalog)
        newer["hub_commit"] = "f" * 40
        newer["references"]["records"][0]["source"].update(commit="a" * 40, sha256="b" * 64)
        cli = runpy.run_path(str(SKILL / "scripts/rsh.py"), run_name="rsh_source_context_test")
        with mock.patch.object(cli["remote_catalog"], "selected_catalog", return_value=newer) as latest, \
                mock.patch.dict(cli["execute"].__globals__, {"load_discovery": mock.Mock(side_effect=AssertionError("latest discovery"))}), \
                mock.patch.object(contributions, "api_configuration", return_value=("https://api.example.test", "fixture-token")), \
                mock.patch.object(contributions, "request_json", side_effect=self.response) as post:
            code, saved = self.cli_result([*acquired["save_args"], "--finding", str(self.input), "--json"], cli)
            self.assertEqual((0, "stored"), (code, saved["status"]))
            latest.assert_not_called()
            self.assertEqual(post.call_count, 1)
            sent = json.loads(post.call_args.kwargs["payload"])
            self.assertEqual(acquired["base"], sent["base"])
        published = {**sent, "memory_id": "mem_" + "1" * 64, "fingerprint": saved["fingerprint"],
                     "content_sha256": "f" * 64, "curation": "maintainer_merged", "interpretation": "data_only"}
        index = self.root / "original-source-findings.json"
        index.write_text(json.dumps({"schema_version": "1", "records": [published]}), encoding="utf-8")
        with mock.patch.object(cli["remote_catalog"], "selected_catalog", side_effect=AssertionError("latest record")), \
                mock.patch.dict(cli["execute"].__globals__, {"load_discovery": mock.Mock(side_effect=AssertionError("latest discovery"))}):
            code, recalled = self.cli_result([*acquired["memories_args"], "--offline", "--index", str(index),
                                              "--runtime", "pybullet", "--robot", "kuka", "--json"], cli)
        self.assertEqual((0, 1), (code, recalled["total"]))
        self.assertEqual(acquired["base"], recalled["base"])
        self.assertEqual(acquired["base"], recalled["results"][0]["base"])

    def test_invalid_source_manifest_stops_before_outbox_credentials_or_network(self):
        _, acquired = self.acquire_reference()
        Path(acquired["source_file"]).write_bytes(b"changed fixture")
        with mock.patch.object(contributions, "api_configuration") as credentials, \
                mock.patch.object(contributions, "request_json") as post:
            code, result = self.cli_result([*acquired["save_args"], "--finding", str(self.input), "--json"])
        self.assertEqual((0, "skipped", False), (code, result["status"], result["network_performed"]))
        self.assertEqual("source_cache_conflict", result["reason_code"])
        self.assertFalse((self.project / ".robot-skill-hub/outbox").exists())
        credentials.assert_not_called()
        post.assert_not_called()

    def test_source_manifest_refuses_a_conflicting_project_lock(self):
        _, acquired = self.acquire_reference()
        lock = self.project / ".robot-skill-hub/locks/pybullet-ik.json"
        lock.parent.mkdir(parents=True)
        lock.write_text(json.dumps({"skill_id": "pybullet-ik", "hub_commit": "f" * 40,
                                    "record_version": "different-version", "source_commit": "a" * 40}), encoding="utf-8")
        with mock.patch.object(contributions, "api_configuration") as credentials, \
                mock.patch.object(contributions, "request_json") as post:
            _, result = self.cli_result([*acquired["save_args"], "--finding", str(self.input), "--json"])
        self.assertEqual("source_context_conflict", result["reason_code"])
        self.assertFalse(result["network_performed"])
        self.assertFalse((self.project / ".robot-skill-hub/outbox").exists())
        credentials.assert_not_called()
        post.assert_not_called()

    def test_source_manifest_requires_project_and_refuses_competing_catalog(self):
        with mock.patch.object(acquisition, "catalog_from_manifest") as selector:
            for args in (["memories", "pybullet-ik", "--source-manifest", "not-read.json", "--json"],
                         ["save", "pybullet-ik", "--project", str(self.project), "--source-manifest", "not-read.json",
                          "--catalog", "also-not-read.json", "--finding", str(self.input), "--json"]):
                _, result = self.cli_result(args)
                self.assertEqual("invalid_arguments", result["reason_code"])
                self.assertFalse(result["network_performed"])
            selector.assert_not_called()

    def test_patch_permission_and_token_do_not_grant_memory_sharing(self):
        (self.project / ".robot-skill-hub.json").write_text(json.dumps({"publication": {"public_submission_allowed": True}}))
        # This file is deliberately outside the explicit finding; the command must not scan it.
        (self.project / "private-project-data.txt").write_text("private research data")
        with mock.patch.object(contributions, "request_json") as network:
            result = self.save()
        self.assertEqual(result["status"], "local_saved")
        self.assertFalse(result["network_performed"])
        self.assertNotIn("delivery_recovery", result)
        network.assert_not_called()
        payload = Path(result["finding_path"]).read_text()
        self.assertNotIn("private research data", payload)
        self.assertFalse(json.loads(payload)["payload"]["publication"]["public_submission_allowed"])

    def test_both_explicit_scopes_and_token_are_required(self):
        for updates in ({"allowed_kinds": []}, {"allowed_skill_ids": []}, {"public_save_allowed": False}):
            with self.subTest(updates=updates):
                self.policy(**updates)
                with mock.patch.object(contributions, "request_json") as network:
                    result = self.save()
                self.assertEqual(result["status"], "local_saved")
                self.assertNotIn("delivery_recovery", result)
                network.assert_not_called()
        self.policy()
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(contributions, "request_json") as network:
            result = memories.flush(self.project)
        self.assertFalse(result["network_performed"])
        network.assert_not_called()
        self.assertFalse(memories.allowed({"memory": {"public_save_allowed": True}}, "fixture-pick", "missing_requirement"))

    def test_missing_token_recovery_preserves_local_finding_and_requires_explicit_flush(self):
        self.policy()
        with mock.patch.dict(os.environ, {"RSH_TELEMETRY": "off"}, clear=True), mock.patch.object(contributions, "request_json") as network:
            first = self.save()
            path = Path(first["finding_path"])
            original = path.read_bytes()
            self.assertEqual(first["status"], "local_saved")
            self.assertEqual(first["reason_code"], "missing_submission_token")
            self.assertEqual(first["next_action"], "continue_user_task")
            self.assertFalse(first["network_performed"])
            recovery = first["delivery_recovery"]
            self.assertEqual(recovery["credential_setup"]["token_file_environment"], "RSH_SUBMISSION_TOKEN_FILE")
            self.assertEqual(recovery["credential_setup"]["token_environment"], "RSH_SUBMISSION_TOKEN")
            self.assertIn("operator-issued scoped Hub token", recovery["credential_setup"]["message"])
            self.assertIn("private one-line UTF-8 file", recovery["credential_setup"]["message"])
            self.assertEqual(recovery["documentation_url"], "https://hub.superfastrobotics.com/memory.md")
            self.assertFalse(recovery["automatic_retry"])
            self.assertEqual(recovery["flush_args"], ["flush", "--project", str(self.project.resolve()), "--fingerprint", first["fingerprint"], "--limit", "1",
                                                      "--api-url", "https://api.superfastrobotics.com", "--json"])
            with mock.patch.dict(os.environ, {"RSH_SUBMISSION_TOKEN": "test-scoped-token-0123456789-abcdef"}), mock.patch.object(
                    contributions, "submission_token", side_effect=AssertionError("Duplicate save must not read a token")):
                second = self.save()
                self.policy(public_save_allowed=False)
                revoked = self.save()
            self.assertEqual(second["reason_code"], "unchanged_finding_already_saved")
            self.assertEqual(second["fingerprint"], first["fingerprint"])
            self.assertEqual(second["delivery_recovery"], recovery)
            self.assertNotIn("delivery_recovery", revoked)
            self.assertEqual(path.read_bytes(), original)
            network.assert_not_called()
        self.policy()
        with mock.patch.object(contributions, "request_json", side_effect=self.response) as network:
            flushed = memories.flush(self.project)
        self.assertEqual(flushed["results"][0]["status"], "stored")
        self.assertEqual(network.call_count, 1)
        self.assertEqual(network.call_args.kwargs["idempotency_key"], first["fingerprint"])
        self.assertEqual(json.loads(network.call_args.kwargs["payload"])["base"], json.loads(original)["payload"]["base"])

    def test_missing_token_recovery_keeps_explicit_policy_and_selected_api(self):
        self.policy()
        policy = self.root / "separate policy.json"
        (self.project / ".robot-skill-hub.json").replace(policy)
        with mock.patch.dict(os.environ, {"RSH_API_URL": "https://environment.example.test"}, clear=True), mock.patch.object(contributions, "request_json") as network:
            result = memories.save(fixture_catalog(), "fixture-pick", self.project, self.input,
                                   policy_path=policy, api_url="https://selected.example.test/pilot/")
        self.assertEqual(result["delivery_recovery"]["flush_args"], [
            "flush", "--project", str(self.project.resolve()), "--fingerprint", result["fingerprint"], "--limit", "1", "--api-url", "https://selected.example.test/pilot",
            "--policy", str(policy.resolve()), "--json"])
        network.assert_not_called()
        with mock.patch.dict(os.environ, {"RSH_API_URL": "https://environment.example.test"}, clear=True):
            recovery = memories.missing_token_recovery(self.project, result["fingerprint"])
        self.assertIn("https://environment.example.test", recovery["flush_args"])

    def test_cli_missing_token_save_returns_recovery_without_prompts(self):
        self.policy()
        catalog = self.root / "catalog.json"
        catalog.write_text(json.dumps(fixture_catalog()), encoding="utf-8")
        environment = {key: value for key, value in os.environ.items()
                       if key not in {"RSH_SUBMISSION_TOKEN", "RSH_SUBMISSION_TOKEN_FILE", "RSH_API_URL"}}
        environment.update(RSH_TELEMETRY="off", PYTHONDONTWRITEBYTECODE="1")
        executed = subprocess.run([
            sys.executable, "-B", str(SKILL / "scripts/rsh.py"), "save", "fixture-pick", "--project", str(self.project),
            "--finding", str(self.input), "--catalog", str(catalog), "--json"],
            env=environment, input="", capture_output=True, text=True, timeout=10)
        self.assertEqual(executed.returncode, 0, executed.stderr)
        result = json.loads(executed.stdout)
        self.assertEqual(result["status"], "local_saved")
        self.assertEqual(result["reason_code"], "missing_submission_token")
        self.assertEqual(result["next_action"], "continue_user_task")
        self.assertFalse(result["network_performed"])
        self.assertEqual(result["delivery_recovery"]["flush_args"], [
            "flush", "--project", str(self.project.resolve()), "--fingerprint", result["fingerprint"], "--limit", "1", "--api-url", "https://api.superfastrobotics.com", "--json"])
        self.assertTrue(Path(result["finding_path"]).is_file())

    def test_missing_token_recovery_does_not_echo_unsafe_endpoint_or_error_text(self):
        self.policy()
        secret = "Bearer " + "x" * 40
        error = RshError("missing_submission_token", secret, next_action=secret)
        with mock.patch.object(contributions, "api_configuration", side_effect=error), mock.patch.object(contributions, "request_json") as network:
            result = memories.save(fixture_catalog(), "fixture-pick", self.project, self.input,
                                   api_url="https://operator:do-not-echo@example.test")
        recovery = result["delivery_recovery"]
        self.assertTrue(recovery["api_configuration_required"])
        self.assertNotIn("flush_args", recovery)
        self.assertNotIn("do-not-echo", json.dumps(result))
        self.assertNotIn(secret, json.dumps(result))
        self.assertEqual(result["next_action"], "continue_user_task")
        network.assert_not_called()

    def test_authorized_save_once_then_unchanged_head_or_label_writes_nothing(self):
        self.policy()
        with mock.patch.object(contributions, "request_json", side_effect=self.response) as network:
            first = self.save()
            path = Path(first["finding_path"])
            original = path.read_bytes()
            changed = fixture_catalog()
            changed["hub_commit"] = "c" * 40
            self.write_finding(finding(attribution={"contributor_label": "another self-reported label", "preserve_upstream_attribution": True}))
            second = self.save(changed)
        self.assertEqual(network.call_count, 1)
        self.assertEqual(first["status"], "stored")
        self.assertEqual(second["fingerprint"], first["fingerprint"])
        self.assertEqual(path.read_bytes(), original)
        self.assertNotIn("test-scoped-token", original.decode())
        wire = json.loads(network.call_args.kwargs["payload"])
        self.assertTrue(wire["publication"]["public_submission_allowed"])
        self.assertEqual(network.call_args.kwargs["timeout"], memories.SEND_TIMEOUT)

    def test_interrupted_save_retries_only_on_explicit_flush_with_identical_payload(self):
        self.policy()
        calls = []
        def interrupted(method, url, token, **kwargs):
            calls.append((kwargs["payload"], kwargs["idempotency_key"]))
            if len(calls) == 1:
                raise RshError("api_unavailable", "Lost response")
            return self.response(method, url, token, **kwargs)
        with mock.patch.object(contributions, "request_json", side_effect=interrupted):
            first = self.save()
            self.assertEqual(first["status"], "local_saved")
            self.save()
            self.assertEqual(len(calls), 1)
            self.policy(public_save_allowed=False)
            memories.flush(self.project)
            self.assertEqual(len(calls), 1)
            self.policy()
            result = memories.flush(self.project)
        self.assertEqual(calls[0], calls[1])
        self.assertEqual(result["results"][0]["status"], "stored")

    def test_safe_api_rejection_details_survive_without_raw_body_or_automatic_rebase(self):
        self.policy()
        diagnostic = {"reason_code": "stale_record", "message": "The pinned catalog commit does not contain this record.",
                      "next_action": "inspect_original_catalog_base"}
        raw_error = {**diagnostic, "payload": {"token": "should-never-be-copied"}, "raw_body": "private submitted observation"}
        error = RshError("submission_conflict", "Submission API rejected the request.", api_error=raw_error, http_status=409)
        with mock.patch.object(contributions, "request_json", side_effect=error) as network:
            first = self.save()
            path = Path(first["finding_path"])
            saved = json.loads(path.read_text())
            second = self.save()
        self.assertEqual(network.call_count, 1)
        self.assertEqual(first["status"], "local_saved")
        self.assertEqual(first["reason_code"], "submission_conflict")
        self.assertEqual(first["next_action"], "continue_user_task")
        self.assertEqual(first["delivery_error"], diagnostic)
        self.assertEqual(second["delivery_error"], diagnostic)
        self.assertEqual(saved["delivery"]["api_error"], diagnostic)
        self.assertEqual(saved["payload"]["base"]["hub_commit"], HUB)
        self.assertNotIn("should-never-be-copied", path.read_text())
        self.assertNotIn("private submitted observation", path.read_text())

    def test_source_version_and_environment_changes_have_distinct_identity(self):
        first = self.save()
        catalog = fixture_catalog()
        catalog["records"][0]["maintenance"]["record_version"] = "2.0.0"
        second = self.save(catalog)
        self.write_finding(finding(environment={"runtime": "fixture", "robot": "other_robot"}))
        third = self.save()
        self.assertEqual(len({r["fingerprint"] for r in (first, second, third)}), 3)

    def test_project_lock_pins_override_newer_selected_catalog(self):
        lock = self.project / ".robot-skill-hub/locks/fixture-pick.json"
        lock.parent.mkdir(parents=True)
        lock.write_text(json.dumps({"skill_id": "fixture-pick", "hub_commit": "c" * 40,
                                    "record_version": "old-project-version", "source_commit": "d" * 40}))
        result = self.save()
        saved = json.loads(Path(result["finding_path"]).read_text())["payload"]
        self.assertEqual(saved["base"], {"hub_commit": "c" * 40, "record_version": "old-project-version", "source_commit": "d" * 40})

    def test_secrets_oversized_inputs_and_arbitrary_environment_fields_are_rejected(self):
        for value in (finding(observation="Token used: ghp_" + "a" * 30),
                      finding(observation="Token used: rsh_" + "a" * 43),
                      finding(observation="Authorization: Bearer " + "x" * 30),
                      finding(environment={"runtime": "fixture", "robot": "panda", "password": "private"}),
                      finding(observation="x" * 17000)):
            self.write_finding(value)
            with self.subTest(value=value), mock.patch.object(contributions, "request_json") as network:
                with self.assertRaises(RshError):
                    self.save()
                network.assert_not_called()
        self.assertFalse((self.project / ".robot-skill-hub/memory/outbox").exists())

    def test_flush_has_a_small_explicit_delivery_budget(self):
        for number in range(4):
            self.write_finding(finding(summary=f"Missing optional parser variant {number}"))
            self.save()
        self.policy()
        with mock.patch.object(contributions, "request_json", side_effect=self.response) as network:
            result = memories.flush(self.project, limit=2)
        self.assertEqual(network.call_count, 2)
        self.assertEqual(result["processed"], 2)

    def test_recovery_selects_allowed_finding_behind_denied_queue_entry_without_glob(self):
        self.policy()
        with mock.patch.dict(os.environ, {"RSH_TELEMETRY": "off"}, clear=True), mock.patch.object(contributions, "request_json") as network:
            saved = self.save()
            network.assert_not_called()
        saved_path = Path(saved["finding_path"])
        payload = json.loads(saved_path.read_text(encoding="utf-8"))["payload"]
        for number in range(256):
            denied_finding = finding(kind="failure_observation", summary=f"A separate synthetic failure observation {number}")
            denied_payload = {**payload, **memories.normalize_finding(denied_finding)}
            if memories.fingerprint(denied_payload) < saved["fingerprint"]:
                break
        else:
            self.fail("Could not construct a lexicographically first denied fixture")
        self.write_finding(denied_finding)
        denied = memories.save(fixture_catalog(), "fixture-pick", self.project, self.input, offline=True)
        denied_path = Path(denied["finding_path"])
        denied_bytes = denied_path.read_bytes()
        self.assertLess(denied["fingerprint"], saved["fingerprint"])
        cli = runpy.run_path(str(SKILL / "scripts/rsh.py"), run_name="rsh_memory_test")
        remaining, json_mode, catalog = cli["extract_global"](saved["delivery_recovery"]["flush_args"])
        args = cli["build_parser"]().parse_args(remaining)
        self.assertTrue(json_mode)
        self.assertEqual(args.selected_fingerprint, saved["fingerprint"])
        with mock.patch.object(Path, "glob", side_effect=AssertionError("Selected flush must not enumerate the queue")), mock.patch.object(
                memories, "read_json", wraps=memories.read_json) as reads, mock.patch.object(
                contributions, "api_configuration", return_value=("https://api.superfastrobotics.com", "synthetic-credential")) as credential, mock.patch.object(
                contributions, "request_json", side_effect=self.response) as network:
            result = cli["execute"](args, catalog)
            already_stored = cli["execute"](args, catalog)
        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["results"][0]["fingerprint"], saved["fingerprint"])
        self.assertEqual(result["results"][0]["status"], "stored")
        self.assertEqual(already_stored["results"][0]["reason_code"], "finding_already_stored")
        self.assertFalse(already_stored["network_performed"])
        self.assertEqual(network.call_count, 1)
        self.assertEqual(credential.call_count, 1)
        self.assertEqual(network.call_args.kwargs["idempotency_key"], saved["fingerprint"])
        self.assertEqual(json.loads(network.call_args.kwargs["payload"])["base"], payload["base"])
        self.assertEqual([Path(call.args[0]) for call in reads.call_args_list], [saved_path, saved_path])
        self.assertEqual(denied_path.read_bytes(), denied_bytes)
        with mock.patch.object(Path, "glob", side_effect=AssertionError("Selected flush must not enumerate the queue")), mock.patch.object(
                contributions, "api_configuration", side_effect=AssertionError("Denied target must not read credentials")), mock.patch.object(
                contributions, "request_json") as network:
            blocked = memories.flush(self.project, selected_fingerprint=denied["fingerprint"])
        self.assertEqual(blocked["results"][0]["reason_code"], "memory_sharing_not_allowed")
        self.assertFalse(blocked["network_performed"])
        self.assertNotIn("delivery_recovery", blocked["results"][0])
        network.assert_not_called()

    def test_selected_flush_rejects_invalid_selectors_before_any_outbox_read(self):
        for selector in ("", "A" * 64, "a" * 63, "a" * 65, "../private", "a" * 64 + ".json", True, 1):
            with self.subTest(selector=selector), mock.patch.object(memories, "outbox_root") as outbox, mock.patch.object(
                    memories, "read_json") as reads, mock.patch.object(contributions, "api_configuration") as credential, mock.patch.object(
                    contributions, "request_json") as network:
                with self.assertRaises(RshError) as error:
                    memories.flush(self.project, selected_fingerprint=selector)
                self.assertEqual(error.exception.result["reason_code"], "invalid_memory_fingerprint")
                self.assertFalse(error.exception.result["network_performed"])
                outbox.assert_not_called()
                reads.assert_not_called()
                credential.assert_not_called()
                network.assert_not_called()

    def test_selected_flush_missing_target_never_reads_or_falls_back_to_pending_entry(self):
        saved = memories.save(fixture_catalog(), "fixture-pick", self.project, self.input, offline=True)
        self.policy()
        with mock.patch.object(Path, "glob", side_effect=AssertionError("Selected flush must not enumerate the queue")), mock.patch.object(
                memories, "read_json") as reads, mock.patch.object(contributions, "api_configuration") as credential, mock.patch.object(
                contributions, "request_json") as network:
            with self.assertRaises(RshError) as error:
                memories.flush(self.project, selected_fingerprint="0" * 64)
        self.assertNotEqual(saved["fingerprint"], "0" * 64)
        self.assertEqual(error.exception.result["reason_code"], "memory_finding_not_found")
        self.assertFalse(error.exception.result["network_performed"])
        reads.assert_not_called()
        credential.assert_not_called()
        network.assert_not_called()

    def test_selected_flush_invalid_content_or_identity_cannot_deliver(self):
        saved = memories.save(fixture_catalog(), "fixture-pick", self.project, self.input, offline=True)
        self.policy()
        path = Path(saved["finding_path"])
        entry = json.loads(path.read_text(encoding="utf-8"))
        changed = copy.deepcopy(entry)
        changed["payload"]["summary"] = "A tampered synthetic summary"
        wrong_fingerprint = {**entry, "fingerprint": "f" * 64}
        for content in ("private malformed JSON", "[]", json.dumps(changed), json.dumps(wrong_fingerprint)):
            path.write_text(content, encoding="utf-8")
            with self.subTest(content=content[:30]), mock.patch.object(Path, "glob", side_effect=AssertionError("No queue scan")), mock.patch.object(
                    contributions, "api_configuration") as credential, mock.patch.object(contributions, "request_json") as network:
                with self.assertRaises(RshError) as error:
                    memories.flush(self.project, selected_fingerprint=saved["fingerprint"])
                self.assertEqual(error.exception.result["reason_code"], "invalid_local_memory")
                self.assertFalse(error.exception.result["network_performed"])
                self.assertNotIn("private malformed", error.exception.result["message"])
                credential.assert_not_called()
                network.assert_not_called()

    def test_cli_post_response_receipt_failures_preserve_network_state_and_retry_identity(self):
        saved = memories.save(fixture_catalog(), "fixture-pick", self.project, self.input, offline=True)
        self.policy()
        path = Path(saved["finding_path"])
        original = path.read_bytes()
        real_write = memories.write_json
        for fail_pending in (False, True):
            path.write_bytes(original)
            writes = []
            def fail_receipt(target, entry):
                state = entry["delivery"]["status"]
                writes.append(state)
                if state == "stored" or fail_pending and state == "pending":
                    raise OSError("private receipt error must not appear")
                return real_write(target, entry)
            with self.subTest(fail_pending=fail_pending), mock.patch.object(Path, "glob", side_effect=AssertionError("No queue scan")), mock.patch.object(
                    memories, "write_json", side_effect=fail_receipt), mock.patch.object(
                    contributions, "api_configuration", return_value=("https://api.example.test", "synthetic-credential")), mock.patch.object(
                    contributions, "request_json", side_effect=self.response) as network:
                code, result = self.cli_result(["flush", "--project", str(self.project), "--fingerprint", saved["fingerprint"], "--json"])
            self.assertEqual(code, 0)
            self.assertTrue(result["network_performed"])
            delivered = result["results"][0]
            self.assertEqual(delivered["status"], "local_saved")
            self.assertEqual(delivered["reason_code"], "memory_receipt_persistence_failed")
            self.assertTrue(delivered["network_performed"])
            self.assertEqual(delivered["next_action"], "continue_user_task")
            self.assertEqual(writes, ["sending", "stored", "pending"])
            self.assertEqual(network.call_count, 1)
            self.assertEqual(network.call_args.kwargs["idempotency_key"], saved["fingerprint"])
            persisted = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(memories.fingerprint(persisted["payload"]), saved["fingerprint"])
            self.assertEqual(contributions.canonical_bytes(persisted["wire_payload"]), network.call_args.kwargs["payload"])
            self.assertEqual(persisted["delivery"]["status"], "sending" if fail_pending else "pending")
            if fail_pending:
                self.assertIs(delivered["local_receipt_persisted"], False)
            self.assertNotIn("private receipt error", json.dumps(result))
            self.assertNotIn("synthetic-credential", json.dumps(result))

    def test_cli_preflight_receipt_failure_performs_no_post(self):
        saved = memories.save(fixture_catalog(), "fixture-pick", self.project, self.input, offline=True)
        self.policy()
        original = Path(saved["finding_path"]).read_bytes()
        with mock.patch.object(memories, "write_json", side_effect=OSError("private preflight error")), mock.patch.object(
                contributions, "api_configuration", return_value=("https://api.example.test", "synthetic-credential")), mock.patch.object(
                contributions, "request_json") as network:
            code, result = self.cli_result(["flush", "--project", str(self.project), "--fingerprint", saved["fingerprint"], "--json"])
        self.assertEqual(code, 0)
        self.assertIs(result["network_performed"], False)
        self.assertIs(result["results"][0]["network_performed"], False)
        self.assertIs(result["results"][0]["local_receipt_persisted"], False)
        self.assertEqual(result["results"][0]["reason_code"], "memory_delivery_failed")
        self.assertEqual(Path(saved["finding_path"]).read_bytes(), original)
        self.assertNotIn("private preflight", json.dumps(result))
        network.assert_not_called()

    def test_cli_old_attempted_state_does_not_claim_current_post_without_token(self):
        saved = memories.save(fixture_catalog(), "fixture-pick", self.project, self.input, offline=True)
        self.policy()
        path = Path(saved["finding_path"])
        entry = json.loads(path.read_text(encoding="utf-8"))
        entry["delivery"] = {"status": "pending", "attempted": True}
        path.write_text(json.dumps(entry), encoding="utf-8")
        with mock.patch.dict(os.environ, {"RSH_TELEMETRY": "off"}, clear=True), mock.patch.object(contributions, "request_json") as network:
            code, result = self.cli_result(["flush", "--project", str(self.project), "--fingerprint", saved["fingerprint"], "--json"])
        self.assertEqual(code, 0)
        self.assertIs(result["network_performed"], False)
        delivered = result["results"][0]
        self.assertEqual(delivered["reason_code"], "missing_submission_token")
        self.assertIs(delivered["network_performed"], False)
        self.assertTrue(json.loads(path.read_text(encoding="utf-8"))["delivery"]["attempted"])
        self.assertIn(saved["fingerprint"], delivered["delivery_recovery"]["flush_args"])
        network.assert_not_called()

    def test_selected_policy_failure_is_not_reclassified_as_invalid_finding(self):
        saved = memories.save(fixture_catalog(), "fixture-pick", self.project, self.input, offline=True)
        (self.project / ".robot-skill-hub.json").write_text('{"memory":', encoding="utf-8")
        with mock.patch.object(contributions, "api_configuration") as credential, mock.patch.object(contributions, "request_json") as network:
            code, result = self.cli_result(["flush", "--project", str(self.project), "--fingerprint", saved["fingerprint"], "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(result["results"][0]["reason_code"], "memory_sharing_not_allowed")
        self.assertIs(result["network_performed"], False)
        credential.assert_not_called()
        network.assert_not_called()
        error = RshError("invalid_project_policy", "The project policy is unavailable.", network_performed=False)
        with mock.patch.object(memories, "policy_for", side_effect=error), mock.patch.object(contributions, "request_json") as network:
            code, result = self.cli_result(["flush", "--project", str(self.project), "--fingerprint", saved["fingerprint"], "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason_code"], "invalid_project_policy")
        self.assertIs(result["network_performed"], False)
        network.assert_not_called()

    def test_main_optional_error_keeps_known_network_and_marks_unknown_state(self):
        cli = runpy.run_path(str(SKILL / "scripts/rsh.py"), run_name="rsh_memory_test")
        cases = [(RshError("delivery_state_unavailable", "Delivery state is unavailable.", network_performed=True), True),
                 (OSError("private unexpected error must not appear"), None)]
        for error, expected_network in cases:
            def unexpected(args, location):
                contributions.request_json("POST", "https://fixture.invalid/v1/memories", "synthetic-credential",
                                           payload=b"{}", idempotency_key="a" * 64)
                raise error
            with self.subTest(error=type(error).__name__), mock.patch.dict(cli["main"].__globals__, {"execute": unexpected}), mock.patch.object(
                    contributions, "request_json", return_value={}) as network:
                code, result = self.cli_result(["flush", "--project", str(self.project), "--json"], cli=cli)
            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "skipped")
            self.assertIs(result["network_performed"], expected_network)
            self.assertEqual(network.call_count, 1)
            self.assertNotIn("private unexpected", json.dumps(result))
            self.assertNotIn("synthetic-credential", json.dumps(result))

    def test_recall_requires_exact_source_record_and_known_environment_match(self):
        base = {"hub_commit": HUB, "record_version": "1.0.0", "source_commit": PIN}
        valid = {"schema_version": "1", **memories.normalize_finding(finding()), "memory_id": "mem_" + "1" * 64,
                 "skill_id": "fixture-pick", "base": base, "publication": {"public_submission_allowed": True},
                 "content_sha256": "e" * 64, "curation": "maintainer_merged", "interpretation": "data_only",
                 "entry_url": "https://hub.superfastrobotics.com/memories/mem_" + "1" * 64 + ".json",
                 "hash_target": "entry_url",
                 "trust": "contributor_reported", "hub_validation": {"level": "structure_checked", "runtime": "not_run"},
                 "created_at": "2026-10-17T00:00:00Z"}
        variants = [valid, {**valid, "base": {**base, "source_commit": "f" * 40}},
                    {**valid, "base": {**base, "record_version": "2.0.0"}},
                    {**valid, "environment": {"runtime": "fixture", "robot": "unknown"}}]
        payload_keys = ("schema_version", "skill_id", "base", "kind", "summary", "observation", "resolution", "environment", "evidence", "attribution", "publication")
        records = [{**value, "fingerprint": memories.fingerprint({key: value[key] for key in payload_keys})} for value in variants]
        # Index membership alone must not label a draft or instruction-bearing entry as reviewed.
        records += [{**records[0], "curation": "draft"}, {**records[0], "interpretation": "agent_instructions"},
                    {**records[0], "content_sha256": "not-a-hash"}]
        index = self.root / "memories.json"
        index.write_text(json.dumps({"schema_version": "1", "records": records}))
        result = memories.query(fixture_catalog(), "fixture-pick", {"runtime": "fixture", "robot": "panda"}, index=index)
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["results"][0]["memory_id"], valid["memory_id"])

    def test_optional_save_failure_is_json_and_exit_zero_without_network(self):
        self.write_finding(finding(observation="Bearer " + "x" * 30))
        catalog = self.root / "catalog.json"
        catalog.write_text(json.dumps(fixture_catalog()))
        executed = subprocess.run([sys.executable, str(SKILL / "scripts/rsh.py"), "save", "fixture-pick", "--project", str(self.project),
                                   "--finding", str(self.input), "--catalog", str(catalog), "--offline", "--json"],
                                  input="", capture_output=True, text=True, timeout=10)
        self.assertEqual(executed.returncode, 0)
        result = json.loads(executed.stdout)
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason_code"], "potential_secret")
        self.assertFalse(result["network_performed"])

    def test_real_http_save_uses_scoped_bearer_and_one_stable_post(self):
        self.policy()
        hits = []
        test = self
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                payload = json.loads(body)
                hits.append((self.path, self.headers.get("Authorization"), self.headers.get("Idempotency-Key"), body))
                response = test.response("POST", self.path, "unused", payload=body)
                data = json.dumps(response).encode()
                self.send_response(201)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            endpoint = f"http://127.0.0.1:{server.server_port}"
            first = memories.save(fixture_catalog(), "fixture-pick", self.project, self.input, api_url=endpoint)
            second = memories.save(fixture_catalog(), "fixture-pick", self.project, self.input, api_url=endpoint)
            self.assertEqual(first["status"], "stored")
            self.assertEqual(second["status"], "stored")
            self.assertEqual(len(hits), 1)
            path, authorization, key, body = hits[0]
            self.assertEqual(path, "/v1/memories")
            self.assertEqual(authorization, "Bearer test-scoped-token-0123456789-abcdef")
            self.assertEqual(key, memories.fingerprint(json.loads(body)))
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_explicit_prepare_pin_mismatch_stops_before_preparation(self):
        catalog = self.root / "catalog.json"
        catalog.write_text(json.dumps(fixture_catalog()))
        executed = subprocess.run([sys.executable, str(SKILL / "scripts/rsh.py"), "prepare", "fixture-pick", "--project", str(self.project),
                                   "--expected-source-commit", "f" * 40, "--catalog", str(catalog), "--offline", "--json"],
                                  input="", capture_output=True, text=True, timeout=10)
        self.assertNotEqual(executed.returncode, 0)
        self.assertEqual(json.loads(executed.stdout)["reason_code"], "selected_recipe_changed")
        self.assertFalse((self.project / ".robot-skill-hub").exists())

    def test_source_reference_finding_save_and_recall_use_full_file_hash_without_prepare_claim(self):
        catalog = reference_catalog()
        self.write_finding(finding(environment={"runtime": "pybullet", "robot": "kuka"}))
        result = memories.save(catalog, "pybullet-ik", self.project, self.input)
        payload = json.loads(Path(result["finding_path"]).read_text())["payload"]
        expected = {"record_version": "source-" + "e" * 64, "source_commit": "d" * 40, "hub_commit": HUB}
        self.assertEqual(payload["base"], expected)
        detail = inspect(catalog, "pybullet-ik")
        self.assertEqual(detail["memory_base"], expected)
        self.assertFalse(detail["hub_prepare"])
        self.assertNotIn("prepare_args", detail)
        self.assertEqual(find(catalog, "inverse kinematics", {"runtime": "pybullet"})["results"][0]["memory_base"], expected)
        published = {**payload, "publication": {"public_submission_allowed": True},
                     "memory_id": "mem_" + "1" * 64, "fingerprint": result["fingerprint"], "content_sha256": "f" * 64,
                     "curation": "maintainer_merged", "interpretation": "data_only"}
        index = self.root / "reference-memories.json"
        index.write_text(json.dumps({"schema_version": "1", "records": [published]}))
        recalled = memories.query(catalog, "pybullet-ik", {"runtime": "pybullet", "robot": "kuka"}, index=index)
        self.assertEqual(recalled["total"], 1)
        catalog["references"]["records"][0]["source"]["sha256"] = "a" * 64
        self.assertEqual(memories.query(catalog, "pybullet-ik", {"runtime": "pybullet"}, index=index)["total"], 0)
        self.assertFalse((self.project / ".robot-skill-hub/environments").exists())

    def test_source_reference_missing_or_short_hash_cannot_create_invalid_memory_pins(self):
        for digest in (None, "e" * 12, "main"):
            catalog = reference_catalog()
            catalog["references"]["records"][0]["source"]["sha256"] = digest
            with self.subTest(digest=digest), mock.patch.object(contributions, "request_json") as network:
                with self.assertRaises(RshError) as error:
                    memories.save(catalog, "pybullet-ik", self.project, self.input)
                self.assertEqual(error.exception.result["reason_code"], "invalid_reference_pin")
                network.assert_not_called()
        self.assertFalse((self.project / ".robot-skill-hub").exists())


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.cache = mock.patch.dict(os.environ, {"RSH_CACHE_DIR": str(self.root / "cache")})
        self.cache.start()

    def tearDown(self):
        self.cache.stop()
        self.temp.cleanup()

    def test_remote_catalog_is_cached_and_outage_uses_it(self):
        calls = []
        def public(url):
            calls.append(url)
            if url.endswith("index.json"):
                return fixture_catalog()
            return {"schema_version": "1", "records": []}
        with mock.patch.object(discovery, "fetch_public", side_effect=public):
            first = discovery.load_discovery()
        self.assertEqual(first["catalog_origin"], "remote")
        with mock.patch.object(discovery, "fetch_public", side_effect=OSError("offline")) as network:
            cached = discovery.load_discovery(offline=True)
            network.assert_not_called()
        self.assertEqual(cached["hub_commit"], HUB)
        self.assertEqual(cached["catalog_origin"], "cache")

    def test_fresh_offline_install_uses_snapshot_and_explicit_fixture_never_fetches(self):
        with mock.patch.object(discovery, "fetch_public", side_effect=OSError("offline")):
            catalog = discovery.load_discovery()
        self.assertEqual(catalog["catalog_origin"], "bundled_snapshot")
        path = self.root / "fixture.json"
        path.write_text(json.dumps(fixture_catalog()))
        with mock.patch.object(discovery, "fetch_public") as network:
            explicit = discovery.load_discovery(path)
            network.assert_not_called()
        self.assertEqual(explicit["catalog_origin"], "explicit")

    def test_prepare_selection_does_not_fetch_and_project_record_stays_pinned(self):
        old = fixture_catalog()
        lock = self.root / ".robot-skill-hub/locks/fixture-pick.json"
        lock.parent.mkdir(parents=True)
        lock.write_text(json.dumps({"skill_id": "fixture-pick", "hub_commit": HUB, "record_version": "1.0.0",
                                    "source_commit": PIN, "record": old["records"][0]}))
        latest = copy.deepcopy(old)
        latest["records"][0]["maintenance"]["record_version"] = "2.0.0"
        with mock.patch.object(discovery, "fetch_public") as network:
            discovery.load_discovery(latest=False)
            selected = discovery.pinned_project_catalog(latest, self.root, "fixture-pick")
            network.assert_not_called()
        self.assertEqual(selected["records"][0]["maintenance"]["record_version"], "1.0.0")
        self.assertEqual(json.loads(lock.read_text())["record_version"], "1.0.0")

    def test_reference_search_is_explicitly_not_a_preparation_result(self):
        catalog = reference_catalog()
        result = find(catalog, "inverse kinematics", {"runtime": "pybullet"})
        self.assertEqual(result["total"], 1)
        item = result["results"][0]
        self.assertFalse(item["hub_prepare"])
        self.assertEqual(item["next_action"], "open_source_reference")
        self.assertEqual(item["compatibility_status"], "unknown")


if __name__ == "__main__":
    unittest.main()
