"""Bounded v2 wire data retains every inventory row and immutable proof field."""
import copy
import hashlib
import json
import unittest

import catalog_v2 as v2

HUB = "a" * 40


class V2WireTests(unittest.TestCase):
    def test_search_pages_split_at_both_row_and_actual_utf8_byte_limits(self):
        rows = [{"id": f"fixture-{i:03d}", "summary": "small"} for i in range(201)]
        kwargs = {"counts": {"recipes": 0, "references": len(rows), "memories": 0}, "memory_manifest": {"records": 0}}
        manifest, pages = v2.paged_index(rows, HUB, "search", **kwargs)
        self.assertEqual([d["records"] for d in manifest["pages"]], [100, 100, 1])
        self.assertEqual((manifest, pages), v2.paged_index(list(reversed(rows)), HUB, "search", **kwargs))
        restored = []
        for i, descriptor in enumerate(manifest["pages"]):
            path = f"catalog/v2/generations/{HUB}/search/{i:06d}.json"
            raw = pages[path]
            self.assertEqual(descriptor["path"], path)
            self.assertEqual(descriptor["bytes"], len(raw))
            self.assertEqual(descriptor["sha256"], hashlib.sha256(raw).hexdigest())
            self.assertTrue(raw.endswith(b"\n"))
            self.assertNotIn(b"\r\n", raw)
            restored.extend(json.loads(raw)["records"])
        self.assertEqual(restored, rows)
        unicode_rows = [{"id": f"unicode-{i}", "summary": "한" * 300} for i in range(5)]
        manifest, pages = v2.paged_index(unicode_rows, HUB, "search", page_max_bytes=1400, **kwargs)
        self.assertEqual(len(manifest["pages"]), 5)
        self.assertTrue(all(len(raw) <= 1400 for raw in pages.values()))

    def test_empty_memory_inventory_and_individual_wire_failures_are_explicit(self):
        manifest, pages = v2.paged_index([], HUB, "memories")
        self.assertEqual(manifest, {"schema_version": "2", "hub_commit": HUB, "records": 0, "pages": []})
        self.assertEqual(pages, {})
        with self.assertRaisesRegex(ValueError, "record fixture.*UTF-8 budget"):
            v2.paged_index([{"id": "fixture", "summary": "한" * 1000}], HUB, "search", page_max_bytes=200)
        with self.assertRaisesRegex(ValueError, "manifest.*UTF-8 budget"):
            v2.paged_index([{"id": "fixture"}], HUB, "search", manifest_max_bytes=1)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            v2.paged_index([{"id": "fixture"}, {"id": "fixture"}], HUB, "search")

    def test_legacy_subset_has_current_commit_and_explicit_complete_manifest(self):
        rows = [{"id": f"fixture-{i:03d}", "summary": "한" * 100} for i in range(10)]
        index = {"schema_version": "1", "hub_commit": HUB, "records": list(reversed(rows))}
        self.assertIs(v2.compatibility_view(index, 10000, "https://hub.test/complete"), index)
        view = v2.compatibility_view(index, 1200, "https://hub.test/complete")
        self.assertLessEqual(len(v2.json_bytes(view)), 1200)
        self.assertEqual(view["hub_commit"], HUB)
        self.assertEqual(view["coverage"], {"complete": False, "total_records": 10,
                         "included_records": len(view["records"]), "complete_manifest_url": "https://hub.test/complete"})
        self.assertGreater(len(view["records"]), 0)
        self.assertLess(len(view["records"]), len(rows))
        self.assertEqual(view["records"], rows[:len(view["records"])])
        self.assertEqual(index["records"], list(reversed(rows)))

    @staticmethod
    def record_proof(ident, sid):
        return {"id": ident, "kind": "source_reference", "record_version": "intake-original", "source_commit": "b" * 40,
                "recipe_url": "https://hub.test/references/" + ident + "/", "compatibility": [{"runtime": "ros2"}],
                "contribution_path_hashes": {"catalog/intake/" + ident + ".json": "c" * 64}, "submission_ids": [sid]}

    def fixture_manifest(self):
        current = self.record_proof("current", "sub_" + "1" * 64)
        other = self.record_proof("other", "sub_" + "2" * 64)
        historical = self.record_proof("historical", "sub_" + "3" * 64)
        historical.update(archive_sha256="4" * 64, recipe_url="https://hub.test/releases/historical/intake-original/")
        other_historical = self.record_proof("old-other", "sub_" + "4" * 64)
        memory = {"memory_id": "mem_" + "5" * 64, "fingerprint": "6" * 64, "content_sha256": "7" * 64,
                  "skill_id": "current", "record_version": "source-" + "8" * 64, "source_commit": "b" * 40,
                  "base_hub_commit": "9" * 40, "entry_url": "https://hub.test/memories/mem_" + "5" * 64 + ".json"}
        return {"schema_version": "1", "hub_commit": HUB, "catalog_url": "https://hub.test/catalog/v1/index.json",
                "records": [current, other], "memories": [memory], "history": [{"hub_commit": "9" * 40, "records": [historical, other_historical]}]}

    def test_per_receipt_bytes_preserve_exact_fields_and_historical_anchors(self):
        manifest = self.fixture_manifest()
        original = copy.deepcopy(manifest)
        files = v2.receipt_proofs(manifest)
        self.assertEqual(len(files), 5)
        for proof in manifest["records"]:
            value = json.loads(files[f"catalog/v2/submissions/{proof['submission_ids'][0]}.json"])
            self.assertEqual(value["records"], [proof])
            self.assertEqual(value["history"], [])
            self.assertEqual(value["memories"], [])
        historical = manifest["history"][0]["records"][0]
        raw = files[f"catalog/v2/submissions/{historical['submission_ids'][0]}.json"]
        expected = {"schema_version": "1", "hub_commit": HUB, "catalog_url": manifest["catalog_url"],
                    "records": [], "memories": [], "history": [{"hub_commit": "9" * 40, "records": [historical]}]}
        self.assertEqual(raw, v2.json_bytes(expected))
        memory = manifest["memories"][0]
        value = json.loads(files[f"catalog/v2/memories/{memory['memory_id']}.json"])
        self.assertEqual(value["memories"], [memory])
        self.assertEqual(value["records"], [])
        self.assertEqual(value["history"], [])
        self.assertEqual(manifest, original)
        self.assertEqual(files, v2.receipt_proofs(manifest))

    def test_invalid_or_conflicting_receipt_ids_and_oversized_single_proofs_fail_closed(self):
        manifest = self.fixture_manifest()
        manifest["records"][0]["submission_ids"] = ["../../arbitrary"]
        with self.assertRaisesRegex(ValueError, "submission ID"):
            v2.receipt_proofs(manifest)
        manifest = self.fixture_manifest()
        manifest["records"][1]["submission_ids"] = manifest["records"][0]["submission_ids"]
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            v2.receipt_proofs(manifest)
        manifest = self.fixture_manifest()
        with self.assertRaisesRegex(ValueError, "UTF-8 budget"):
            v2.receipt_proofs(manifest, max_bytes=100)


if __name__ == "__main__":
    unittest.main()
