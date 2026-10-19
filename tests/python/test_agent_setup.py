"""First-use scope and credential setup; HTTP checks never create contributions."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from test_rsh import fixture_catalog
from test_memory_cli import finding
import rsh
from rshlib import contributions, memories, setup
from rshlib.core import RshError

TOKEN = "test-agent-token-0123456789-abcdef"


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / "experiment"
        self.project.mkdir()
        self.policy = self.project / ".robot-skill-hub.json"
        self.token_file = self.root / "scoped.secret"
        self.token_file.write_text(TOKEN + "\n", encoding="utf-8")
        # Keep OS machine identity while clearing application credentials. On
        # Windows platform.uname() caches these values for later test modules.
        machine = {key: os.environ[key] for key in ("PROCESSOR_ARCHITECTURE", "PROCESSOR_ARCHITEW6432") if key in os.environ}
        self.environment = mock.patch.dict(os.environ, machine, clear=True)
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.temp.cleanup()

    def allow(self, **kwargs):
        return setup.configure(self.project, allow_public_memory=True, skill_ids=["fixture-pick"],
                               kinds=["missing_requirement"], **kwargs)

    def test_contribution_api_defaults_to_hub_and_preserves_explicit_endpoint_precedence(self):
        os.environ["RSH_SUBMISSION_TOKEN_FILE"] = str(self.token_file)
        self.assertEqual(contributions.api_configuration(None), ("https://api.superfastrobotics.com", TOKEN))
        os.environ["RSH_API_URL"] = "https://operator.example.test/"
        self.assertEqual(contributions.api_configuration(None), ("https://operator.example.test", TOKEN))
        self.assertEqual(contributions.api_configuration("http://127.0.0.1:8765/"), ("http://127.0.0.1:8765", TOKEN))

    def test_default_endpoint_never_supplies_credentials_or_accepts_a_credential_url(self):
        with self.assertRaises(RshError) as error:
            contributions.api_configuration(None)
        self.assertEqual(error.exception.result["reason_code"], "missing_submission_token")
        os.environ["RSH_SUBMISSION_TOKEN_FILE"] = str(self.token_file)
        for endpoint in ("https://user:password@example.test", "https://example.test?key=secret"):
            with self.assertRaises(RshError):
                contributions.api_configuration(endpoint)

    def test_explicit_scope_is_required_and_replaces_only_memory_policy(self):
        existing = {"publication": {"public_submission_allowed": True, "allowed_paths": ["docs/*"]},
                    "private_extension": {"retain": "value"}, "memory": {"public_save_allowed": False}}
        self.policy.write_text(json.dumps(existing))
        with self.assertRaises(RshError):
            setup.configure(self.project)
        with self.assertRaises(RshError):
            setup.configure(self.project, allow_public_memory=True)
        self.assertEqual(json.loads(self.policy.read_text()), existing)
        result = self.allow()
        saved = json.loads(self.policy.read_text())
        self.assertEqual(saved["publication"], existing["publication"])
        self.assertEqual(saved["private_extension"], existing["private_extension"])
        self.assertEqual(saved["memory"]["allowed_skill_ids"], ["fixture-pick"])
        self.assertFalse(result["network_performed"])
        self.assertFalse(result["token_persisted"])
        before = self.policy.stat().st_mtime_ns
        self.assertFalse(self.allow()["changed"])
        self.assertEqual(self.policy.stat().st_mtime_ns, before)
        setup.configure(self.project, local_only=True)
        self.assertFalse(json.loads(self.policy.read_text())["memory"]["public_save_allowed"])

    def test_invalid_policy_or_scope_is_not_overwritten(self):
        for value in ("[]", "broken JSON"):
            self.policy.write_text(value)
            with self.assertRaises(RshError):
                self.allow()
            self.assertEqual(self.policy.read_text(), value)
        self.policy.unlink()
        for skills, kinds in ((["../escape"], ["missing_requirement"]), (["fixture-pick"], ["invented"])):
            with self.assertRaises(RshError):
                setup.configure(self.project, allow_public_memory=True, skill_ids=skills, kinds=kinds)
        self.assertFalse(self.policy.exists())

    def test_fixed_temporary_symlink_cannot_overwrite_an_external_file(self):
        external = self.root / "outside-project.txt"
        external.write_bytes(b"preserve external bytes")
        stale_temporary = self.project / ".robot-skill-hub.json.tmp"
        try:
            stale_temporary.symlink_to(external)
        except OSError as error:
            self.skipTest("This host cannot create a file symlink: " + str(error))
        self.allow()
        self.assertEqual(external.read_bytes(), b"preserve external bytes")
        self.assertTrue(json.loads(self.policy.read_text())["memory"]["public_save_allowed"])
        self.assertTrue(stale_temporary.is_symlink())
        self.assertEqual(list(self.project.glob(".robot-skill-hub-*.tmp")), [])

    def test_fixed_temporary_hardlink_is_ignored_and_external_bytes_are_preserved(self):
        external = self.root / "hardlinked-outside-project.txt"
        external.write_bytes(b"preserve external hardlinked bytes")
        stale_temporary = self.project / ".robot-skill-hub.json.tmp"
        os.link(external, stale_temporary)
        self.allow()
        self.assertEqual(external.read_bytes(), b"preserve external hardlinked bytes")
        self.assertTrue(json.loads(self.policy.read_text())["memory"]["public_save_allowed"])
        self.assertTrue(stale_temporary.samefile(external))
        self.assertEqual(list(self.project.glob(".robot-skill-hub-*.tmp")), [])

    def test_setup_check_does_not_infer_consent_from_token_or_make_network_request(self):
        os.environ["RSH_SUBMISSION_TOKEN_FILE"] = str(self.token_file)
        with mock.patch.object(contributions, "request_json") as network:
            result = setup.check(self.project)
        self.assertFalse(result["local_public_save_ready"])
        self.assertEqual(result["credential"], {"configured": True, "source": "file", "authentication": "not_checked"})
        network.assert_not_called()
        self.assertFalse(self.policy.exists())
        self.allow()
        result = setup.check(self.project)
        self.assertTrue(result["local_public_save_ready"])
        self.assertNotIn(TOKEN, json.dumps(result))
        self.assertNotIn(TOKEN, self.policy.read_text())

    def test_token_file_is_bounded_one_line_and_environment_wins(self):
        os.environ["RSH_SUBMISSION_TOKEN_FILE"] = str(self.token_file)
        for invalid in (TOKEN + "\n" + TOKEN, " " + TOKEN, "x" * 4097, "short"):
            self.token_file.write_text(invalid)
            result = setup.check(self.project)
            self.assertFalse(result["credential"]["configured"])
            self.assertNotIn(TOKEN, json.dumps(result))
        os.environ["RSH_SUBMISSION_TOKEN"] = TOKEN
        token, source = contributions.submission_token()
        self.assertEqual((token, source), (TOKEN, "environment"))

    def test_file_token_delivers_after_explicit_policy_without_token_persistence(self):
        self.allow()
        os.environ["RSH_SUBMISSION_TOKEN_FILE"] = str(self.token_file)
        input_file = self.root / "finding.json"
        input_file.write_text(json.dumps(finding()))
        def response(method, url, token, **kwargs):
            self.assertEqual((method, token), ("POST", TOKEN))
            payload = json.loads(kwargs["payload"])
            return {"status": "stored", "memory_id": "mem_" + "1" * 64,
                    "fingerprint": memories.fingerprint(payload), "content_sha256": "e" * 64}
        with mock.patch.object(contributions, "request_json", side_effect=response) as network:
            result = memories.save(fixture_catalog(), "fixture-pick", self.project, input_file)
        self.assertEqual(result["status"], "stored")
        self.assertEqual(network.call_count, 1)
        self.assertNotIn(TOKEN, Path(result["finding_path"]).read_text())

    def test_cli_setup_skips_catalog_discovery(self):
        with mock.patch.object(rsh, "load_discovery") as discovery, contextlib.redirect_stdout(io.StringIO()) as output:
            code = rsh.main(["setup", "--project", str(self.project), "--local-only", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["memory"], {"public_save_allowed": False})
        discovery.assert_not_called()

    def test_explicit_remote_check_is_one_authenticated_read_only_request(self):
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(handler):
                requests.append((handler.command, handler.path, handler.headers.get("Authorization"), handler.headers.get("User-Agent")))
                handler.send_response(200)
                handler.send_header("Content-Type", "application/json")
                handler.end_headers()
                handler.wfile.write(json.dumps({"schema_version": "1", "authenticated": True, "principal_id": "a" * 64,
                     "authorization": {"api_submission_allowed": True, "project_memory_scope": "client_policy_required"}}).encode())
            def log_message(handler, *args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.allow()
        os.environ.update(RSH_SUBMISSION_TOKEN_FILE=str(self.token_file), RSH_API_URL=f"http://127.0.0.1:{server.server_port}")
        result = setup.check(self.project, check_api=True)
        self.assertEqual(result["credential"]["authentication"], "verified")
        self.assertTrue(result["network_performed"])
        self.assertEqual(requests, [("GET", "/v1/session", "Bearer " + TOKEN, "robot-skill-hub/1")])
        self.assertNotIn(TOKEN, json.dumps(result))
        with self.assertRaises(RshError):
            setup.check(self.project, check_api=True, offline=True)
        self.assertEqual(len(requests), 1)

    def test_remote_error_is_sanitized_and_does_not_grant_policy(self):
        os.environ["RSH_SUBMISSION_TOKEN"] = TOKEN
        error = RshError("authentication_required", "Rejected", api_error={"reason_code": "invalid_token",
                         "message": "Bearer " + TOKEN, "request": TOKEN})
        with mock.patch.object(contributions, "request_json", side_effect=error):
            result = setup.check(self.project, check_api=True)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["credential"]["authentication"], "failed")
        self.assertFalse(result["local_public_save_ready"])
        self.assertEqual(result["api_error"], {"reason_code": "invalid_token"})
        self.assertNotIn(TOKEN, json.dumps(result))
        self.assertFalse(self.policy.exists())

    def test_remote_error_cannot_echo_the_bare_active_credential(self):
        os.environ["RSH_SUBMISSION_TOKEN"] = TOKEN
        error = RshError("authentication_required", "Rejected", api_error={"reason_code": "invalid_token",
                         "message": "Unrecognized credential " + TOKEN, "next_action": TOKEN})
        with mock.patch.object(contributions, "request_json", side_effect=error):
            result = setup.check(self.project, check_api=True)
        self.assertEqual(result["api_error"], {"reason_code": "invalid_token"})
        self.assertNotIn(TOKEN, json.dumps(result))


if __name__ == "__main__":
    unittest.main()
