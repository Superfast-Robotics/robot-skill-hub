"""Source files are verified inert bytes; no upstream source or real network runs."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills/find-robot-skills"
sys.path.insert(0, str(SKILL / "scripts"))
from rshlib import acquisition
from rshlib.core import RshError

COMMIT = "a" * 40
HUB = "b" * 40


def reference(body=b"print('never execute')\n", path="examples/main.py", license_info=None):
    return {"id": "fixture-source", "kind": "official_example",
            "source": {"repository": "https://github.com/example/robot", "commit": COMMIT,
                       "path": path, "url": "https://github.com/example/robot/tree/" + COMMIT + "/examples",
                       "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body), "authors": ["Fixture author"]},
            "license": license_info or {"spdx": "MIT", "url": "https://github.com/example/robot/blob/" + COMMIT + "/LICENSE", "scope": "Selected file only."},
            "access": {"mode": "source_reference", "hub_prepare": False},
            "evidence": {"runtime_verification": "not_run"}}


def catalog(record):
    return {"schema_version": "1", "hub_commit": HUB, "records": [],
            "references": {"schema_version": "1", "hub_commit": HUB, "records": [record]}}


class WireSocket:
    def __init__(self, response):
        self.response = response
        self.sent = bytearray()
        self.connected = None
        self.timeouts = []
        self.shutdowns = []

    def settimeout(self, value):
        self.timeouts.append(value)

    def connect(self, address):
        self.connected = address

    def sendall(self, data):
        self.sent.extend(data)

    def makefile(self, mode):
        return io.BytesIO(self.response)

    def shutdown(self, how):
        self.shutdowns.append(how)

    def close(self):
        pass


class SourceAcquisitionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.project = self.root / "project"

    def tearDown(self):
        self.temporary.cleanup()

    def assert_error(self, code, callable, *args, **kwargs):
        with self.assertRaises(RshError) as caught:
            callable(*args, **kwargs)
        self.assertEqual(caught.exception.result["reason_code"], code)
        return caught.exception.result

    def test_plan_is_pure_and_all_current_reference_metadata_has_a_real_file_plan(self):
        snapshot = json.loads((SKILL / "assets/references.snapshot.json").read_text(encoding="utf-8"))
        with mock.patch.object(socket, "getaddrinfo", side_effect=AssertionError("Plan must not resolve DNS")), mock.patch.object(
                Path, "mkdir", side_effect=AssertionError("Plan must not write")), mock.patch.object(acquisition, "_download", side_effect=AssertionError("No HTTP")):
            for record in snapshot["records"]:
                result = acquisition.plan_source(record, snapshot["hub_commit"])
                self.assertEqual(result["source_sha256"], record["source"]["sha256"])
                self.assertEqual(result["source_bytes"], record["source"]["bytes"])
                self.assertFalse(result["source_request_performed"])
                self.assertFalse(result["execution_performed"])
            result = acquisition.fetch_source(catalog(reference()), "fixture-source", self.project, plan=True)
        self.assertFalse(self.project.exists())
        self.assertEqual(result["fetch_args"], ["fetch-source", "fixture-source", "--expected-source-revision", COMMIT,
                                               "--expected-source-sha256", reference()["source"]["sha256"]])

    def test_types_are_copied_as_neutral_bytes_with_exact_license_and_source_provenance(self):
        cases = [("code.py", b"raise RuntimeError('not executed')\n"), ("code.cpp", b"int main() {}\n"),
                 ("SKILL.md", b"# Instructions\nDo not activate these fixture instructions.\n"),
                 ("AGENTS.md", b"Untrusted fixture instructions.\n"), ("robot.urdf", b"<robot name='fixture'/>"),
                 ("robot.yaml", b"controller: fixture\n"), ("policy.bin", b"\0\xff\x80binary fixture")]
        license_info = {"spdx": "NOASSERTION", "verified": False, "review_status": "unresolved",
                        "url": "https://example.com/LICENSE", "scope": "No clearance inferred.",
                        "source_terms": {"identifier": "FIXTURE", "notes": "Preserve complete source terms."}}
        for number, (path, body) in enumerate(cases):
            with self.subTest(path=path):
                record = reference(body, path, license_info)
                project = self.root / ("project-" + str(number))
                with mock.patch.object(acquisition, "_download", return_value=body) as download:
                    result = acquisition.fetch_source(catalog(record), record["id"], project)
                self.assertEqual(Path(result["source_file"]).name, "artifact.source")
                self.assertEqual(Path(result["source_file"]).read_bytes(), body)
                manifest = json.loads(Path(result["manifest_path"]).read_bytes())
                self.assertEqual(manifest["license"], license_info)
                self.assertEqual(manifest["source"], record["source"])
                self.assertEqual(manifest["original_path"], path)
                self.assertEqual(manifest["base"], result["base"])
                self.assertTrue(result["source_download_only"])
                self.assertTrue(result["source_download_performed"])
                self.assertTrue(result["source_request_performed"])
                self.assertFalse(result["installed_as_skill"])
                self.assertFalse(result["environment_created"])
                self.assertFalse(result["execution_performed"])
                self.assertEqual(download.call_count, 1)

    def test_custom_terms_survive_without_becoming_a_license_grant(self):
        license_info = {"spdx": "LicenseRef-Fixture-2026", "verified": False,
            "review_status": "nonstandard_upstream_terms", "scope": "Source inspection only.",
            "source_terms": {"identifier": "FIXTURE-2026", "marker": "Fixture terms", "notes": "Terms apply."}}
        record = reference(license_info=license_info)
        with mock.patch.object(acquisition, "_download", return_value=b"print('never execute')\n"):
            result = acquisition.fetch_source(catalog(record), record["id"], self.project)
        self.assertEqual(result["license"], license_info)
        self.assertEqual(json.loads(Path(result["manifest_path"]).read_bytes())["license"], license_info)
        self.assertFalse(result["hub_prepare"])

    def test_standalone_and_non_github_revision_urls_are_genuinely_supported(self):
        body = b"standalone source fixture"
        for revision, url in [("sha256:" + hashlib.sha256(body).hexdigest(), "https://example.com/files/source.bin"),
                              (COMMIT, "https://example.com/repository/" + COMMIT + "/source.bin")]:
            record = reference(body, "source.bin")
            record["source"].pop("commit")
            record["source"].update(repository="https://example.com/repository", revision=revision, url=url)
            project = self.root / hashlib.sha256(url.encode()).hexdigest()
            with mock.patch.object(acquisition, "_download", return_value=body) as download:
                result = acquisition.fetch_source(catalog(record), record["id"], project)
            self.assertEqual(download.call_args.args[0], url)
            self.assertEqual(result["base"]["source_commit"], revision)
            self.assertEqual(Path(result["source_file"]).read_bytes(), body)

    def test_invalid_pins_paths_sizes_and_raw_url_binding_fail_before_network_or_writes(self):
        mutations = [("invalid_source_pin", {"sha256": "A" * 64}), ("invalid_source_pin", {"commit": "main"}),
                     ("invalid_source_path", {"path": "../other.py"}), ("invalid_source_path", {"path": "/other.py"}),
                     ("invalid_source_path", {"path": "a\\other.py"}), ("invalid_source_size", {"bytes": True}),
                     ("invalid_source_size", {"bytes": 0}), ("invalid_source_size", {"bytes": 1.5}),
                     ("invalid_source_size", {"bytes": 2 ** 53}), ("source_too_large", {"bytes": acquisition.MAX_SOURCE_BYTES + 1}),
                     ("source_url_pin_mismatch", {"raw_url": "https://example.com/other.py"})]
        with mock.patch.object(acquisition, "_download") as download, mock.patch.object(socket, "getaddrinfo") as dns:
            for code, change in mutations:
                record = reference()
                record["source"].update(change)
                with self.subTest(change=change):
                    error = self.assert_error(code, acquisition.fetch_source, catalog(record), record["id"], self.project)
                    self.assertFalse(error["source_request_performed"])
            record = reference()
            self.assert_error("selected_source_changed", acquisition.fetch_source, catalog(record), record["id"], self.project,
                              expected_source_sha256="f" * 64)
            self.assert_error("selected_source_changed", acquisition.fetch_source, catalog(record), record["id"], self.project,
                              expected_source_revision="f" * 40)
        download.assert_not_called()
        dns.assert_not_called()
        self.assertFalse(self.project.exists())

    def test_content_revision_and_non_github_commit_segment_must_bind_exactly(self):
        record = reference()
        record["source"].pop("commit")
        record["source"].update(repository="https://example.com/repo", revision="sha256:" + "f" * 64, url="https://example.com/source.py")
        self.assert_error("invalid_source_pin", acquisition.plan_source, record, HUB)
        record["source"]["revision"] = COMMIT
        record["source"]["url"] = "https://example.com/repo/prefix" + COMMIT + "/source.py"
        self.assert_error("source_url_pin_mismatch", acquisition.plan_source, record, HUB)

    def test_recipes_are_referred_to_prepare_without_acquiring_an_archive(self):
        recipe = {"id": "fixture-source", "source": {"archive_sha256": "f" * 64}, "preparation": {}}
        with mock.patch.object(acquisition, "_download") as download:
            result = self.assert_error("source_is_preparation_recipe", acquisition.fetch_source,
                                       {"records": [recipe], "hub_commit": HUB}, recipe["id"], self.project)
        self.assertEqual(result["next_action"], "use_prepare")
        download.assert_not_called()

    def test_unsafe_urls_and_embedded_credentials_are_not_echoed(self):
        for url in ["https://localhost/source", "https://127.0.0.1/source", "https://[::1]/source", "https://169.254.169.254/source",
                    "https://private.local/source", "https://user:private-value@example.com/source", "https://example.com/file#fragment",
                    "https://example.com/file?token=private-value", "https://example.com/%0d%0aheader"]:
            record = reference()
            record["source"]["url"] = url
            with self.subTest(url=url):
                error = self.assert_error("unsafe_source_url", acquisition.plan_source, record, HUB)
                self.assertNotIn("private-value", json.dumps(error))

    def test_offline_cache_is_verified_without_dns_and_preserves_original_hub_base(self):
        body = b"print('never execute')\n"
        record = reference(body)
        with mock.patch.object(acquisition, "_download", return_value=body):
            first = acquisition.fetch_source(catalog(record), record["id"], self.project)
        original = Path(first["manifest_path"]).read_bytes()
        newer = catalog(record)
        newer["hub_commit"] = newer["references"]["hub_commit"] = "c" * 40
        with mock.patch.object(socket, "getaddrinfo", side_effect=AssertionError("No DNS for cache")), mock.patch.object(
                acquisition, "_download", side_effect=AssertionError("No HTTP for cache")):
            second = acquisition.fetch_source(newer, record["id"], self.project, offline=True)
            self.assert_error("source_unavailable_offline", acquisition.fetch_source, catalog(record), record["id"], self.root / "absent", offline=True)
        self.assertEqual(second["base"]["hub_commit"], HUB)
        self.assertEqual(second["selected_base"]["hub_commit"], "c" * 40)
        self.assertEqual(Path(second["manifest_path"]).read_bytes(), original)
        self.assertTrue(second["cache_reused"])
        self.assertFalse(second["source_request_performed"])
        self.assertFalse(second["source_download_performed"])

    def test_cache_tampering_or_license_context_change_never_overwrites(self):
        record = reference()
        with mock.patch.object(acquisition, "_download", return_value=b"print('never execute')\n"):
            first = acquisition.fetch_source(catalog(record), record["id"], self.project)
        path = Path(first["source_file"])
        path.write_bytes(b"corrupt")
        with mock.patch.object(acquisition, "_download") as download:
            self.assert_error("source_cache_conflict", acquisition.fetch_source, catalog(record), record["id"], self.project)
        self.assertEqual(path.read_bytes(), b"corrupt")
        download.assert_not_called()
        changed = copy.deepcopy(record)
        changed["license"]["scope"] = "A separately reviewed license context"
        self.assertNotEqual(acquisition.plan_source(record, HUB)["acquisition_id"], acquisition.plan_source(changed, HUB)["acquisition_id"])

    def test_failure_before_atomic_publish_never_marks_partial_directory_ready(self):
        record = reference()
        with mock.patch.object(acquisition, "_download", return_value=b"print('never execute')\n"), mock.patch.object(
                acquisition, "_write_exclusive", side_effect=OSError("private filesystem error")):
            error = self.assert_error("source_acquisition_failed", acquisition.fetch_source, catalog(record), record["id"], self.project)
        identity = acquisition.plan_source(record, HUB)["acquisition_id"]
        self.assertFalse((self.project / ".robot-skill-hub/source-files" / identity).exists())
        self.assertTrue(error["source_request_performed"])
        self.assertTrue(error["source_download_performed"])
        self.assertNotIn("private filesystem", json.dumps(error))
        self.assertEqual(list((self.project / ".robot-skill-hub/source-files").iterdir()), [])

    def test_concurrent_complete_target_is_reused_and_empty_target_is_never_replaced(self):
        record = reference()
        real_publish = acquisition._publish_directory
        def competing_winner(staging, target):
            target.mkdir()
            for name in (acquisition.ARTIFACT_NAME, acquisition.MANIFEST_NAME):
                (target / name).write_bytes((staging / name).read_bytes())
            real_publish(staging, target)
        with mock.patch.object(acquisition, "_download", return_value=b"print('never execute')\n"), mock.patch.object(
                acquisition, "_publish_directory", side_effect=competing_winner):
            result = acquisition.fetch_source(catalog(record), record["id"], self.project)
        self.assertTrue(result["cache_reused"])
        self.assertTrue(result["source_request_performed"])
        self.assertTrue(result["source_download_performed"])
        other = self.root / "other"
        def empty_target(staging, target):
            target.mkdir()
            real_publish(staging, target)
        with mock.patch.object(acquisition, "_download", return_value=b"print('never execute')\n"), mock.patch.object(
                acquisition, "_publish_directory", side_effect=empty_target):
            self.assert_error("source_cache_conflict", acquisition.fetch_source, catalog(record), record["id"], other)
        target = other / ".robot-skill-hub/source-files" / acquisition.plan_source(record, HUB)["acquisition_id"]
        self.assertTrue(target.is_dir())
        self.assertEqual(list(target.iterdir()), [])

    def test_symlinked_managed_path_and_artifact_are_never_followed(self):
        external = self.root / "external"
        external.mkdir()
        self.project.mkdir()
        link = self.project / ".robot-skill-hub"
        try:
            link.symlink_to(external, target_is_directory=True)
        except OSError:
            self.skipTest("Symlink creation requires unavailable Windows privileges")
        with mock.patch.object(acquisition, "_download") as download:
            self.assert_error("source_path_escape", acquisition.fetch_source, catalog(reference()), "fixture-source", self.project)
        download.assert_not_called()
        self.assertEqual(list(external.iterdir()), [])
        link.unlink()
        with mock.patch.object(acquisition, "_download", return_value=b"print('never execute')\n"):
            first = acquisition.fetch_source(catalog(reference()), "fixture-source", self.project)
        path = Path(first["source_file"])
        path.unlink()
        outside = external / "data"
        outside.write_bytes(b"print('never execute')\n")
        path.symlink_to(outside)
        with mock.patch.object(acquisition, "_download") as download:
            self.assert_error("source_cache_conflict", acquisition.fetch_source, catalog(reference()), "fixture-source", self.project)
        download.assert_not_called()

    def transport(self, body, *, status=200, headers=None, dns=None, callback=None):
        headers = {"Content-Length": str(len(body)), **(headers or {})}
        response = (f"HTTP/1.1 {status} Fixture\r\n" + "".join(f"{key}: {value}\r\n" for key, value in headers.items()) + "\r\n").encode() + body
        wire = WireSocket(response)
        context = mock.Mock()
        context.wrap_socket.return_value = wire
        answers = dns or [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 443))]
        with mock.patch.object(socket, "getaddrinfo", return_value=answers) as resolver, mock.patch.object(
                socket, "socket", return_value=wire) as sockets, mock.patch.object(acquisition.ssl, "create_default_context", return_value=context), mock.patch.dict(
                os.environ, {"HTTPS_PROXY": "https://proxy.invalid", "RSH_SUBMISSION_TOKEN": "do-not-send", "GITHUB_TOKEN": "do-not-send"}):
            result = callback(wire, context, resolver, sockets) if callback else acquisition._download(
                "https://example.com/pinned/file", len(body), hashlib.sha256(body).hexdigest())
        return result, wire, context, resolver, sockets

    def test_real_http_parser_uses_validated_ip_original_tls_host_and_no_credentials(self):
        body = b"public source fixture"
        result, wire, context, resolver, sockets = self.transport(body)
        self.assertEqual(result, body)
        self.assertEqual(wire.connected, ("93.184.216.34", 443))
        self.assertEqual(resolver.call_count, 1)
        sockets.assert_called_once_with(socket.AF_INET, socket.SOCK_STREAM)
        context.wrap_socket.assert_called_once_with(wire, server_hostname="example.com")
        sent = bytes(wire.sent).decode("ascii")
        self.assertIn("GET /pinned/file HTTP/1.1\r\n", sent)
        self.assertIn("Host: example.com\r\n", sent)
        self.assertIn("DNT: 1\r\n", sent)
        self.assertIn("X-RSH-Telemetry: off\r\n", sent)
        for forbidden in ("Authorization", "Cookie", "Proxy-", "do-not-send", "proxy.invalid"):
            self.assertNotIn(forbidden, sent)
        self.assertTrue(all(0 < timeout <= acquisition.SOCKET_TIMEOUT for timeout in wire.timeouts))

    def test_connection_close_responses_stream_through_real_socket_files(self):
        # Unlike the BytesIO wire, socket.makefile keeps a real descriptor alive
        # after socket.close, then closes it when HTTPResponse finishes its body.
        # Exercise that lifetime for both exact-length and EOF-delimited replies.
        body = b"source bytes with a server-close response"
        for framing in (b"Content-Length: " + str(len(body)).encode() + b"\r\n", b""):
            with self.subTest(framing=framing):
                client, server = socket.socketpair()

                class ConnectedWire:
                    def connect(self, address):
                        self.connected = address  # The socketpair is already connected locally.

                    def __getattr__(self, name):
                        return getattr(client, name)

                wire = ConnectedWire()
                server.sendall(b"HTTP/1.1 200 OK\r\nConnection: close\r\n" + framing + b"\r\n" + body)
                server.shutdown(socket.SHUT_WR)
                context = mock.Mock()
                context.wrap_socket.return_value = wire
                responses = []
                response_type = acquisition.http.client.HTTPResponse

                def response(*args, **kwargs):
                    result = response_type(*args, **kwargs)
                    responses.append(result)
                    return result

                try:
                    with mock.patch.object(socket, "getaddrinfo", return_value=[(
                            socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 443))]), mock.patch.object(
                            socket, "socket", return_value=wire), mock.patch.object(acquisition.ssl, "create_default_context", return_value=context), mock.patch.object(
                            acquisition.http.client, "HTTPResponse", side_effect=response):
                        result = acquisition._download("https://example.com/source", len(body), hashlib.sha256(body).hexdigest())
                    self.assertEqual(body, result)
                    self.assertEqual(("93.184.216.34", 443), wire.connected)
                    self.assertEqual(-1, client.fileno())
                    self.assertEqual(1, len(responses))
                    self.assertTrue(all(item.isclosed() for item in responses))
                    self.assertIn(b"Connection: close\r\n", server.recv(8192))
                finally:
                    client.close()
                    server.close()

    def test_private_or_mixed_dns_and_dns_failure_never_start_a_source_request(self):
        for addresses in [["127.0.0.1"], ["10.0.0.1"], ["169.254.169.254"], ["93.184.216.34", "192.168.1.2"]]:
            answers = [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, 443)) for address in addresses]
            with self.subTest(addresses=addresses), mock.patch.object(socket, "getaddrinfo", return_value=answers), mock.patch.object(socket, "socket") as connect:
                error = self.assert_error("private_source_address", acquisition._download, "https://example.com/source", 1, "f" * 64)
                self.assertFalse(error["source_request_performed"])
                connect.assert_not_called()
        with mock.patch.object(socket, "getaddrinfo", side_effect=socket.gaierror("private resolver detail")):
            error = self.assert_error("source_dns_unavailable", acquisition.fetch_source, catalog(reference()), "fixture-source", self.project)
        self.assertIs(error["source_request_performed"], False)
        self.assertNotIn("private resolver", json.dumps(error))

    def test_redirect_bad_status_size_hash_and_encoding_fail_with_known_request_state(self):
        cases = [(302, {}, "source_redirect_refused"), (403, {}, "source_http_error"),
                 (200, {"Content-Length": "999999999"}, "source_size_mismatch"),
                 (200, {"Content-Encoding": "gzip"}, "source_encoding_unsupported")]
        for status, headers, code in cases:
            with self.subTest(code=code):
                def check(*unused):
                    return self.assert_error(code, acquisition._download, "https://example.com/source", 3, hashlib.sha256(b"abc").hexdigest())
                result, wire, *_ = self.transport(b"abc", status=status, headers=headers, callback=check)
                self.assertTrue(result["source_request_performed"])
                self.assertEqual(bytes(wire.sent).count(b"GET "), 1)
        def wrong_hash(*unused):
            return self.assert_error("source_hash_mismatch", acquisition._download, "https://example.com/source", 3, "f" * 64)
        result, *_ = self.transport(b"abc", callback=wrong_hash)
        self.assertTrue(result["source_request_performed"])

    def test_body_size_is_bounded_even_without_content_length(self):
        wire = WireSocket(b"HTTP/1.1 200 OK\r\nConnection: close\r\n\r\nabcdef")
        context = mock.Mock()
        context.wrap_socket.return_value = wire
        with mock.patch.object(socket, "getaddrinfo", return_value=[(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 443))]), mock.patch.object(
                socket, "socket", return_value=wire), mock.patch.object(acquisition.ssl, "create_default_context", return_value=context):
            error = self.assert_error("source_size_mismatch", acquisition._download, "https://example.com/source", 3, "f" * 64)
        self.assertTrue(error["source_request_performed"])

    def test_total_deadline_has_a_socket_interrupt_watchdog(self):
        body = b"abc"
        with mock.patch.object(acquisition.threading, "Timer") as timer:
            result, wire, *_ = self.transport(body)
        self.assertEqual(result, body)
        self.assertEqual(timer.call_args.args[0], acquisition.TRANSFER_TIMEOUT)
        timer.return_value.start.assert_called_once()
        timer.return_value.cancel.assert_called_once()
        timer.call_args.args[1]()
        self.assertEqual(wire.shutdowns, [socket.SHUT_RDWR])


if __name__ == "__main__":
    unittest.main()
