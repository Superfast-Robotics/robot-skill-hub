"""Selection recall is bounded, data-only and cannot break the selected record."""
from contextlib import redirect_stdout
import io
import json
import os
import runpy
import tempfile
import time
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

from test_rsh import fixture_catalog, failed_attempt, HUB, PIN, SKILL
from test_memory_cli import finding, reference_catalog
from rshlib import contributions, discovery, memories


def published(catalog=None, skill_id="fixture-pick", **changes):
    catalog = catalog or fixture_catalog()
    base, _ = memories.base_for(catalog, skill_id)
    payload = {"schema_version": "1", "skill_id": skill_id, "base": base,
               **memories.normalize_finding(finding()), "publication": {"public_submission_allowed": True}}
    payload.update(changes)
    return {**payload, "fingerprint": memories.fingerprint(payload), "memory_id": "mem_" + "1" * 64,
            "content_sha256": "e" * 64, "curation": "maintainer_merged", "interpretation": "data_only"}


class SelectionFindingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, {"RSH_CACHE_DIR": str(self.root / "cache"), "RSH_TELEMETRY": "off"})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def cli(self, args, catalog=None):
        cli = runpy.run_path(str(SKILL / "scripts/rsh.py"), run_name="selection_test")
        path = self.root / "catalog.json"
        path.write_text(json.dumps(catalog or fixture_catalog()), encoding="utf-8")
        output = io.StringIO()
        with redirect_stdout(output):
            code = cli["main"]([*args, "--catalog", str(path), "--json"])
        return code, json.loads(output.getvalue())

    def index(self, records, **changes):
        return {"schema_version": "1", "hub_commit": HUB, "coverage": {"complete": True},
                "records": records, **changes}

    def test_inspect_automatically_recalls_exact_version_without_credentials_or_project(self):
        entry = published()
        with mock.patch.object(memories, "public_index", return_value=(self.index([entry]), "cache")), \
                mock.patch.object(memories, "_remote_findings", side_effect=OSError()), \
                mock.patch.object(contributions, "api_configuration", side_effect=AssertionError("credential access")):
            code, detail = self.cli(["inspect", "fixture-pick", "--offline"])
        self.assertEqual((code, detail["status"]), (0, "ready"))
        recalled = detail["findings"]
        self.assertEqual(recalled["status"], "ready")
        self.assertEqual(recalled["total"], 1)
        self.assertEqual(recalled["results"][0]["memory_id"], entry["memory_id"])
        self.assertEqual(recalled["applicability"], "needs_applicability_check")
        self.assertEqual(recalled["environment_filter"], {})
        self.assertFalse((self.root / "cache").exists())

    def test_explicit_environment_only_and_wrong_source_or_version_is_excluded(self):
        first = published()
        variants = [first, published(base={**first["base"], "source_commit": "f" * 40}),
                    published(base={**first["base"], "record_version": "2.0.0"}),
                    published(environment={"runtime": "fixture", "robot": "ur5"})]
        with mock.patch.object(memories, "public_index", return_value=(self.index(variants), "cache")):
            _, detail = self.cli(["inspect", "fixture-pick", "--offline", "--robot", "panda"])
        self.assertEqual(detail["findings"]["total"], 1)
        self.assertEqual(detail["findings"]["environment_filter"], {"robot": "panda"})
        self.assertEqual(detail["findings"]["applicability"], "needs_applicability_check")

    def test_online_inspect_reads_one_anonymous_exact_pin_page(self):
        entry = published()
        page = {"schema_version": "1", "interpretation": "data_only", "execution_performed": False,
                "hub_commit": HUB, "results": [entry], "total": 1, "limit": 3, "offset": 0,
                "next": None, "coverage": {"complete": True}}
        with mock.patch.object(discovery, "fetch_public", return_value=page) as http, \
                mock.patch.object(memories, "public_index", side_effect=AssertionError("unexpected aggregate")), \
                mock.patch.object(contributions, "api_configuration", side_effect=AssertionError("credential access")):
            code, detail = self.cli(["inspect", "fixture-pick", "--robot", "panda"])
        self.assertEqual((code, detail["findings"]["index_origin"]), (0, "remote_api"))
        self.assertEqual(http.call_count, 1)
        url = urllib.parse.urlsplit(http.call_args.args[0])
        self.assertEqual((url.scheme, url.netloc, url.path), ("https", "api.superfastrobotics.com", "/v1/findings"))
        self.assertEqual(urllib.parse.parse_qs(url.query), {"skill_id": ["fixture-pick"], "record_version": ["1.0.0"],
            "source_commit": [PIN], "robot": ["panda"], "limit": ["3"], "offset": ["0"], "hub_commit": [HUB]})

    def test_unavailable_stale_incomplete_or_malformed_does_not_claim_absence(self):
        invalid = {**published(), "fingerprint": "broken"}
        cases = [(self.index([]), "empty_snapshot"),
                 (self.index([], hub_commit="f" * 40), "cache"),
                 (self.index([], coverage={"complete": False}), "cache"),
                 (self.index([invalid]), "cache"), (self.index([published(), published()]), "cache")]
        for index, origin in cases:
            with self.subTest(origin=origin, index=index), \
                    mock.patch.object(memories, "public_index", return_value=(index, origin)):
                code, detail = self.cli(["inspect", "fixture-pick", "--offline"])
            self.assertEqual((code, detail["status"]), (0, "ready"))
            self.assertEqual(detail["findings"]["status"], "unknown")
            self.assertIsNone(detail["findings"]["total"])
            self.assertEqual(detail["findings"]["coverage"], {"complete": False})
            self.assertTrue(detail["findings"]["reason_code"])

    def test_duplicate_remote_page_is_rejected_directly_and_not_trusted_from_cache(self):
        entry = published()
        page = {"schema_version": "1", "interpretation": "data_only", "execution_performed": False,
                "hub_commit": HUB, "results": [entry, entry], "total": 2, "limit": 3, "offset": 0,
                "next": None, "coverage": {"complete": True}}
        with self.assertRaises(memories.RshError) as error:
            memories._finding_page(page, "fixture-pick", entry["base"], {}, 3, 0, HUB)
        self.assertEqual(error.exception.result["reason_code"], "invalid_public_findings")
        with mock.patch.object(discovery, "_read_cache", return_value={"data": page, "fetched_at": time.time()}), \
                mock.patch.object(discovery, "fetch_public", side_effect=OSError("offline fixture")) as http, \
                mock.patch.object(discovery, "_write_cache") as write:
            with self.assertRaises(OSError):
                memories._remote_findings("fixture-pick", entry["base"], {}, 3, 0, HUB, False)
        self.assertEqual(http.call_count, 1)
        write.assert_not_called()

    def test_duplicate_remote_inspect_preserves_record_and_unknown_when_fallback_is_incomplete(self):
        entry = published()
        page = {"schema_version": "1", "interpretation": "data_only", "execution_performed": False,
                "hub_commit": HUB, "results": [entry, entry], "total": 2, "limit": 3, "offset": 0,
                "next": None, "coverage": {"complete": True}}
        fallback = self.index([], coverage={"complete": False})
        with mock.patch.object(discovery, "fetch_public", return_value=page) as http, \
                mock.patch.object(memories, "public_index", return_value=(fallback, "bundled_snapshot")), \
                mock.patch.object(discovery, "_write_cache") as write:
            code, detail = self.cli(["inspect", "fixture-pick"])
        self.assertEqual((code, detail["status"]), (0, "ready"))
        self.assertEqual(detail["source"]["commit"], PIN)
        self.assertEqual(detail["findings"]["status"], "unknown")
        self.assertEqual(detail["findings"]["reason_code"], "findings_coverage_unknown")
        self.assertIsNone(detail["findings"]["total"])
        self.assertEqual(detail["findings"]["coverage"], {"complete": False})
        self.assertEqual(http.call_count, 1)
        write.assert_not_called()

    def test_invalid_environment_never_queries_or_echoes_private_extra_fields(self):
        path = self.root / "environment.json"
        path.write_text(json.dumps({"private_path": "do-not-transmit", "robot": "panda"}), encoding="utf-8")
        with mock.patch.object(memories, "query", side_effect=AssertionError("invalid environment lookup")) as lookup:
            code, detail = self.cli(["inspect", "fixture-pick", "--environment", str(path), "--offline"])
        self.assertEqual((code, detail["status"]), (0, "ready"))
        self.assertEqual(detail["findings"]["reason_code"], "invalid_environment")
        self.assertNotIn("do-not-transmit", json.dumps(detail))
        lookup.assert_not_called()

    def test_first_page_is_bounded_and_keeps_next_coverage_and_failed_attempt(self):
        catalog = fixture_catalog()
        attempt = failed_attempt()
        catalog["records"][0]["evidence"].update(level="import_verified", runtime_verification="import_verified",
            artifacts=["https://example.test/immutable/attempt.json"],
            hub_verification={"level": "import_verified", "runtime": "import_verified", "last_task_attempt": attempt})
        records = [{**published(), "memory_id": "mem_" + str(i) * 64} for i in range(1, 6)]
        with mock.patch.object(memories, "public_index", return_value=(self.index(records), "cache")):
            _, detail = self.cli(["inspect", "fixture-pick", "--offline"], catalog)
        self.assertEqual(detail["last_task_attempt"], attempt)
        self.assertEqual(len(detail["findings"]["results"]), 3)
        self.assertEqual(detail["findings"]["total"], 5)
        self.assertEqual(detail["findings"]["next"]["offset"], 3)
        self.assertEqual(detail["findings"]["coverage"], {"complete": True})

    def test_source_reference_uses_source_digest_version_and_find_stays_lookup_free(self):
        catalog = reference_catalog()
        catalog["references"]["hub_commit"] = HUB
        entry = published(catalog, "pybullet-ik")
        with mock.patch.object(memories, "public_index", return_value=(self.index([entry]), "cache")):
            _, detail = self.cli(["inspect", "pybullet-ik", "--offline"], catalog)
        self.assertEqual(detail["findings"]["base"]["record_version"], "source-" + "e" * 64)
        with mock.patch.object(memories, "query", side_effect=AssertionError("search fan-out")):
            code, result = self.cli(["find", "pick", "--offline"])
        self.assertEqual(code, 0)
        self.assertNotIn("findings", result)

    def test_prepare_plan_has_no_added_recall_network_or_project_write(self):
        project = self.root / "never-created"
        with mock.patch.object(memories, "query", side_effect=AssertionError("plan recall")), \
                mock.patch.object(discovery, "fetch_public", side_effect=AssertionError("HTTP")):
            _, result = self.cli(["prepare", "fixture-pick", "--project", str(project), "--plan", "--offline"])
        self.assertIn(result["status"], ("ready", "needs_configuration"))
        self.assertFalse(project.exists())
        self.assertNotIn("findings", result)


if __name__ == "__main__":
    unittest.main()
