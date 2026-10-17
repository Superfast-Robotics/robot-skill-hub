"""Sync orchestration uses only mocked transport or opted-out loopback HTTP."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import textwrap
import threading
import unittest
from unittest import mock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import urllib.error

import sync_catalog as sync

HUB, OTHER = "a" * 40, "b" * 40
KEY = "private-sync-test-key-never-print-this"


def progress(next_page, total=3, *, status=None):
    return {"hub_commit": HUB, "status": status or ("active" if next_page == total else "syncing"),
            "next_page": next_page, "total_pages": total, "records": 42, "memories": 3}


class Clock:
    def __init__(self):
        self.now, self.sleeps = 0, []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        if not 0 < seconds <= 5:
            raise AssertionError("Sleep must be bounded and positive")
        self.sleeps.append(seconds)
        self.now += seconds


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.environment = mock.patch.dict(os.environ, {"CATALOG_SYNC_KEY": KEY})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.clock = Clock()
        self.events = []

    def run_sync(self, request, **kwargs):
        return sync.sync_catalog(HUB, request_fn=request, clock=self.clock, sleeper=self.clock.sleep,
                                 report=self.events.append, **kwargs)

    def test_successful_pages_resume_same_commit_across_bounded_transport_retries(self):
        request = mock.Mock(side_effect=[(200, progress(1), None), OSError("sensitive " + KEY),
                                        (503, None, "999999"), (200, progress(2), None), (200, progress(3), None)])
        result = self.run_sync(request)
        self.assertEqual(result, progress(3))
        self.assertEqual(self.clock.sleeps, [1, 5])
        self.assertTrue(all(call.args[:2] == (HUB, KEY) for call in request.call_args_list))
        self.assertTrue(all(0 < call.args[2] <= 20 for call in request.call_args_list))
        self.assertNotIn(KEY, json.dumps(self.events))
        self.assertEqual([e["next_page"] for e in self.events if "next_page" in e], [1, 2, 3])

    def test_initial_different_publication_can_propagate_then_sync_without_switch_or_reset(self):
        conflict = (409, {"reason_code": "catalog_changed", "hub_commit": OTHER}, None)
        request = mock.Mock(side_effect=[conflict, (200, progress(1, 2), None), (200, progress(2, 2), None)])
        result = self.run_sync(request)
        self.assertEqual(result["status"], "active")
        self.assertEqual(self.clock.sleeps, [5])
        self.assertEqual({call.args[0] for call in request.call_args_list}, {HUB})
        self.assertEqual(self.events[0]["status"], "waiting_for_publication")

    def test_persistent_different_commit_is_terminal_superseded_within_60_seconds(self):
        request = mock.Mock(return_value=(409, {"reason_code": "catalog_changed", "hub_commit": OTHER}, None))
        result = self.run_sync(request)
        self.assertEqual(result["status"], "superseded")
        self.assertEqual(result["expected_hub_commit"], HUB)
        self.assertEqual(result["hub_commit"], OTHER)
        self.assertLessEqual(self.clock.now, 60)
        self.assertLessEqual(request.call_count, 12)
        self.assertEqual({call.args[0] for call in request.call_args_list}, {HUB})
        self.assertFalse(any(e.get("status") == "active" for e in self.events))

    def test_commit_change_after_progress_is_superseded_immediately(self):
        request = mock.Mock(side_effect=[(200, progress(1), None),
            (409, {"reason_code": "catalog_changed", "hub_commit": OTHER}, None)])
        self.assertEqual(self.run_sync(request)["status"], "superseded")
        self.assertEqual(self.clock.sleeps, [])

    def test_transient_failure_does_not_relabel_an_old_conflict_as_current_after_window(self):
        calls = 0
        def request(expected, key, timeout):
            nonlocal calls
            calls += 1
            if calls == 1:
                return 409, {"reason_code": "catalog_changed", "hub_commit": OTHER}, None
            if calls == 2:
                self.clock.now += sync.PROPAGATION_SECONDS
                return 503, None, None
            return 200, progress(3), None
        self.assertEqual(self.run_sync(request)["status"], "active")
        self.assertEqual(calls, 3)

    def test_malformed_or_regressing_progress_is_never_reported_as_active(self):
        cases = [dict(progress(1), hub_commit=OTHER), dict(progress(1), status="active"),
                 dict(progress(1), next_page=True), dict(progress(1), credentials=KEY),
                 dict(progress(1), next_page=4), dict(progress(1), records=-1)]
        for value in cases:
            with self.subTest(value=list(value)), self.assertRaises(sync.SyncFailure):
                self.run_sync(mock.Mock(return_value=(200, value, None)))
        request = mock.Mock(side_effect=[(200, progress(2), None), (200, progress(1), None)])
        with self.assertRaisesRegex(sync.SyncFailure, "recorded progress"):
            self.run_sync(request)
        self.assertNotIn(KEY, json.dumps(self.events))

    def test_retry_stall_deadline_and_call_bounds_preserve_server_state(self):
        request = mock.Mock(return_value=(503, None, None))
        with self.assertRaisesRegex(sync.SyncFailure, "retries were exhausted"):
            self.run_sync(request)
        self.assertEqual(request.call_count, sync.MAX_RETRIES + 1)
        with self.assertRaisesRegex(sync.SyncFailure, "stopped advancing"):
            self.run_sync(mock.Mock(return_value=(200, progress(1), None)))
        self.clock = Clock()
        with self.assertRaisesRegex(sync.SyncFailure, "deadline"):
            self.run_sync(mock.Mock(return_value=(503, None, None)), timeout_seconds=0.25)
        self.clock = Clock()
        with mock.patch.object(sync, "MAX_CALLS", 1):
            with self.assertRaisesRegex(sync.SyncFailure, "call limit"):
                self.run_sync(mock.Mock(return_value=(200, progress(1), None)))

    def test_daily_write_limit_stops_without_retry_or_switch_after_preserving_progress(self):
        quota = (503, {"reason_code": "catalog_write_limit"}, "18000")
        for prefix in ([], [(200, progress(1), None)]):
            with self.subTest(progress=bool(prefix)):
                request = mock.Mock(side_effect=prefix + [quota])
                with self.assertRaises(sync.SyncFailure) as failure:
                    self.run_sync(request)
                self.assertEqual(failure.exception.code, "catalog_write_limit")
                self.assertEqual(request.call_count, len(prefix) + 1)
                self.assertEqual(self.clock.sleeps, [])
        stderr = io.StringIO()
        with mock.patch.object(sync, "sync_catalog", side_effect=sync.SyncFailure("catalog_write_limit", KEY)), contextlib.redirect_stderr(stderr):
            self.assertEqual(sync.main(["--hub-commit", HUB]), 75)
        self.assertEqual(json.loads(stderr.getvalue()), {"status": "deferred", "reason_code": "catalog_write_limit"})
        self.assertNotIn(KEY, stderr.getvalue())

    def test_cli_never_logs_exception_headers_body_or_unknown_argument_secret(self):
        for failure in (RuntimeError("Authorization: Bearer " + KEY), sync.SyncFailure(KEY, KEY), sync.SyncFailure([KEY], KEY)):
            stdout, stderr = io.StringIO(), io.StringIO()
            with mock.patch.object(sync, "sync_catalog", side_effect=failure), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                self.assertEqual(sync.main(["--hub-commit", HUB]), 1)
            self.assertNotIn(KEY, stdout.getvalue() + stderr.getvalue())
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as stopped:
            sync.main(["--hub-commit", HUB, "--key", KEY])
        self.assertEqual(stopped.exception.code, 2)
        self.assertNotIn(KEY, stderr.getvalue())
        with mock.patch.dict(os.environ, {"CATALOG_SYNC_KEY": ""}), self.assertRaisesRegex(sync.SyncFailure, "environment"):
            self.run_sync(mock.Mock())


class TransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.requests, cls.leaked = [], 0
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                cls.leaked += 1
                self.send_response(200)
                self.end_headers()

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                cls.requests.append((self.path, json.loads(body), dict(self.headers)))
                if self.path == "/redirect":
                    self.send_response(302)
                    self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/credential-leak")
                    self.end_headers()
                    return
                if self.path == "/oversize":
                    raw = b'"' + b'x' * sync.MAX_RESPONSE_BYTES + b'"'
                elif self.path == "/malformed":
                    raw = ("not-json " + KEY).encode()
                elif self.path == "/quota":
                    raw = json.dumps({"reason_code": "catalog_write_limit", "message": KEY}).encode()
                elif self.path == "/unknown-503":
                    raw = ("provider-html " + KEY).encode()
                else:
                    raw = json.dumps(progress(3)).encode()
                self.send_response(503 if self.path in ("/quota", "/unknown-503") else 200)
                self.send_header("Content-Type", "application/json")
                if self.path != "/oversize":
                    self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.worker = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.worker.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.worker.join(timeout=2)

    def local_post(self, path):
        with mock.patch.object(sync, "ENDPOINT", f"http://127.0.0.1:{self.server.server_port}" + path):
            return sync._post(HUB, KEY, 2)

    def test_only_fixed_endpoint_is_production_config_and_loopback_requests_opt_out(self):
        self.assertEqual(sync.ENDPOINT, "https://api.superfastrobotics.com/internal/catalog-sync")
        status, value, _ = self.local_post("/progress")
        self.assertEqual((status, value), (200, progress(3)))
        _, body, headers = self.requests[-1]
        headers = {key.lower(): value for key, value in headers.items()}
        self.assertEqual(body, {"hub_commit": HUB})
        self.assertEqual(headers["dnt"], "1")
        self.assertEqual(headers["x-rsh-telemetry"], "off")
        self.assertEqual(headers["authorization"], "Bearer " + KEY)

    def test_redirect_does_not_forward_authorization_and_oversized_or_malformed_body_is_bounded(self):
        status, value, _ = self.local_post("/redirect")
        self.assertEqual((status, value), (302, None))
        self.assertEqual(self.leaked, 0)
        for route in ("/oversize", "/malformed"):
            with self.subTest(route=route), self.assertRaises(sync.SyncFailure) as failure:
                self.local_post(route)
            self.assertNotIn(KEY, str(failure.exception))

    def test_transport_retains_only_known_quota_code_and_discards_provider_text(self):
        self.assertEqual(self.local_post("/quota"), (503, {"reason_code": "catalog_write_limit"}, None))
        self.assertEqual(self.local_post("/unknown-503"), (503, None, None))


class WorkflowTests(unittest.TestCase):
    def test_scheduled_resume_pins_served_commit_even_when_main_differs_without_sending_credentials(self):
        workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/resume-catalog.yml").read_text(encoding="utf-8")
        script = textwrap.dedent(workflow.split("python - <<'PY'\n", 1)[1].split("\n          PY", 1)[0])
        requests = []
        class Opener:
            def open(self, request, timeout):
                requests.append(request)
                self_test.assertEqual(timeout, 20)
                return io.BytesIO(json.dumps({"hub_commit": HUB}).encode())
        self_test = self
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "outputs"
            with mock.patch.dict(os.environ, {"GITHUB_SHA": OTHER, "GITHUB_OUTPUT": str(output)}), mock.patch.object(urllib.request, "build_opener", return_value=Opener()):
                exec(compile(script, "scheduled-publication-pin", "exec"), {})
            self.assertEqual(output.read_text(encoding="utf-8"), "hub_commit=" + HUB + "\n")
        self.assertEqual(len(requests), 1)
        request = requests[0]
        self.assertEqual(request.full_url, "https://hub.superfastrobotics.com/catalog/v1/version.json")
        headers = {key.lower(): value for key, value in request.header_items()}
        self.assertEqual(headers["dnt"], "1")
        self.assertEqual(headers["x-rsh-telemetry"], "off")
        self.assertNotIn("authorization", headers)
        self.assertIn('sync_catalog.py --hub-commit "$HUB_COMMIT"', workflow)
        self.assertIn("HUB_COMMIT: ${{ steps.publication.outputs.hub_commit }}", workflow)

    def test_sync_runs_only_after_main_deploy_with_read_only_checkout_and_step_scoped_secret(self):
        workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/pages.yml").read_text(encoding="utf-8")
        job = workflow.split("\n  sync:\n", 1)[1]
        self.assertIn("needs: deploy", job)
        self.assertIn("github.ref == 'refs/heads/main'", job)
        self.assertIn("github.repository == 'Superfast-Robotics/robot-skill-hub'", job)
        self.assertIn("timeout-minutes: 10", job)
        self.assertIn("permissions:\n      contents: read", job)
        self.assertNotIn("pages: write", job)
        self.assertNotIn("id-token: write", job)
        self.assertIn("ref: ${{ github.sha }}", job)
        self.assertIn("persist-credentials: false", job)
        self.assertIn("CATALOG_SYNC_KEY: ${{ secrets.CATALOG_SYNC_KEY }}", job)
        self.assertNotIn("GITHUB_TOKEN:", job)


if __name__ == "__main__":
    unittest.main()
