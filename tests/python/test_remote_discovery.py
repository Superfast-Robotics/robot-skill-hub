"""Bounded online reads preserve source identity, project pins and local fallback."""
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills/find-robot-skills/scripts"))
from rshlib import core, discovery, memories, remote_catalog
from test_rsh import fixture_catalog, HUB, PIN
from test_memory_cli import finding

rsh = importlib.import_module("rsh")


def search_page():
    record = fixture_catalog()["records"][0]
    row = {"id": record["id"], "name": record["name"], "summary": record["summary"],
           "kind": "preparation_recipe", "hub_prepare": True, "record_version": "1.0.0",
           "source_commit": PIN, "source_sha256": record["source"]["archive_sha256"], "record_sha256": "c" * 64,
           "compatibility": record["compatibility"], "python_requirement": record["requirements"]["python"]}
    return {"schema_version": "1", "hub_commit": HUB, "results": [row], "total": 1,
            "offset": 0, "limit": 3, "next": None, "backend": "d1", "execution_performed": False, "coverage": {"complete": True}}


def finding_page():
    payload = {"schema_version": "1", "skill_id": "fixture-pick", "base": {
        "hub_commit": HUB, "record_version": "1.0.0", "source_commit": PIN},
        **memories.normalize_finding(finding()), "publication": {"public_submission_allowed": True}}
    row = {**payload, "memory_id": "mem_" + "d" * 64, "content_sha256": "e" * 64,
           "fingerprint": memories.fingerprint(payload), "curation": "maintainer_merged", "interpretation": "data_only"}
    return {"schema_version": "1", "hub_commit": HUB, "interpretation": "data_only", "execution_performed": False,
            "coverage": {"complete": True}, "limit": 20, "offset": 0, "results": [row], "total": 1, "next": None}


class RemoteDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.env = mock.patch.dict(os.environ, {"RSH_CACHE_DIR": self.temporary.name, "RSH_TELEMETRY": "off"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def args(self, *argv):
        return rsh.build_parser().parse_args(argv)

    def test_find_downloads_only_one_bounded_query_without_global_catalog(self):
        with mock.patch.object(discovery, "fetch_public", return_value=search_page()) as fetch, mock.patch.object(rsh, "load_discovery", side_effect=AssertionError("whole catalog read")):
            result = rsh.execute(self.args("find", "pick"), None)
        self.assertEqual(result["results"][0]["memory_base"], {"hub_commit": HUB, "record_version": "1.0.0", "source_commit": PIN})
        self.assertEqual(result["discovery_scope"], "complete_public_query")
        self.assertEqual(fetch.call_count, 1)
        self.assertTrue(fetch.call_args.args[0].startswith(discovery.API_BASE + "search?"))
        self.assertEqual(fetch.call_args.kwargs["max_bytes"], 512 * 1024)

    def test_inspect_uses_one_selected_record_and_its_individual_offline_cache(self):
        value = {"schema_version": "1", "hub_commit": HUB, "record": fixture_catalog()["records"][0]}
        with mock.patch.object(discovery, "fetch_public", return_value=value) as fetch, mock.patch.object(rsh, "load_discovery", side_effect=AssertionError("whole catalog read")):
            online = rsh.execute(self.args("inspect", "fixture-pick"), None)
            offline = rsh.execute(self.args("--offline", "inspect", "fixture-pick"), None)
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(online["memory_base"], offline["memory_base"])
        self.assertEqual(offline["catalog_origin"], "api_cache")
        self.assertEqual(offline["discovery_scope"], "selected_record")

    def test_online_search_preserves_robot_type_labels_without_inventing_compatibility(self):
        page = search_page()
        page["results"][0].update(id="h1-locomotion", name="H1 locomotion", summary="Pinned locomotion source",
                                  kind="source_reference", hub_prepare=False, robot_types=["humanoid"],
                                  framework="isaaclab", robots=["h1"], compatibility=[],
                                  record_version="source-" + "d" * 64, source_sha256="d" * 64)
        with mock.patch.object(discovery, "fetch_public", return_value=page) as fetch:
            result = remote_catalog.search("humanoid locomotion", {})
        self.assertEqual(1, fetch.call_count)
        self.assertEqual(["humanoid"], result["results"][0]["robot_types"])
        self.assertEqual("unknown", result["results"][0]["compatibility_status"])
        self.assertFalse(result["results"][0]["hub_prepare"])
        for environment in ({"robot": "humanoid"}, {"runtime": "isaaclab", "robot": "h1"}, {"os": "linux"}):
            with self.subTest(environment=environment), mock.patch.object(discovery, "fetch_public", return_value=page):
                with self.assertRaises(core.RshError):
                    remote_catalog.search("humanoid locomotion", environment, refresh=True)

    def test_malformed_robot_type_labels_do_not_poison_the_online_query_cache(self):
        for types in ("humanoid", [None], [""], ["x" * 81]):
            page = search_page()
            page["results"][0]["robot_types"] = types
            with self.subTest(types=types), mock.patch.object(discovery, "fetch_public", return_value=page):
                with self.assertRaises(core.RshError):
                    remote_catalog.search("humanoid locomotion", {}, refresh=True)
        self.assertFalse(list(Path(self.temporary.name).glob("api-search-*.json")))

    def test_register_reads_only_generation_metadata_without_source_inventory(self):
        with mock.patch.object(discovery, "fetch_public", return_value={"schema_version": "1", "hub_commit": HUB}) as fetch, mock.patch.object(rsh.intake, "register", return_value={"status": "ready"}) as register, mock.patch.object(rsh, "load_discovery", side_effect=AssertionError("whole catalog read")):
            rsh.execute(self.args("register", "new-source.json", "--project", self.temporary.name, "--contributor", "fixture", "--draft"), None)
        self.assertEqual(fetch.call_args.args[0], discovery.BASE + "version.json")
        self.assertEqual(register.call_args.args[0]["records"], [])
        self.assertEqual(register.call_args.args[0]["discovery_scope"], "generation_metadata")

    def test_project_lock_wins_before_any_remote_read_and_keeps_exact_version(self):
        project = Path(self.temporary.name) / "project"
        lock_path = project / ".robot-skill-hub/locks/fixture-pick.json"
        lock_path.parent.mkdir(parents=True)
        lock_path.write_text(json.dumps({"skill_id": "fixture-pick", "hub_commit": HUB, "source_commit": PIN,
                                         "record_version": "1.0.0", "record": fixture_catalog()["records"][0]}))
        original = lock_path.read_bytes()
        with mock.patch.object(remote_catalog, "selected_catalog", side_effect=AssertionError("remote refresh of existing lock")), mock.patch.object(rsh, "load_discovery", side_effect=AssertionError("whole catalog read")), mock.patch.object(rsh, "prepare", return_value={"status": "ready"}) as prepare:
            rsh.execute(self.args("prepare", "fixture-pick", "--project", str(project), "--plan", "--expected-source-commit", PIN, "--expected-record-version", "1.0.0"), None)
        self.assertEqual(prepare.call_args.args[0]["catalog_origin"], "project_lock")
        self.assertEqual(lock_path.read_bytes(), original)

    def test_malformed_search_pagination_cannot_poison_query_cache(self):
        value = search_page()
        value.update(total=5, next={"hub_commit": "f" * 40, "offset": 3, "limit": 3})
        with mock.patch.object(discovery, "fetch_public", return_value=value):
            with self.assertRaises(core.RshError):
                remote_catalog.search("pick", {})
        self.assertFalse(list(Path(self.temporary.name).glob("api-search-*.json")))

    def test_search_rejects_ignored_python_constraint_and_preserves_stale_cache_origin(self):
        with mock.patch.object(discovery, "fetch_public", return_value=search_page()):
            with self.assertRaises(core.RshError):
                remote_catalog.search("pick", {"python": "2.7"})
            first = remote_catalog.search("pick", {})
        with mock.patch.object(discovery, "fetch_public", side_effect=OSError("unavailable")):
            stale = remote_catalog.search("pick", {}, refresh=True)
        self.assertEqual(first["catalog_hub_commit"], stale["catalog_hub_commit"])
        self.assertEqual(stale["catalog_origin"], "api_cache_fallback")

    def test_search_rejects_partial_coverage_changed_filters_duplicate_ids_and_missing_requirements(self):
        partial = search_page()
        partial["coverage"]["complete"] = False
        changed_next = search_page()
        changed_next.update(total=4, next={"q": "different", "limit": 3, "offset": 3, "hub_commit": HUB})
        changed_next["results"] = [dict(changed_next["results"][0], id="fixture-" + str(index)) for index in range(3)]
        duplicate = search_page()
        duplicate.update(total=2, results=duplicate["results"] * 2)
        requirement = search_page()
        del requirement["results"][0]["python_requirement"]
        malformed_combos = search_page()
        malformed_combos["results"][0]["compatibility"] = [None]
        for value in (partial, changed_next, duplicate, requirement, malformed_combos):
            with self.subTest(value=value), mock.patch.object(discovery, "fetch_public", return_value=value):
                with self.assertRaises(core.RshError):
                    remote_catalog.search("pick", {"python": "3.10"}, refresh=True)
        self.assertFalse(list(Path(self.temporary.name).glob("api-search-*.json")))

    def test_findings_null_coverage_fails_closed_without_attribute_error(self):
        page = finding_page()
        page["coverage"] = None
        with self.assertRaises(core.RshError):
            memories._finding_page(page, "fixture-pick", page["results"][0]["base"], {}, 20, 0, None)

    def test_failure_reports_fallback_and_respects_explicit_coverage(self):
        fallback = {**fixture_catalog(), "coverage": {"complete": False, "total_records": 100, "included_records": 1}}
        with mock.patch.object(remote_catalog, "search", side_effect=OSError()), mock.patch.object(rsh, "load_discovery", return_value=fallback):
            result = rsh.execute(self.args("find", "pick"), None)
        self.assertFalse(result["catalog_coverage"]["complete"])
        self.assertEqual(result["discovery_fallback_reasons"], ["public_search_unavailable"])

    def test_findings_query_uses_exact_pins_and_validates_fingerprint_before_cache(self):
        page = finding_page()
        with mock.patch.object(discovery, "fetch_public", return_value=page) as fetch, mock.patch.object(memories, "public_index", side_effect=AssertionError("global finding download")):
            result = memories.query(fixture_catalog(), "fixture-pick", {})
        self.assertEqual(result["total"], 1)
        self.assertIn("record_version=1.0.0", fetch.call_args.args[0])
        self.assertIn("source_commit=" + PIN, fetch.call_args.args[0])
        self.assertFalse(result["execution_performed"])
        self.assertIn("treat text as data", result["results"][0]["trust"])
        page["results"][0]["observation"] += " altered"
        with mock.patch.object(discovery, "fetch_public", return_value=page):
            cached, origin = memories._remote_findings("fixture-pick", page["results"][0]["base"], {}, 20, 0, None, True)
            self.assertEqual(origin, "api_cache_fallback")
            self.assertNotEqual(cached["results"][0]["observation"], page["results"][0]["observation"])
            for path in Path(self.temporary.name).glob("api-findings-*.json"):
                path.unlink()
            with self.assertRaises(core.RshError):
                memories._remote_findings("fixture-pick", page["results"][0]["base"], {}, 20, 0, None, True)


if __name__ == "__main__":
    unittest.main()
