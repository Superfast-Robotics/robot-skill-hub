"""Opt-in task ranking: real local/remote CLI paths, no upstream execution."""
import copy
import importlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills/find-robot-skills/scripts"))
from rshlib import core, discovery, remote_catalog, task_search
from test_rsh import fixture_catalog, HUB, PIN
from test_reference_discovery import reference
from test_remote_discovery import search_page, search_slice
rsh = importlib.import_module("rsh")
SPEC = json.loads((ROOT / "benchmarks/search/task-lexical-v1.json").read_bytes())


class TaskSearchTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.env = mock.patch.dict(os.environ, {"RSH_TELEMETRY": "off", "RSH_CACHE_DIR": self.directory.name})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_frozen_shared_normalization_and_scoring_vectors(self):
        for vector in SPEC["normalization_vectors"]:
            with self.subTest(query=vector["query"]):
                if "error" in vector:
                    with self.assertRaises(task_search.TaskQueryError) as caught:
                        task_search.terms(vector["query"], core.query_terms)
                    self.assertEqual(vector["error"], caught.exception.code)
                else:
                    self.assertEqual(vector["terms"], task_search.terms(vector["query"], core.query_terms))
        for vector in SPEC["ranking_vectors"]:
            actual = task_search.rank(vector["rows"], vector["query"], task_search.terms(vector["query"], core.query_terms))
            self.assertEqual(vector["expected_ids"], [row["id"] for row, _ in actual])
            self.assertEqual(vector["expected_scores"], [match["score"] for _, match in actual])

    def test_local_task_filters_pins_pagination_and_unchanged_prepare_handoff(self):
        catalog = fixture_catalog()
        original = catalog["records"][0]
        catalog["records"] = [{**copy.deepcopy(original), "id": "fixture-pick-" + str(i)} for i in range(4)]
        source = reference()
        source.update(framework="fixture", robots=["panda"])
        catalog["references"] = {"schema_version": "1", "hub_commit": HUB, "records": [source]}
        environment = {**original["compatibility"][0], "python": core.local_environment()["python"]}
        query = "Please help me pick an object"
        strict = core.find(catalog, query, environment)
        self.assertEqual(0, strict["total"])
        result = core.find(catalog, query, environment, limit=2, query_mode="task")
        self.assertEqual(4, result["candidate_count"])
        self.assertEqual(4, result["total"])
        self.assertEqual("hard_filtered_records", result["candidate_scope"])
        self.assertEqual("task", result["next"]["query_mode"])
        self.assertEqual(HUB, result["next"]["hub_commit"])
        next_page = core.find(catalog, query, environment, limit=2, offset=2, hub_commit=HUB, query_mode="task")
        self.assertFalse({r["id"] for r in result["results"]} & {r["id"] for r in next_page["results"]})
        for row in result["results"]:
            self.assertEqual(PIN, row["source_commit"])
            self.assertEqual({"record_version": "1.0.0", "source_commit": PIN, "hub_commit": HUB}, row["memory_base"])
            self.assertEqual(core.preparation_arguments(row["id"], PIN, "1.0.0", environment), row["prepare_args"])
            self.assertNotIn("--query-mode", row["prepare_args"])
        self.assertEqual(0, core.find(catalog, query, {"robot": "wrong"}, query_mode="task")["total"])
        # A label alone can discover a reference; two constraints cannot invent a tuple.
        discovered = core.find(catalog, "Please compute inverse kinematics", {"runtime": "fixture"}, query_mode="task")
        self.assertIn(source["id"], [r["id"] for r in discovered["results"]])
        self.assertTrue(all(r["compatibility_status"] == "unknown" for r in discovered["results"]))
        with self.assertRaises(core.RshError) as caught:
            core.find(catalog, query, environment, hub_commit="f" * 40, query_mode="task")
        self.assertEqual("catalog_generation_changed", caught.exception.result["reason_code"])

    def test_candidate_scope_precedes_any_text_and_task_validation(self):
        catalog = fixture_catalog()
        row = catalog["records"][0]
        catalog["records"] = [{**copy.deepcopy(row), "id": "fixture-" + str(i)} for i in range(513)]
        for query in ("pick", "zzzzunfindable", "the and please"):
            with self.assertRaises(core.RshError) as caught:
                core.find(catalog, query, {}, query_mode="task")
            self.assertEqual("query_too_broad", caught.exception.result["reason_code"])
        self.assertEqual(513, core.find(catalog, "pick", {})["total"])  # Strict search has no task cap.
        catalog["records"].pop()
        self.assertEqual(512, core.find(catalog, "pick", {}, query_mode="task")["candidate_count"])
        self.assertEqual(0, core.find(catalog, "the and please", {}, query_mode="task")["total"])
        self.assertEqual(0, core.find(catalog, "pick", {"robot": "wrong"}, query_mode="task")["candidate_count"])
        for query, code in (("caf\u00e9", "unsupported_task_query"), (" ".join("word" + str(i) for i in range(17)), "invalid_task_query")):
            with self.assertRaises(core.RshError) as caught:
                core.find(catalog, query, {}, query_mode="task")
            self.assertEqual(code, caught.exception.result["reason_code"])

    def task_page(self, offset=0):
        page = search_slice(offset, total=4, query="Please pick a cube", environment={"runtime": "fixture"})
        query_terms = task_search.terms("Please pick a cube", core.query_terms)
        page.update(task_search.metadata(query_terms, 4))
        page["backend"] = "d1_filtered_lexical"
        if page["next"]:
            page["next"]["query_mode"] = "task"
        for row in page["results"]:
            row["aliases"] = ["cube"]
            row["query_match"] = task_search.score(row, query_terms)
        return page

    def test_actual_remote_cli_mode_cache_paging_and_local_explicit_path(self):
        args = rsh.build_parser().parse_args
        with mock.patch.object(discovery, "fetch_public", side_effect=[self.task_page(), self.task_page(3), search_page()]) as fetch, \
                mock.patch.object(rsh, "load_discovery", side_effect=AssertionError("aggregate fallback")):
            first = rsh.execute(args(["find", "Please pick a cube", "--runtime", "fixture", "--query-mode", "task"]), None)
            second = remote_catalog.search("Please pick a cube", {"runtime": "fixture"}, offset=3, hub_commit=HUB, query_mode="task")
            cached = remote_catalog.search("Please pick a cube", {"runtime": "fixture"}, query_mode="task")
            strict = remote_catalog.search("Please pick a cube", {"runtime": "fixture"})
        self.assertEqual(3, fetch.call_count)
        self.assertEqual("task", first["query_mode"])
        self.assertEqual("api_cache", cached["catalog_origin"])
        self.assertEqual(3, second["offset"])
        self.assertNotIn("query_mode", strict)
        params = urllib.parse.parse_qs(urllib.parse.urlsplit(fetch.call_args_list[1].args[0]).query)
        self.assertEqual(["task"], params["query_mode"])
        self.assertEqual([HUB], params["hub_commit"])
        with mock.patch.object(rsh, "load_discovery", return_value=fixture_catalog()), \
                mock.patch.object(discovery, "fetch_public", side_effect=AssertionError("network")):
            local = rsh.execute(args(["--offline", "find", "Please pick an object", "--query-mode", "task"]), "fixture.json")
        self.assertEqual(1, local["total"])
        self.assertEqual("--offline", local["results"][0]["prepare_args"][0])

    def test_remote_overflow_is_typed_no_cache_or_aggregate_fallback(self):
        error = urllib.error.HTTPError("https://api.example.invalid", 400, "bad request", {}, io.BytesIO(b'{"reason_code":"query_too_broad"}'))
        with mock.patch.object(discovery, "fetch_public", side_effect=error) as fetch, \
                mock.patch.object(rsh, "load_discovery", side_effect=AssertionError("aggregate fallback")):
            with self.assertRaises(core.RshError) as caught:
                rsh.execute(rsh.build_parser().parse_args(["find", "Please pick a cube", "--query-mode", "task"]), None)
        self.assertEqual("query_too_broad", caught.exception.result["reason_code"])
        self.assertEqual(1, fetch.call_count)


if __name__ == "__main__":
    unittest.main()
