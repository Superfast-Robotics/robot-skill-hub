"""Offline patch boundaries and credential-safe API results; no HTTP is sent."""
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import runpy
import tempfile
import unittest
import urllib.error
from unittest import mock

from test_rsh import bundle, fixture_catalog, SKILL
from test_memory_cli import finding
from rshlib import contributions


TOKEN = "opaque.Active-credential_0123456789~abcdef"


class ContributionBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.project = Path(self.temporary.name)
        self.bundle = self.project / "bundle.json"
        self.bundle.write_text(json.dumps(bundle()), encoding="utf-8")
        (self.project / ".robot-skill-hub.json").write_text(json.dumps({
            "publication": {"public_submission_allowed": True},
            "memory": {"public_save_allowed": True, "allowed_skill_ids": ["fixture-pick"],
                       "allowed_kinds": ["missing_requirement"]}}), encoding="utf-8")
        self.finding = self.project / "finding.json"
        self.finding.write_text(json.dumps(finding()), encoding="utf-8")
        self.cli = runpy.run_path(str(SKILL / "scripts/rsh.py"), run_name="rsh_contribution_boundary_test")
        self.addCleanup(mock.patch.stopall)
        mock.patch.dict(os.environ, {"RSH_SUBMISSION_TOKEN": TOKEN, "RSH_TELEMETRY": "off"}).start()

    def invoke(self, args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = self.cli["main"]([*args, "--json"])
        self.assertNotIn(TOKEN, stdout.getvalue() + stderr.getvalue())
        self.assertEqual(stderr.getvalue(), "")
        return code, json.loads(stdout.getvalue())

    def commands(self):
        return (["submit", str(self.bundle), "--project", str(self.project)],
                ["submission-status", "sub_fixture"])

    def test_offline_patch_commands_stop_before_files_catalog_credentials_or_http(self):
        with ExitStack() as stack:
            forbidden = [stack.enter_context(mock.patch.dict(self.cli["execute"].__globals__, {
                name: mock.Mock(side_effect=AssertionError(name + " must not be used offline"))}))[name]
                for name in ("read_json", "load_discovery", "pinned_project_catalog")]
            forbidden.extend(stack.enter_context(mock.patch.object(owner, name,
                side_effect=AssertionError(name + " must not be used offline")))
                for owner, name in ((self.cli["remote_catalog"], "selected_catalog"),
                                    (contributions, "submission_token"), (contributions, "submit"),
                                    (contributions, "submission_status")))
            forbidden.append(stack.enter_context(mock.patch("urllib.request.build_opener",
                side_effect=AssertionError("HTTP must not be used offline"))))
            for command in self.commands():
                for args in (["--offline", *command], [*command, "--offline"]):
                    with self.subTest(args=args):
                        code, result = self.invoke([*args, "--catalog", "https://catalog.invalid/not-read"])
                        self.assertEqual((code, result["status"], result["reason_code"], result["network_performed"]),
                                         (2, "blocked", "offline_submission_unavailable", False))
            for call in forbidden:
                call.assert_not_called()
        self.assertFalse(self.bundle.with_name("bundle.receipt.json").exists())

    def reject(self, kind):
        if kind == "transport":
            return urllib.error.URLError("Transport echoed " + TOKEN)
        error = {"reason_code": "stale_record", "message": "Rejected credential " + TOKEN,
                 "next_action": "inspect_original_catalog_base", "request": {"authorization": TOKEN},
                 "raw_body": "An arbitrary remote body must not be copied."}
        return urllib.error.HTTPError("https://api.example.test/v1/test", 409, "Conflict",
                                      {"Retry-After": TOKEN}, io.BytesIO(json.dumps(error).encode()))

    def test_patch_submit_and_status_keep_safe_errors_without_echoing_remote_or_transport_tokens(self):
        for command in self.commands():
            for kind in ("http", "transport"):
                with self.subTest(command=command[0], kind=kind), \
                        mock.patch.dict(self.cli["execute"].__globals__, {"load_discovery": mock.Mock(return_value=fixture_catalog())}), \
                        mock.patch("urllib.request.build_opener") as opener:
                    opener.return_value.open.side_effect = self.reject(kind)
                    code, result = self.invoke([*command, "--catalog", "not-read.json", "--api-url", "https://api.example.test"])
                    self.assertEqual((2, "blocked"), (code, result["status"]))
                    self.assertEqual(opener.return_value.open.call_count, 1)
                    request = opener.return_value.open.call_args.args[0]
                    self.assertEqual(request.get_method(), "POST" if command[0] == "submit" else "GET")
                    self.assertEqual(request.get_header("Authorization"), "Bearer " + TOKEN)
                    if kind == "http":
                        self.assertEqual(result["api_error"], {"reason_code": "stale_record", "next_action": "inspect_original_catalog_base"})
                        self.assertIsNone(result["retry_after"])
                        self.assertNotIn("raw_body", json.dumps(result))
                    else:
                        self.assertEqual(result["reason_code"], "api_unavailable")
                    for path in self.project.rglob("*.json"):
                        self.assertNotIn(TOKEN, path.read_text(encoding="utf-8"))

    def test_memory_http_and_transport_errors_never_reach_cli_or_saved_outbox(self):
        for kind in ("http", "transport"):
            with self.subTest(kind=kind), \
                    mock.patch.dict(self.cli["execute"].__globals__, {"load_discovery": mock.Mock(return_value=fixture_catalog())}), \
                    mock.patch("urllib.request.build_opener") as opener:
                opener.return_value.open.side_effect = self.reject(kind)
                code, result = self.invoke(["save", "fixture-pick", "--project", str(self.project),
                    "--finding", str(self.finding), "--catalog", "not-read.json", "--api-url", "https://api.example.test"]
                    if kind == "http" else ["flush", "--project", str(self.project), "--api-url", "https://api.example.test"])
                self.assertEqual((0, "local_saved" if kind == "http" else "ready"), (code, result["status"]))
                self.assertEqual(opener.return_value.open.call_count, 1)
                saved = result if kind == "http" else result["results"][0]
                self.assertTrue(saved["network_performed"])
                outbox = Path(saved["finding_path"]).read_text(encoding="utf-8")
                self.assertNotIn(TOKEN, outbox)
                self.assertNotIn("raw_body", outbox)
                if kind == "http":
                    self.assertEqual(saved["delivery_error"], {"reason_code": "stale_record", "next_action": "inspect_original_catalog_base"})

    def test_memory_sanitizes_an_already_wrapped_error_with_the_exact_active_token(self):
        error = contributions.RshError("submission_conflict", "Rejected", api_error={
            "reason_code": "stale_record", "message": TOKEN, "next_action": "retry with " + TOKEN})
        with mock.patch.dict(self.cli["execute"].__globals__, {"load_discovery": mock.Mock(return_value=fixture_catalog())}), \
                mock.patch.object(contributions, "request_json", side_effect=error) as request:
            code, result = self.invoke(["save", "fixture-pick", "--project", str(self.project),
                "--finding", str(self.finding), "--catalog", "not-read.json"])
        self.assertEqual((code, result["status"]), (0, "local_saved"))
        request.assert_called_once()
        self.assertEqual(result["delivery_error"], {"reason_code": "stale_record"})
        self.assertNotIn(TOKEN, Path(result["finding_path"]).read_text(encoding="utf-8"))

    def test_success_response_cannot_smuggle_active_token_into_patch_receipt_or_memory_outbox(self):
        for command in (self.commands()[0], ["save", "fixture-pick", "--project", str(self.project), "--finding", str(self.finding)]):
            with self.subTest(command=command[0]), \
                    mock.patch.dict(self.cli["execute"].__globals__, {"load_discovery": mock.Mock(return_value=fixture_catalog())}), \
                    mock.patch("urllib.request.build_opener") as opener:
                response = opener.return_value.open.return_value.__enter__.return_value
                response.status = 201
                response.read.return_value = json.dumps({"status": "submitted", "extra": {TOKEN: "echo"}}).encode()
                code, result = self.invoke([*command, "--catalog", "not-read.json", "--api-url", "https://api.example.test"])
                self.assertEqual(result["reason_code"], "invalid_api_response")
                self.assertEqual(opener.return_value.open.call_count, 1)
                for path in self.project.rglob("*.json"):
                    self.assertNotIn(TOKEN, path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
