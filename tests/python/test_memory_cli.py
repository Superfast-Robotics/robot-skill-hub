"""Local-first memory delivery and public discovery contracts, without live writes."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from test_rsh import fixture_catalog, HUB, PIN, ROOT, SKILL
from rshlib import contributions, discovery, memories
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
        self.env = mock.patch.dict(os.environ, {"RSH_SUBMISSION_TOKEN": "test-scoped-token", "RSH_API_URL": "https://api.example.test"})
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

    def test_patch_permission_and_token_do_not_grant_memory_sharing(self):
        (self.project / ".robot-skill-hub.json").write_text(json.dumps({"publication": {"public_submission_allowed": True}}))
        # This file is deliberately outside the explicit finding; the command must not scan it.
        (self.project / "private-project-data.txt").write_text("private research data")
        with mock.patch.object(contributions, "request_json") as network:
            result = self.save()
        self.assertEqual(result["status"], "local_saved")
        self.assertFalse(result["network_performed"])
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
                network.assert_not_called()
        self.policy()
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(contributions, "request_json") as network:
            result = memories.flush(self.project)
        self.assertFalse(result["network_performed"])
        network.assert_not_called()
        self.assertFalse(memories.allowed({"memory": {"public_save_allowed": True}}, "fixture-pick", "missing_requirement"))

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
            self.assertEqual(authorization, "Bearer test-scoped-token")
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
