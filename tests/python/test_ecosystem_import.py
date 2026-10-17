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

    def test_library_and_commented_main_are_not_examples(self):
        for name, data in [("helper.py", b"import pinocchio\ndef helper():\n    return pinocchio.Model()\n"),
                           ("helper.cpp", b"// int main() { return 0; }\nvoid helper() {}\n")]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                importer.inspect_source(name, data)

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
