"""Supply-chain and additive refresh checks; never execute upstream robot code."""
import copy
from concurrent.futures import ThreadPoolExecutor
import json
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import import_ecosystem_examples as importer
import import_reference_examples as legacy
from reference_index import check_source_index, json_bytes, source_index, source_index_shards, write_source_index


class EcosystemImportTests(unittest.TestCase):
    def fixture(self):
        source = b"import pinocchio\nif __name__ == '__main__':\n    print(pinocchio.__version__)\n"
        license_text = b"MIT License\nPermission is hereby granted, free of charge\n"
        project = {"id": "fixture", "name": "Fixture", "repository": "https://github.com/example/robot", "commit": "1" * 40,
                   "ref": "stable", "stars": 0, "checked_at": "2026-10-18", "capabilities": ["kinematics"],
                   "robot_types": ["arm", "humanoid"], "execution_domain": "computation", "setup_url": "https://example.com/setup",
                   "invocation_notes": "Inspect source before use", "requirements": {"python": "3.10", "packages": [], "environment": "CPU"},
                   "license": {"spdx": "MIT", "path": "LICENSE", "sha256": importer.digest(license_text), "scope": "Source only"},
                   "selection": {"include": ["examples/*.py"], "exclude": []}}
        artifact = {"path": "examples/ik.py", "sha256": importer.digest(source), "bytes": len(source), "entrypoint_kind": "python_main"}
        return project, artifact, source, license_text

    def discovery_fetch_fixture(self):
        project, artifact, source, license_text = self.fixture()
        artifact["path"] = "examples/panda.py"
        documents = {"README.md": b"Selected Panda example setup.\n",
                     "setup/robot.md": b"Panda controller configuration.\n"}
        artifact["robot_discovery"] = {"labels": ["panda"], "scope": "Pinned example setup only; compatibility unknown.",
            "evidence": [{"path": path, "sha256": importer.digest(data), "bytes": len(data),
                          "quote": "Panda", "labels": ["panda"]} for path, data in documents.items()]}
        # Same-source evidence must not make the fetch download an artifact twice.
        artifact["robot_discovery"]["evidence"].append({"path": artifact["path"], "sha256": artifact["sha256"],
            "bytes": artifact["bytes"], "quote": "panda", "labels": ["panda"], "match_in": "source_path"})
        project["artifacts"] = [artifact]
        return project, artifact, {"LICENSE": license_text, artifact["path"]: source, **documents}

    def test_fresh_fetch_includes_pinned_setup_discovery_evidence_and_rebuilds_offline(self):
        project, artifact, bodies = self.discovery_fetch_fixture()
        base = f"https://raw.githubusercontent.com/example/robot/{project['commit']}/"
        responses = {base + path: data for path, data in bodies.items()}
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            with mock.patch.object(importer, "download", side_effect=lambda url: responses[url]) as fetch:
                result = importer.build({"projects": [project]}, cache, {"records": []}, fetch=True)
            self.assertCountEqual(responses, [call.args[0] for call in fetch.call_args_list])
            self.assertEqual(len(responses), fetch.call_count)
            for path, data in bodies.items():
                self.assertEqual(data, importer.cache_path(cache, project, path).read_bytes())
            record = result["records"][0]
            self.assertEqual(["panda"], record["robots"])
            self.assertEqual([pin["sha256"] for pin in artifact["robot_discovery"]["evidence"]],
                             [pin["sha256"] for pin in record["evidence"]["robot_discovery"]["evidence"]])
            self.assertNotIn("compatibility", record)
            self.assertFalse(record["access"]["hub_prepare"])
            self.assertEqual("not_run", record["evidence"]["runtime_verification"])
            with mock.patch.object(importer, "download", side_effect=AssertionError("Offline build fetched")) as fetch:
                self.assertEqual(result, importer.build({"projects": [project]}, cache, result, fetch=False))
            fetch.assert_not_called()

    def test_malformed_discovery_pin_is_rejected_before_any_fetch(self):
        changes = [{"path": "../escape.md"}, {"path": None}, {"sha256": "not-a-sha"},
                   {"bytes": True}, {"bytes": 0}, {"bytes": importer.MAX_SOURCE_BYTES + 1},
                   {"match_in": "source_path"}]
        for change in changes:
            project, artifact, _ = self.discovery_fetch_fixture()
            artifact["robot_discovery"]["evidence"][0].update(change)
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                with mock.patch.object(importer, "download") as fetch:
                    with self.assertRaises(ValueError):
                        importer.build({"projects": [project]}, Path(directory), {"records": []}, fetch=True)
                fetch.assert_not_called()

    def test_fetched_discovery_evidence_still_requires_its_reviewed_checksum(self):
        project, artifact, bodies = self.discovery_fetch_fixture()
        bodies["README.md"] = b"Changed Panda setup text.\n"
        base = f"https://raw.githubusercontent.com/example/robot/{project['commit']}/"
        responses = {base + path: data for path, data in bodies.items()}
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(importer, "download", side_effect=lambda url: responses[url]):
                with self.assertRaisesRegex(ValueError, "evidence checksum/size"):
                    importer.build({"projects": [project]}, Path(directory), {"records": []}, fetch=True)

    def test_pinned_bytes_and_license_are_required(self):
        project, artifact, source, license_text = self.fixture()
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            target = importer.cache_path(cache, project, artifact["path"])
            target.parent.mkdir(parents=True)
            target.write_bytes(source)
            importer.cache_path(cache, project, "LICENSE").write_bytes(license_text)
            importer.checked_license(project, cache)
            record = importer.make_record(project, artifact, cache)
            self.assertFalse(record["access"]["hub_prepare"])
            self.assertEqual("not_run", record["evidence"]["runtime_verification"])
            self.assertEqual(["source-defined"], record["robot_types"])
            target.write_bytes(source + b"# changed\n")
            with self.assertRaisesRegex(ValueError, "checksum/size"):
                importer.make_record(project, artifact, cache)
            importer.cache_path(cache, project, "LICENSE").write_bytes(license_text + b" changed")
            with self.assertRaisesRegex(ValueError, "license checksum"):
                importer.checked_license(project, cache)

    def test_reviewed_per_artifact_aliases_enable_exact_entry_retrieval_and_keep_header_credit(self):
        project, _, _, license_text = self.fixture()
        project.update(capabilities=["planning"], aliases=["MPC", "DWA"], authors=["Project-wide credit must not be broadcast"])
        specifications = [
            ("examples/model_predictive_speed_and_steer_control.py", "Fixture Control Author", ["MPC"], ["Fixture Control Author"]),
            ("examples/dynamic_window_approach.py", "Fixture Local Planner Author", ["DWA"], ["Fixture Local Planner Author"]),
            ("examples/pure_pursuit.py", "Unselected Header Author", None, None),
        ]
        bodies, artifacts = {}, []
        for path, header_author, aliases, authors in specifications:
            body = (f"# Author: {header_author}\nraise RuntimeError('fixture source must never execute')\n"
                    "if __name__ == '__main__':\n    main()\n").encode()
            bodies[path] = body
            artifact = {"path": path, "sha256": importer.digest(body), "bytes": len(body), "entrypoint_kind": "python_main"}
            if aliases is not None:
                artifact["aliases"] = aliases
            if authors is not None:
                artifact["authors"] = authors
            artifacts.append(artifact)
        project["artifacts"] = artifacts
        absent = copy.deepcopy(project)
        for artifact in absent["artifacts"]:
            artifact.pop("aliases", None)
            artifact.pop("authors", None)
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            for path, body in {"LICENSE": license_text, **bodies}.items():
                destination = importer.cache_path(cache, project, path)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(body)
            with mock.patch.object(importer, "download", side_effect=AssertionError("Offline fixture only")):
                baseline = importer.build({"projects": [absent]}, cache, {"records": []})
                result = importer.build({"projects": [project]}, cache, {"records": []})
        sys.path.insert(0, str(ROOT / "skills/find-robot-skills/scripts"))
        from rshlib.core import find
        before = {"records": [], "references": {"records": baseline["records"]}}
        after = {"records": [], "references": {"records": result["records"]}}
        self.assertEqual(0, find(before, "MPC", {})["total"])
        self.assertEqual(0, find(before, "DWA", {})["total"])
        by_path = {record["source"]["path"]: record for record in result["records"]}
        for query, path in (("MPC", specifications[0][0]), ("DWA", specifications[1][0])):
            matches = find(after, query, {})
            self.assertEqual(1, matches["total"])
            self.assertEqual(by_path[path]["id"], matches["results"][0]["id"])
            self.assertEqual("unknown", matches["results"][0]["compatibility_status"])
        for artifact in artifacts:
            record = by_path[artifact["path"]]
            self.assertEqual(artifact["sha256"], record["source"]["sha256"])
            self.assertEqual(artifact["bytes"], record["source"]["bytes"])
            self.assertFalse(record["access"]["hub_prepare"])
            self.assertEqual("not_run", record["evidence"]["runtime_verification"])
            self.assertNotIn("compatibility", record)
            if "authors" in artifact:
                self.assertEqual(artifact["authors"], record["source"]["authors"])
                self.assertIsNot(artifact["authors"], record["source"]["authors"])
                self.assertTrue(all(author.encode() in bodies[artifact["path"]] for author in record["source"]["authors"]))
            else:
                self.assertNotIn("authors", record["source"])
                self.assertNotIn("aliases", record)
        # Absent optional declarations retain every previous record field.
        stripped = copy.deepcopy(result)
        for record in stripped["records"]:
            record.pop("aliases", None)
            record["source"].pop("authors", None)
        self.assertEqual(baseline, stripped)

    def test_malformed_per_artifact_aliases_and_authors_fail_before_source_read_or_fetch(self):
        for field, maximum in (("aliases", 120), ("authors", 240)):
            invalid = [None, "MPC", [], [None], [True], [{}], [[]], [""], [" "], [" leading"], ["trailing "],
                       ["line\nbreak"], ["tab\tname"], ["nul\0name"], ["delete\x7f"], ["control\x85"],
                       ["same", "same"], ["x" * (maximum + 1)], [str(number) for number in range(21)]]
            for value in invalid:
                project, artifact, *_ = self.fixture()
                artifact[field] = value
                project["artifacts"] = [artifact]
                with self.subTest(field=field, value=value), mock.patch.object(importer, "source_bytes") as source, mock.patch.object(importer, "download") as fetch:
                    with self.assertRaisesRegex(ValueError, "Reviewed artifact " + field):
                        importer.make_record(project, artifact, Path("unused-cache"))
                    with self.assertRaisesRegex(ValueError, "Reviewed artifact " + field):
                        importer.build({"projects": [project]}, Path("unused-cache"), {"records": []}, fetch=True)
                source.assert_not_called()
                fetch.assert_not_called()

    def test_reviewed_metadata_accepts_exact_bounds_and_copies_only_supplied_fields(self):
        artifact = {"aliases": ["x" * 120] + [f"alias-{number}" for number in range(19)],
                    "authors": ["y" * 240] + [f"Author {number}" for number in range(19)]}
        result = importer.reviewed_artifact_metadata(artifact)
        self.assertEqual(artifact, result)
        self.assertIsNot(artifact["aliases"], result["aliases"])
        self.assertIsNot(artifact["authors"], result["authors"])
        self.assertEqual({}, importer.reviewed_artifact_metadata({"path": "example.py"}))

    def test_library_and_commented_main_are_not_examples(self):
        for name, data in [("helper.py", b"import pinocchio\ndef helper():\n    return pinocchio.Model()\n"),
                           ("helper.cpp", b"// int main() { return 0; }\nvoid helper() {}\n")]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                importer.inspect_source(name, data)

    def test_reviewed_robot_name_is_searchable_without_inferred_compatibility(self):
        project, artifact, _, license_text = self.fixture()
        source = b"import cflib.crazyflie\nif __name__ == '__main__':\n    main()\n"
        artifact.update(sha256=importer.digest(source), bytes=len(source), robot_discovery={
            "labels": ["crazyflie"], "scope": "Named library target only; compatibility unknown.",
            "evidence": [{"path": artifact["path"], "sha256": importer.digest(source), "bytes": len(source),
                          "quote": "cflib.crazyflie", "labels": ["crazyflie"]}]})
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            target = importer.cache_path(cache, project, artifact["path"])
            target.parent.mkdir(parents=True)
            target.write_bytes(source)
            importer.cache_path(cache, project, "LICENSE").write_bytes(license_text)
            record = importer.make_record(project, artifact, cache)
            sys.path.insert(0, str(ROOT / "skills/find-robot-skills/scripts"))
            from rshlib.core import find
            catalog = {"records": [], "references": {"records": [record]}}
            self.assertEqual(1, find(catalog, "", {"robot": "crazyflie"})["total"])
            self.assertEqual(0, find(catalog, "", {"robot": "crazyflie", "os": "linux"})["total"])
            self.assertNotIn("compatibility", record)
            self.assertFalse(record["evidence"]["robot_discovery"]["compatibility_inferred"])
            self.assertEqual("not_run", record["evidence"]["runtime_verification"])
            artifact["robot_discovery"]["evidence"][0]["quote"] = "logging1"
            artifact["robot_discovery"]["labels"] = ["g1"]
            artifact["robot_discovery"]["evidence"][0]["labels"] = ["g1"]
            changed = source + b"# logging1\n"
            target.write_bytes(changed)
            artifact.update(sha256=importer.digest(changed), bytes=len(changed))
            artifact["robot_discovery"]["evidence"][0].update(sha256=artifact["sha256"], bytes=artifact["bytes"])
            with self.assertRaisesRegex(ValueError, "complete robot label"):
                importer.make_record(project, artifact, cache)

    def test_path_discovery_cannot_use_another_artifact_or_changed_bytes(self):
        project, artifact, source, license_text = self.fixture()
        artifact["path"] = "examples/g1.py"
        artifact["robot_discovery"] = {"labels": ["g1"], "scope": "Source filename only.",
            "evidence": [{"path": artifact["path"], "sha256": artifact["sha256"], "bytes": artifact["bytes"],
                          "quote": "g1", "labels": ["g1"], "match_in": "source_path"}]}
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            target = importer.cache_path(cache, project, artifact["path"])
            target.parent.mkdir(parents=True)
            target.write_bytes(source)
            importer.cache_path(cache, project, "LICENSE").write_bytes(license_text)
            record = importer.make_record(project, artifact, cache)
            self.assertEqual(["g1"], record["robots"])
            pin = artifact["robot_discovery"]["evidence"][0]
            pin["sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "checksum/size"):
                importer.make_record(project, artifact, cache)
            pin.update(path="LICENSE", sha256=importer.digest(license_text), bytes=len(license_text))
            with self.assertRaisesRegex(ValueError, "selected source"):
                importer.make_record(project, artifact, cache)

    def test_offline_source_read_preserves_the_fetch_byte_bound(self):
        project, artifact, *_ = self.fixture()
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            target = importer.cache_path(cache, project, artifact["path"])
            target.parent.mkdir(parents=True)
            target.write_bytes(b"x" * 33)
            with mock.patch.object(importer, "MAX_SOURCE_BYTES", 32), self.assertRaisesRegex(ValueError, "size limit"):
                importer.source_bytes(cache, project, artifact["path"])

    def test_straightline_config_is_not_a_reviewed_lerobot_entrypoint(self):
        project, artifact, _, _ = self.fixture()
        source = b"import lerobot\nCONFIG = lerobot.Config()\n"
        artifact.update(sha256=importer.digest(source), bytes=len(source), entrypoint_kind="python_script")
        with tempfile.TemporaryDirectory() as directory:
            target = importer.cache_path(Path(directory), project, artifact["path"])
            target.parent.mkdir(parents=True)
            target.write_bytes(source)
            with self.assertRaisesRegex(ValueError, "Straight-line"):
                importer.make_record(project, artifact, Path(directory))

    def test_paths_and_mutable_refs_are_rejected(self):
        for path in ["../escape.py", "/absolute.py", "a/../escape.py", "C:/escape.py", "a\\escape.py", "a\x00.py"]:
            with self.subTest(path=path), self.assertRaises(ValueError):
                importer.safe_relative(path)
        project, *_ = self.fixture()
        project["commit"] = "main"
        with self.assertRaisesRegex(ValueError, "immutable commit"):
            importer.validate_project(project)

    def test_concurrent_fresh_cache_paths_stay_inside_project(self):
        project, *_ = self.fixture()
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            base = cache / project["id"] / project["commit"]
            base.mkdir(parents=True)
            def create(index):
                target = importer.cache_path(cache, project, f"examples/group-{index % 5}/source-{index}.py")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("# fixture\n", encoding="utf-8")
                return target
            with ThreadPoolExecutor(max_workers=8) as pool:
                paths = list(pool.map(create, range(60)))
            self.assertEqual(60, len(paths))
            self.assertTrue(all(p.is_file() for p in paths))

    def test_explicit_different_file_license_is_rejected(self):
        project, *_ = self.fixture()
        self.assertFalse(importer.compatible_file_license(project, "# SPDX-License-Identifier: GPL-3.0-only\n"))
        self.assertFalse(importer.compatible_file_license(project, "# GNU General Public License\n"))
        self.assertTrue(importer.compatible_file_license(project, "# SPDX-License-Identifier: MIT\n"))

    def test_nonstandard_license_ref_remains_unverified_source_metadata(self):
        project, artifact, source, _ = self.fixture()
        terms = {"identifier": "FIXTURE-2026", "marker": "Fixture SDK License",
                 "notes": "Vendor terms apply to the linked source; no usage grant is inferred."}
        license_text = b"Fixture SDK License (FIXTURE-2026)\nVendor product conditions apply.\n"
        project["license"] = {"path": "LICENSE", "sha256": importer.digest(license_text),
            "spdx": "LicenseRef-Fixture-FIXTURE-2026", "scope": "Linked SDK source under pinned vendor terms.",
            "verified": False, "review_status": "nonstandard_upstream_terms", "source_terms": terms}
        project["artifacts"] = [artifact]
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            for path, body in {"LICENSE": license_text, artifact["path"]: source}.items():
                target = importer.cache_path(cache, project, path)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(body)
            with mock.patch.object(importer, "download", side_effect=AssertionError("offline")):
                result = importer.build({"projects": [project]}, cache, {"records": []})
            record = result["records"][0]
            self.assertEqual(terms, record["license"]["source_terms"])
            self.assertFalse(record["license"]["verified"])
            self.assertEqual("LicenseRef-Fixture-FIXTURE-2026", record["license"]["spdx"])
            self.assertEqual("nonstandard_upstream_terms", record["license"]["review_status"])
            self.assertFalse(record["access"]["hub_prepare"])
            self.assertEqual("not_run", record["evidence"]["runtime_verification"])
            self.assertNotIn("compatibility", record)
            for field in ("marker", "identifier"):
                project["license"]["source_terms"] = {**terms, field: "absent-from-pinned-text"}
                with self.subTest(field=field), self.assertRaisesRegex(ValueError, "identity or text marker"):
                    importer.build({"projects": [project]}, cache, {"records": []})

    def test_nonstandard_terms_cannot_be_asserted_as_verified_or_standard_license(self):
        project, *_ = self.fixture()
        base = {**project["license"], "spdx": "LicenseRef-Fixture-FIXTURE-2026", "verified": False,
                "review_status": "nonstandard_upstream_terms",
                "source_terms": {"identifier": "FIXTURE-2026", "marker": "Fixture SDK License", "notes": "Vendor terms."}}
        cases = [{"verified": True}, {"verified": None}, {"review_status": "approved"},
                 {"spdx": "MIT"}, {"source_terms": {**base["source_terms"], "marker": "x" + " " * 240}},
                 {"source_terms": {**base["source_terms"], "notes": "x" + " " * 2000}},
                 {"source_terms": {**base["source_terms"], "identifier": "bad\nidentifier"}},
                 {"source_terms": {**base["source_terms"], "permission_granted": True}}]
        for change in cases:
            project["license"] = {**base, **change}
            with self.subTest(change=change), self.assertRaises(ValueError):
                importer.validate_project(project)

    def test_additive_refresh_preserves_other_registries_and_detects_duplicates(self):
        project, artifact, *_ = self.fixture()
        foreign = {"id": "foreign", "framework": "outside", "source": {"repository": "https://github.com/other/repo", "commit": "2" * 40, "path": "sample.py", "sha256": "a" * 64}, "popularity": {"repository_stars": 0}}
        owned = {**copy.deepcopy(foreign), "id": "owned", "source_registry": importer.REGISTRY}
        updated = {**copy.deepcopy(owned), "source": {**foreign["source"], "path": "updated.py"}}
        merged = importer.merge_records([foreign, owned], [updated])
        self.assertEqual(["foreign", "owned"], [r["id"] for r in merged])
        self.assertEqual("updated.py", merged[1]["source"]["path"])
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            importer.merge_records([foreign], [copy.deepcopy(foreign)])
        original = {**copy.deepcopy(foreign), "id": "mujoco-fixture", "framework": "mujoco", "source": {**foreign["source"], "repository": legacy.PROJECTS["mujoco"]["repository"]}}
        self.assertEqual({"foreign", "mujoco-fixture"}, {r["id"] for r in legacy.merge_reference_records([foreign, original], [original])})

    def test_published_index_matches_every_official_source(self):
        references = json.loads((ROOT / "catalog/references.json").read_text(encoding="utf-8"))
        self.assertTrue(all(len(record["id"]) <= 80 for record in references["records"]))
        self.assertEqual(len(references["records"]), len({record["id"] for record in references["records"]}))
        compact = json.loads((ROOT / "catalog/source-index.json").read_text(encoding="utf-8"))
        self.assertEqual(source_index(references["records"]), compact)
        check_source_index(references["records"], ROOT / "catalog/source-index.json")
        manifest = json.loads((ROOT / "catalog/source-projects.json").read_text(encoding="utf-8"))
        managed = {(r["framework"], r["source"]["path"]): r for r in references["records"] if r.get("source_registry") == importer.REGISTRY}
        count = 0
        for project in manifest["projects"]:
            importer.validate_project(project)
            for artifact in project["artifacts"]:
                record = managed[project["id"], artifact["path"]]
                self.assertEqual(artifact["sha256"], record["source"]["sha256"])
                self.assertEqual(project["commit"], record["source"]["commit"])
                self.assertEqual(project["license"]["sha256"], record["license"]["sha256"])
                count += 1
        self.assertEqual(len(managed), count)

    def synthetic_records(self, count):
        return [{"id": f"future-robot-skill-{index:06d}", "source": {
            "commit": "1" * 40, "sha256": hashlib.sha256(str(index).encode("utf-8")).hexdigest()}}
                for index in range(count)]

    def test_shard_manifest_has_exact_hashes_prefixes_and_complete_coverage(self):
        records = self.synthetic_records(600)
        # Prefix allocation is explicitly UTF-8, independent of source revision.
        records.append({"id": "future-robot-\U0001f916", "source": {"revision": "sha256:" + "2" * 64, "sha256": "3" * 64}})
        manifest, shards = source_index_shards(records)
        self.assertEqual("sha256-id-prefix-2", manifest["scheme"])
        self.assertEqual(len(records), manifest["records"])
        flattened = []
        for prefix, body in shards.items():
            descriptor = manifest["shards"][prefix]
            self.assertEqual(f"catalog/source-index/{prefix}.json", descriptor["path"])
            self.assertEqual(hashlib.sha256(body).hexdigest(), descriptor["sha256"])
            parsed = json.loads(body)
            self.assertEqual(descriptor["records"], len(parsed["records"]))
            self.assertEqual(sorted(r["id"] for r in parsed["records"]), [r["id"] for r in parsed["records"]])
            self.assertTrue(body.endswith(b"\n"))
            self.assertNotIn(b"\r\n", body)
            for record in parsed["records"]:
                self.assertEqual(hashlib.sha256(record["id"].encode("utf-8")).hexdigest()[:2], prefix)
            flattened.extend(parsed["records"])
        self.assertEqual(source_index(records)["records"], sorted(flattened, key=lambda r: r["id"]))

    def test_large_flat_catalog_still_has_small_deterministic_shard_reads(self):
        records = self.synthetic_records(4096)
        manifest, shards = source_index_shards(records)
        self.assertGreater(len(json_bytes(source_index(records))), 256 * 1024)
        self.assertLess(len(json_bytes(manifest)), 64 * 1024)
        self.assertLess(max(len(body) for body in shards.values()), 32 * 1024)
        self.assertEqual((manifest, shards), source_index_shards(list(reversed(records))))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog/source-index.json"
            path.parent.mkdir()
            write_source_index(records, path)
            check_source_index(records, path)
            prefix = next(iter(shards))
            (path.parent / "source-index" / (prefix + ".json")).write_bytes(shards[prefix] + b" ")
            with self.assertRaisesRegex(ValueError, "shard checksum"):
                check_source_index(records, path)

    def test_refresh_only_removes_unchanged_obsolete_generated_shards(self):
        candidates = self.synthetic_records(20)
        chosen = {}
        for record in candidates:
            chosen.setdefault(hashlib.sha256(record["id"].encode()).hexdigest()[:2], record)
        records = list(chosen.values())[:3]
        self.assertEqual(3, len(records))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source-index.json"
            write_source_index(records, path)
            _, shards = source_index_shards(records)
            prefixes = [hashlib.sha256(r["id"].encode()).hexdigest()[:2] for r in records]
            modified = path.parent / "source-index" / (prefixes[2] + ".json")
            modified.write_text("manually replaced content", encoding="utf-8")
            unrelated = path.parent / "source-index/notes.txt"
            unrelated.write_text("keep unrelated file", encoding="utf-8")
            write_source_index(records[:1], path)
            self.assertFalse((path.parent / "source-index" / (prefixes[1] + ".json")).exists())
            self.assertEqual("manually replaced content", modified.read_text(encoding="utf-8"))
            self.assertEqual("keep unrelated file", unrelated.read_text(encoding="utf-8"))
            check_source_index(records[:1], path)

    def test_check_rejects_a_whole_shard_directory_resolving_outside_catalog(self):
        records = self.synthetic_records(3)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = root / "catalog"
            catalog.mkdir()
            path = catalog / "source-index.json"
            write_source_index(records, path)
            shard_dir = catalog / "source-index"
            external = root / "outside"
            external.mkdir()
            for shard in shard_dir.iterdir():
                (external / shard.name).write_bytes(shard.read_bytes())
            before = {p.name: p.read_bytes() for p in external.iterdir()}
            original_resolve = Path.resolve
            external_resolved = external.resolve()
            def redirected_resolve(value, *args, **kwargs):
                if value == shard_dir or value.is_relative_to(shard_dir):
                    return external_resolved / value.relative_to(shard_dir)
                return original_resolve(value, *args, **kwargs)
            # Reproduce directory-symlink resolution without requiring Windows
            # developer mode or elevated symlink privileges on the test host.
            with mock.patch.object(Path, "resolve", redirected_resolve):
                with self.assertRaisesRegex(ValueError, "shard directory escapes"):
                    check_source_index(records, path)
            self.assertEqual(before, {p.name: p.read_bytes() for p in external.iterdir()})
            check_source_index(records, path)


if __name__ == "__main__":
    unittest.main()
