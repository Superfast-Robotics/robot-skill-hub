"""Project authorization and provenance use one home-expanded root; no HTTP."""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from test_rsh import bundle, fixture_catalog, DOC_PATH
from test_memory_cli import finding
from test_intake import skill
import rsh
from rshlib import contributions


TOKEN = "test-project-token-0123456789-abcdef"


class ProjectPolicyPathTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home, self.cwd = self.root / "home", self.root / "cwd"
        self.project, self.decoy = self.home / "work", self.cwd / "~" / "work"
        for path in (self.project, self.decoy):
            path.mkdir(parents=True)
        previous = Path.cwd()
        self.addCleanup(os.chdir, previous)
        os.chdir(self.cwd)
        environment = mock.patch.dict(os.environ, {"HOME": str(self.home), "USERPROFILE": str(self.home),
                                                   "RSH_TELEMETRY": "off"}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        network = mock.patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("No real HTTP"))
        network.start()
        self.addCleanup(network.stop)
        self.catalog = self.root / "catalog.json"
        self.catalog.write_text(json.dumps(fixture_catalog()), encoding="utf-8")
        self.finding = self.root / "finding.json"
        self.finding.write_text(json.dumps(finding()), encoding="utf-8")
        self.selector = ["--catalog", str(self.catalog)]

    def invoke(self, arguments):
        output = io.StringIO()
        with redirect_stdout(output):
            code = rsh.main([*arguments, "--json"])
        self.assertNotIn(TOKEN, output.getvalue())
        return code, json.loads(output.getvalue())

    def memory_policy(self, project, allowed):
        path = project / ".robot-skill-hub.json"
        path.write_text(json.dumps({"memory": {"public_save_allowed": allowed,
            "allowed_skill_ids": ["fixture-pick"], "allowed_kinds": ["missing_requirement"]}}), encoding="utf-8")
        return path

    def response(self, method, url, token, **kwargs):
        self.assertEqual((method, url, token), ("POST", "https://api.superfastrobotics.com/v1/memories", TOKEN))
        payload = json.loads(kwargs["payload"])
        from rshlib.memories import fingerprint
        return {"status": "stored", "memory_id": "mem_" + "1" * 64,
                "fingerprint": fingerprint(payload), "content_sha256": "e" * 64}

    def save_args(self):
        return [*self.selector, "save", "fixture-pick", "--project", "~/work", "--finding", str(self.finding)]

    def test_setup_check_save_and_selected_flush_agree_on_the_expanded_project(self):
        decoy_policy = self.memory_policy(self.decoy, False)
        decoy_bytes = decoy_policy.read_bytes()
        code, configured = self.invoke(["setup", "--project", "~/work", "--allow-public-memory",
                                       "--skill", "fixture-pick", "--kind", "missing_requirement"])
        self.assertEqual((0, str(self.project / ".robot-skill-hub.json")), (code, configured["policy_path"]))
        os.environ["RSH_SUBMISSION_TOKEN"] = TOKEN
        code, checked = self.invoke(["setup-check", "--project", "~/work"])
        self.assertEqual((0, True), (code, checked["local_public_save_ready"]))
        with mock.patch.object(contributions, "request_json", side_effect=self.response) as post:
            code, saved = self.invoke(self.save_args())
        self.assertEqual((0, "stored", True), (code, saved["status"], saved["network_performed"]))
        self.assertEqual(post.call_count, 1)
        self.assertTrue(Path(saved["finding_path"]).is_relative_to(self.project))
        self.finding.write_text(json.dumps(finding(summary="A second optional dependency observation")), encoding="utf-8")
        with mock.patch.object(contributions, "request_json") as post:
            _, pending = self.invoke([*self.save_args(), "--offline"])
            post.assert_not_called()
        original = json.loads(Path(pending["finding_path"]).read_bytes())["payload"]
        with mock.patch.object(contributions, "request_json", side_effect=self.response) as post:
            code, flushed = self.invoke(["flush", "--project", "~/work", "--fingerprint", pending["fingerprint"], "--limit", "1"])
        self.assertEqual((0, "stored", True), (code, flushed["results"][0]["status"], flushed["network_performed"]))
        self.assertEqual(post.call_count, 1)
        self.assertEqual(post.call_args.kwargs["idempotency_key"], pending["fingerprint"])
        self.assertEqual(json.loads(post.call_args.kwargs["payload"])["base"], original["base"])
        self.assertEqual(decoy_policy.read_bytes(), decoy_bytes)
        self.assertFalse((self.decoy / ".robot-skill-hub").exists())

    def test_decoy_cannot_grant_memory_scope_to_a_local_only_project(self):
        self.memory_policy(self.decoy, True)
        self.invoke(["setup", "--project", "~/work", "--local-only"])
        os.environ["RSH_SUBMISSION_TOKEN"] = TOKEN
        _, checked = self.invoke(["setup-check", "--project", "~/work"])
        self.assertFalse(checked["local_public_save_ready"])
        with mock.patch.object(contributions, "request_json", side_effect=self.response) as post:
            code, saved = self.invoke(self.save_args())
            self.assertEqual((0, "local_saved", "memory_sharing_not_allowed"), (code, saved["status"], saved["reason_code"]))
            code, flushed = self.invoke(["flush", "--project", "~/work", "--fingerprint", saved["fingerprint"]])
            self.assertEqual((0, "memory_sharing_not_allowed", False),
                             (code, flushed["results"][0]["reason_code"], flushed["network_performed"]))
            post.assert_not_called()
        self.assertFalse(json.loads(Path(saved["finding_path"]).read_bytes())["payload"]["publication"]["public_submission_allowed"])

    def test_explicit_policy_keeps_cwd_and_literal_tilde_semantics(self):
        allow = {"memory": {"public_save_allowed": True, "allowed_skill_ids": ["fixture-pick"], "allowed_kinds": ["missing_requirement"]}}
        deny = {"memory": {"public_save_allowed": False}}
        self.memory_policy(self.project, True)
        (self.cwd / "~" / "selected.json").write_text(json.dumps(deny), encoding="utf-8")
        (self.home / "selected.json").write_text(json.dumps(allow), encoding="utf-8")
        os.environ["RSH_SUBMISSION_TOKEN"] = TOKEN
        with mock.patch.object(contributions, "request_json") as post:
            code, saved = self.invoke([*self.save_args(), "--policy", "~/selected.json"])
            self.assertEqual((0, "memory_sharing_not_allowed"), (code, saved["reason_code"]))
            post.assert_not_called()
        (self.cwd / "selected.json").write_text(json.dumps(allow), encoding="utf-8")
        (self.project / "selected.json").write_text(json.dumps(deny), encoding="utf-8")
        self.finding.write_text(json.dumps(finding(summary="Another explicit policy observation")), encoding="utf-8")
        with mock.patch.object(contributions, "request_json", side_effect=self.response) as post:
            code, saved = self.invoke([*self.save_args(), "--policy", "selected.json"])
        self.assertEqual((0, "stored", 1), (code, saved["status"], post.call_count))

    def test_patch_bundle_preserves_the_expanded_project_lock_pins(self):
        policy = {"publication": {"public_submission_allowed": True, "allowed_skill_ids": ["fixture-pick"], "allowed_paths": [DOC_PATH]}}
        expected = {"record_version": "retained-project-version", "hub_commit": "c" * 40, "source_commit": "d" * 40}
        for project, pins in ((self.project, expected), (self.decoy, {"record_version": "decoy", "hub_commit": "e" * 40, "source_commit": "f" * 40})):
            (project / ".robot-skill-hub.json").write_text(json.dumps(policy), encoding="utf-8")
            lock = project / ".robot-skill-hub/locks/fixture-pick.json"
            lock.parent.mkdir(parents=True)
            lock.write_text(json.dumps(pins), encoding="utf-8")
        patch, metadata, output = (self.root / name for name in ("fix.patch", "metadata.json", "bundle.json"))
        patch.write_text(bundle()["patch"], encoding="utf-8")
        metadata.write_text(json.dumps(bundle()), encoding="utf-8")
        with mock.patch.object(contributions, "api_configuration", side_effect=AssertionError("No credential lookup")):
            code, result = self.invoke([*self.selector, "--offline", "bundle", "fixture-pick", "--project", "~/work",
                                       "--patch", str(patch), "--metadata", str(metadata), "--output", str(output)])
        self.assertEqual((0, "ready", False), (code, result["status"], result["network_performed"]))
        self.assertEqual(json.loads(output.read_bytes())["base"], expected)
        self.assertEqual(json.loads((self.project / ".robot-skill-hub/locks/fixture-pick.json").read_bytes()), expected)

    def test_register_recovery_keeps_true_default_policy_and_saved_identity(self):
        selected = skill(); source = self.root / "skill.json"
        source.write_text(json.dumps(selected), encoding="utf-8")
        allowed = {"publication": {"public_submission_allowed": True, "allowed_skill_ids": [selected["id"]],
                   "allowed_new_skill_ids": [selected["id"]], "allowed_paths": ["catalog/intake/" + selected["id"] + ".json"]}}
        (self.project / ".robot-skill-hub.json").write_text(json.dumps(allowed), encoding="utf-8")
        (self.decoy / ".robot-skill-hub.json").write_text('{"publication":{"public_submission_allowed":false}}', encoding="utf-8")
        with mock.patch.object(contributions, "request_json") as post:
            code, saved = self.invoke([*self.selector, "register", str(source), "--project", "~/work", "--contributor", "Fixture agent"])
            post.assert_not_called()
        self.assertEqual((0, "local_saved", "missing_submission_token"), (code, saved["status"], saved["reason_code"]))
        path = Path(saved["bundle_path"]); original = path.read_bytes()
        args = saved["delivery_recovery"]["register_args"]
        self.assertEqual(args[args.index("--project") + 1], str(self.project))
        self.assertEqual(args[args.index("--policy") + 1], str(self.project / ".robot-skill-hub.json"))
        later = self.root / "later-cwd"; later.mkdir(); os.chdir(later)
        os.environ["RSH_SUBMISSION_TOKEN"] = TOKEN
        with mock.patch.object(rsh, "load_discovery", side_effect=AssertionError("No fresh discovery")), \
                mock.patch.object(rsh.remote_catalog, "current_catalog", side_effect=AssertionError("No public request")), \
                mock.patch.object(contributions, "request_json", return_value={"status": "submitted", "submission_id": "sub_" + "2" * 64}) as post:
            code, submitted = self.invoke(args)
        self.assertEqual((0, "submitted", 1), (code, submitted["status"], post.call_count))
        self.assertEqual(post.call_args.kwargs["idempotency_key"], saved["idempotency_key"])
        self.assertEqual(post.call_args.kwargs["payload"], contributions.canonical_bytes(json.loads(original)))
        self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
