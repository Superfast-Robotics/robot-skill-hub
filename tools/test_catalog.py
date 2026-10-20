"""Meaningful catalog integrity and publication proof tests (standard library)."""
import argparse
import copy
import contextlib
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import socket
import tempfile
import unittest
from unittest import mock
from urllib.parse import urljoin, urlparse

import build_catalog as builder
import reference_index


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.real_root = builder.ROOT
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for folder in ("catalog", "schemas", "recipes", "docs", "web", "evidence", "LICENSES"):
            shutil.copytree(self.real_root / folder, self.root / folder)
        for name in ('LICENSE', 'NOTICE', 'LICENSE_SCOPE.md', 'license-policy.json'):
            shutil.copyfile(self.real_root / name, self.root / name)
        for name in ("search.md", "source-files.md", "community.md"):
            guide = Path("skills/find-robot-skills/references") / name
            (self.root / guide).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.real_root / guide, self.root / guide)
        if (self.real_root / "server.json").exists():
            shutil.copyfile(self.real_root / "server.json", self.root / "server.json")
        builder.ROOT = self.root

    def tearDown(self):
        builder.ROOT = self.real_root
        self.temp.cleanup()

    def record_path(self):
        return self.root / "catalog/records/maniskill-panda-pick-cube.json"

    def mutate(self, action):
        path = self.record_path()
        record = json.loads(path.read_text(encoding="utf-8"))
        action(record)
        path.write_text(json.dumps(record) + "\n", encoding="utf-8")

    def build(self):
        args = argparse.Namespace(check=False, output=str(self.root / "site"), base_url="https://example.test/hub", hub_commit="1" * 40)
        with contextlib.redirect_stdout(io.StringIO()):
            builder.build(args)

    def search_inventory(self):
        site = self.root / 'site'
        manifest = json.loads((site / 'catalog/v2/search-manifest.json').read_text())
        records = []
        for page in manifest['pages']:
            raw = (site / page['path']).read_bytes()
            self.assertEqual(len(raw), page['bytes'])
            self.assertEqual(hashlib.sha256(raw).hexdigest(), page['sha256'])
            rows = json.loads(raw)['records']
            self.assertEqual(len(rows), page['records'])
            records.extend(rows)
        self.assertEqual(len(records), manifest['counts']['recipes'] + manifest['counts']['references'])
        return {**manifest, 'records': records}

    def memory(self, summary='Preserve sources on the unsupported host'):
        record = json.loads(self.record_path().read_text(encoding='utf-8'))
        payload = {'schema_version':'1', 'skill_id':record['id'],
                   'base':{'hub_commit':'1'*40,'record_version':record['maintenance']['record_version'],'source_commit':record['source']['commit']},
                   'kind':'compatibility_note','summary':summary,
                   'observation':'Download-only preparation preserved the exact source and recipe without creating a simulator environment.',
                   'resolution':'Use download-only for source preparation, and run the task on the documented host.',
                   'environment':{'runtime':'maniskill','robot':'panda','os':'windows'},
                   'evidence':{'level':'contributor_reported','command':'rsh.py prepare --download-only','result':'Source prepared; environment not created.','reported_by':'submitter'},
                   'attribution':{'contributor_label':'fixture agent','preserve_upstream_attribution':True},
                   'publication':{'public_submission_allowed':True}}
        material = {k:v for k,v in payload.items() if k not in ('attribution','publication')}
        material['base'] = {k:payload['base'][k] for k in ('record_version','source_commit')}
        fingerprint = hashlib.sha256(builder.canonical(material).encode()).hexdigest()
        principal = '2'*64
        ident = 'mem_'+hashlib.sha256(('rsh-memory-id-v1\0'+principal+'\0'+fingerprint).encode()).hexdigest()
        entry = {**payload,'memory_id':ident,'principal_id':principal,'fingerprint':fingerprint,
                 'hub_validation':{'level':'structure_checked','runtime':'not_run','result':'Structural checks only.'},
                 'created_at':'2026-10-17T00:00:00.000Z'}
        path = self.root / '.hub/memories' / (ident+'.json')
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(entry,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
        return path,entry

    def intake(self, ident="ros2-panda-grasp", standalone=False):
        """A reviewed data-only record, including a non-Python artifact."""
        pin, digest = "b" * 40, "c" * 64
        source = {"repository": "https://github.com/upstream/robot", "commit": pin,
                  "path": "examples/grasp.cpp", "url": f"https://github.com/upstream/robot/blob/{pin}/examples/grasp.cpp",
                  "sha256": digest, "bytes": 2000, "authors": ["Upstream authors"]}
        if standalone:
            del source["commit"]
            source.update(revision="sha256:" + digest, path="panda.onnx", url="https://models.robotics.org/panda.onnx")
        record = {"id": ident, "name": "Panda grasp", "summary": "A pinned robot artifact <script>metadata</script>.",
                  "framework": "ros2", "kind": "community_skill", "capabilities": ["grasp"], "aliases": [], "robots": ["panda"],
                  "source": source, "license": {"spdx": "Apache-2.0", "url": f"https://github.com/upstream/robot/blob/{pin}/LICENSE", "scope": "Artifact source only.", "verified": False},
                  "artifact": {"kind": "policy" if standalone else "code", "format": "onnx" if standalone else "cpp"},
                  "requirements": {"python": None, "packages": [], "hardware": ["panda"], "system": ["ROS 2"], "notes": "Inspect upstream setup."},
                  "invocation": {"entrypoint": "upstream runner", "notes": "Configure the upstream runtime before use."},
                  "access": {"mode": "source_reference", "hub_prepare": False, "instructions": "Inspect pinned upstream source before use.", "setup_url": "https://docs.ros.org/en/rolling/"},
                  "compatibility": [{"runtime": "ros2", "runtime_version": "unknown", "robot": "panda", "controller": "unknown", "observation": "unknown", "os": "linux", "status": "contributor_reported"}],
                  "evidence": {"level": "contributor_reported", "runtime_verification": "not_run", "checked_at": "2026-10-18", "inspection": "Data structure checked; no robot code executed."},
                  "maintenance": {"record_version": "intake-123", "last_checked": "2026-10-18", "upstream_status": "contributor_reported"}}
        path = self.root / "catalog/intake" / (ident + ".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        return path, record

    def test_git_and_standalone_intakes_publish_data_only_pages_and_exact_search_hashes(self):
        _, git = self.intake()
        _, artifact = self.intake("panda-policy-model", standalone=True)
        canonical_references = (self.root / "catalog/references.json").read_bytes()
        self.build()
        site = self.root / "site"
        published_references = json.loads((site / "catalog/v1/references.json").read_text(encoding="utf-8"))
        reference_snapshot = json.loads((self.root / "skills/find-robot-skills/assets/references.snapshot.json").read_text(encoding="utf-8"))
        self.assertEqual(published_references["hub_commit"], "1" * 40)
        self.assertEqual(reference_snapshot["hub_commit"], published_references["hub_commit"])
        self.assertEqual((self.root / "catalog/references.json").read_bytes(), canonical_references)
        references = published_references["records"]
        thin_path = site / "catalog/v1/search.json"
        thin = self.search_inventory()
        if thin_path.exists():
            self.assertLessEqual(len(thin_path.read_bytes()), builder.SEARCH_JSON_MAX_BYTES)
            self.assertEqual(json.loads(thin_path.read_text())['records'], thin['records'])
        self.assertEqual(thin["counts"]["references"], len(references))
        self.assertEqual(len(thin["records"]), thin["counts"]["recipes"] + len(references))
        for row in thin["records"]:
            relative = row["record_url"].removeprefix("https://example.test/hub/")
            self.assertEqual(row["record_sha256"], hashlib.sha256((site / relative).read_bytes()).hexdigest())
            self.assertIsInstance(row["compatibility"], list)
            self.assertNotIn("preparation", row)
            self.assertNotIn("requirements", row)
        for record in (git, artifact):
            row = next(r for r in thin["records"] if r["id"] == record["id"])
            self.assertEqual(row["source_commit"], record["source"].get("commit") or record["source"]["revision"])
            self.assertEqual(row["record_version"], "source-" + record["source"]["sha256"])
            self.assertEqual(row["runtime_verification"], "not_run")
            self.assertFalse(row["hub_prepare"])
            folder = site / "references" / record["id"]
            self.assertEqual(json.loads((folder / "skill.json").read_text(encoding="utf-8")), record)
            page = (folder / "index.html").read_text(encoding="utf-8")
            self.assertIn("&lt;script&gt;metadata&lt;/script&gt;", page)
            self.assertNotIn("<script", page)
            self.assertIn("not independently verified", page)
            self.assertIn("not_run", page)
            self.assertIn(record["source"]["sha256"], (folder / "README.md").read_text(encoding="utf-8"))
        version = json.loads((site / "catalog/v1/version.json").read_text(encoding="utf-8"))
        if thin_path.exists():
            self.assertEqual(version["resources"]["search"]["sha256"], hashlib.sha256(thin_path.read_bytes()).hexdigest())
        else:
            self.assertNotIn('search', version['resources'])
        self.assertEqual(version["counts"], thin["counts"])
        # This canonical official index stays independent of reviewed intake.
        canonical_index = json.loads((self.root / "catalog/source-index.json").read_text(encoding="utf-8"))
        self.assertEqual(canonical_index, json.loads((site / "catalog/v1/source-index.json").read_text(encoding="utf-8")))
        self.assertNotIn(git["id"], [r["id"] for r in canonical_index["records"]])

    def test_intake_publication_matches_only_exact_receipts_and_keeps_maintenance_version(self):
        path, record = self.intake(standalone=True)
        relative = path.relative_to(self.root).as_posix()
        revision = record["source"]["revision"]
        receipt = {"submission_id": "sub_" + "2" * 64, "skill_id": record["id"], "change_kind": "new_skill",
                   "new_record_version": record["maintenance"]["record_version"], "base": {"source_commit": revision},
                   "patch_paths": [relative], "patch_hashes": {relative: hashlib.sha256(path.read_bytes()).hexdigest()}}
        receipts = self.root / ".hub/submissions"
        receipts.mkdir(parents=True)
        (receipts / "valid.json").write_text(json.dumps(receipt), encoding="utf-8")
        changes = ({"base": {"source_commit": "b" * 40}}, {"change_kind": "patch"},
                   {"patch_hashes": {relative: "0" * 64}}, {"patch_paths": [relative, "README.md"]},
                   {"new_record_version": "source-" + record["source"]["sha256"]})
        for index, update in enumerate(changes):
            wrong = dict(receipt, **update, submission_id="sub_" + str(index + 3) * 64)
            (receipts / f"wrong-{index}.json").write_text(json.dumps(wrong), encoding="utf-8")
        self.build()
        manifest = json.loads((self.root / "site/catalog/v1/publication.json").read_text(encoding="utf-8"))
        proof = next(r for r in manifest["records"] if r["id"] == record["id"])
        self.assertEqual(proof["record_version"], "intake-123")
        self.assertEqual(proof["kind"], "source_reference")
        self.assertEqual(proof["source_commit"], revision)
        self.assertEqual(proof["recipe_url"], "https://example.test/hub/references/" + record["id"] + "/")
        self.assertEqual(proof["submission_ids"], [receipt["submission_id"]])
        self.assertEqual(proof["contribution_path_hashes"], receipt["patch_hashes"])
        self.assertNotEqual(hashlib.sha256((self.root / "site/references" / record["id"] / "skill.json").read_bytes()).hexdigest(), receipt["patch_hashes"][relative])
        # A semantically identical edit changes the actual contribution bytes.
        path.write_text(json.dumps(record, indent=4) + "\n", encoding="utf-8")
        self.build()
        manifest = json.loads((self.root / "site/catalog/v1/publication.json").read_text(encoding="utf-8"))
        proof = next(r for r in manifest["records"] if r["id"] == record["id"])
        self.assertEqual(proof["submission_ids"], [])

    def test_recipe_reference_and_intake_ids_cannot_collide(self):
        official = json.loads((self.root / "catalog/references.json").read_text(encoding="utf-8"))["records"][0]
        self.intake(official["id"])
        with self.assertRaisesRegex(ValueError, "Duplicate catalog id"):
            builder.load_references()
        (self.root / "catalog/intake" / (official["id"] + ".json")).unlink()
        self.intake("maniskill-panda-pick-cube")
        with self.assertRaisesRegex(ValueError, "Duplicate catalog id"):
            self.build()
        with self.assertRaisesRegex(ValueError, "Duplicate catalog id"):
            builder.load_references([official["id"]])

    def test_intake_cannot_escalate_evidence_or_omit_source_identity(self):
        path, record = self.intake()
        record["evidence"]["runtime_verification"] = "task_complete"
        path.write_text(json.dumps(record), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "runtime execution"):
            builder.load_references()
        path, record = self.intake(standalone=True)
        record["source"]["revision"] = "sha256:" + "d" * 64
        path.write_text(json.dumps(record), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "must match its SHA-256"):
            builder.load_references()

    def test_thin_compatibility_preserves_explicit_combinations_only(self):
        combos = [{"runtime": "ros2", "robot": "panda", "os": "linux"},
                  {"runtime": "mujoco", "robot": "ur5", "os": "macos"}]
        self.assertEqual(builder.explicit_compatibility({"compatibility": combos}), combos)
        self.assertEqual(builder.explicit_compatibility({"compatibility": combos[0]}), combos[:1])
        self.assertEqual(builder.explicit_compatibility({"framework": "ros2", "robots": ["panda", "ur5"]}), [])
        self.assertEqual(builder.explicit_compatibility({"compatibility": {"runtime": ["ros2", "mujoco"], "robot": ["panda", "ur5"]}}), [])

    def test_thin_source_search_keeps_robot_types_separate_from_model_compatibility(self):
        references = json.loads((self.root / "catalog/references.json").read_text(encoding="utf-8"))["records"]
        record = copy.deepcopy(next(row for row in references if row["id"] == "unitree-sdk2-python-example-g1-high-level-g1-loco-client-example-py"))
        record.pop("robots", None)
        record.pop("compatibility", None)
        destination = self.root / "site/references" / record["id"] / "skill.json"
        destination.parent.mkdir(parents=True)
        destination.write_text(json.dumps(record), encoding="utf-8")
        row = builder.search_row(record, self.root / "site", "https://example.test/hub")
        self.assertEqual(["humanoid"], row["robot_types"])
        self.assertEqual([], row["compatibility"])
        self.assertNotIn("robots", row)
        self.assertFalse(row["hub_prepare"])
        self.assertEqual("not_run", row["runtime_verification"])
        record["robot_types"] = "humanoid"
        with self.assertRaisesRegex(ValueError, "robot type discovery labels"):
            builder.search_row(record, self.root / "site", "https://example.test/hub")

    def test_builder_publishes_minimal_action_home_contract_openapi_and_indexnow(self):
        key = "public-indexnow-key-123456789"
        (self.root / "docs/indexnow-key.txt").write_text(key + "\n", encoding="utf-8")
        spec = {"openapi": "3.1.0", "paths": {"/v1/search": {"get": {}}}}
        (self.root / "docs/public-api.openapi.json").write_text(json.dumps(spec), encoding="utf-8")
        self.build()
        site = self.root / "site"
        self.assertEqual(json.loads((site / "openapi.json").read_text(encoding="utf-8")), spec)
        self.assertEqual((site / (key + ".txt")).read_text(encoding="utf-8").strip(), key)
        home = (site / "index.html").read_text(encoding="utf-8")
        for text in ("/v1/search", "npx skills add", "SKILL.md", "register --help", "/v1/skills", "/mcp", "/openapi.json"):
            self.assertIn(text, home)
        self.assertLess(len(home), 12000)
        contract = json.loads((site / "agent.json").read_text(encoding="utf-8"))
        for key in ("search_url", "api_search_url", "mcp_url", "openapi_url", "intake_schema_url", "source_files_guide_url"):
            self.assertIn(key, contract["resources"])
        self.assertEqual(contract["resources"]["search_url"], "https://api.superfastrobotics.com/v1/search")
        self.assertEqual(contract['resources']['search_manifest_url'], 'https://example.test/hub/catalog/v2/search-manifest.json')
        if (site / 'catalog/v1/search.json').exists():
            self.assertEqual(contract['resources']['search_index_url'], 'https://example.test/hub/catalog/v1/search.json')
        else:
            self.assertEqual(contract['resources']['search_index_url'], contract['resources']['search_manifest_url'])
        self.assertEqual(contract['resources']['executable_skills_guide_url'], 'https://example.test/hub/executable-skills.md')
        self.assertEqual(contract['resources']['execution_interface_schema_url'], 'https://example.test/hub/schemas/execution-interface.schema.json')
        sitemap = (site / "sitemap.xml").read_text(encoding="utf-8")
        official = json.loads((self.root / "catalog/references.json").read_text(encoding="utf-8"))["records"][0]
        self.assertIn("/references/" + official["id"] + "/", sitemap)
        self.assertIn("/openapi.json", sitemap)
        self.assertIn("/source-files.md", sitemap)
        self.assertEqual((site / "source-files.md").read_bytes(),
                         (self.root / "skills/find-robot-skills/references/source-files.md").read_bytes())

    def test_public_agent_guides_and_their_local_links_are_published(self):
        self.build()
        site = self.root / "site"
        for name in ("agent-quickstart.md", "privacy.md", "discovery.md", "new-skills.md", "search.md", "community.md"):
            text = (site / name).read_text(encoding="utf-8")
            source = self.root / ("skills/find-robot-skills/references" if name in ("search.md", "community.md") else "docs") / name
            self.assertEqual(text, source.read_text(encoding="utf-8"))
            for href in re.findall(r"\[[^\]]*\]\(([^\s)]+)\)", text):
                resolved = urlparse(urljoin(builder.DEFAULT_BASE + "/" + name, href))
                if resolved.hostname == urlparse(builder.DEFAULT_BASE).hostname:
                    target = site / resolved.path.lstrip("/")
                    self.assertTrue(target.is_file() or (target / 'index.html').is_file(), f"{name}: {href}")
        for name in ("llms.txt", "llms-full.txt"):
            text = (site / name).read_text(encoding="utf-8")
            self.assertIn("/privacy.md", text)
            self.assertIn("/discovery.md", text)
            limit = builder.LLMS_TEXT_MAX_BYTES if name == "llms.txt" else builder.LLMS_FULL_TEXT_MAX_BYTES
            self.assertLessEqual(len(text.encode("utf-8")), limit)
        full = (site / "llms-full.txt").read_text(encoding="utf-8")
        self.assertTrue(full.startswith((self.root / "docs/agent-quickstart.md").read_text(encoding="utf-8")))
        self.assertIn("# Access measurement and privacy", full)
        self.assertIn("# Agent discovery", full)

    def test_official_index_and_license_provenance_are_checked(self):
        path = self.root / "catalog/source-index.json"
        index = json.loads(path.read_text(encoding="utf-8"))
        index["records"][0]["source_sha256"] = "0" * 64
        path.write_text(json.dumps(index), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "does not match"):
            builder.load_references()
        path.unlink()
        path = self.root / "catalog/references.json"
        references = json.loads(path.read_text(encoding="utf-8"))
        references["records"][0]["license"]["sha256"] = "bad"
        path.write_text(json.dumps(references), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "license provenance"):
            builder.load_references()

    def test_public_source_shards_keep_hashes_and_use_resolvable_public_paths(self):
        references = json.loads((self.root / "catalog/references.json").read_text(encoding="utf-8"))["records"]
        reference_index.write_source_index(references, self.root / "catalog/source-index.json")
        manifest_path = self.root / "catalog/source-index-manifest.json"
        canonical_raw = manifest_path.read_bytes()
        canonical_manifest = json.loads(canonical_raw)
        self.build()
        site = self.root / "site"
        public_path = site / "catalog/v1/source-index-manifest.json"
        public = json.loads(public_path.read_text(encoding="utf-8"))
        self.assertEqual(public["records"], len(references))
        self.assertEqual(public["scheme"], "sha256-id-prefix-2")
        covered = []
        for prefix, descriptor in public["shards"].items():
            original = canonical_manifest["shards"][prefix]
            self.assertEqual(descriptor["path"], f"catalog/v1/source-index/{prefix}.json")
            self.assertEqual(descriptor["url"], "https://example.test/hub/" + descriptor["path"])
            raw = (site / descriptor["path"]).read_bytes()
            self.assertEqual(raw, (self.root / original["path"]).read_bytes())
            self.assertEqual(hashlib.sha256(raw).hexdigest(), descriptor["sha256"])
            rows = json.loads(raw)["records"]
            self.assertEqual(descriptor["records"], len(rows))
            self.assertTrue(all(reference_index.source_prefix(row["id"]) == prefix for row in rows))
            covered.extend(rows)
        self.assertEqual(sorted(covered, key=lambda r: r["id"]), reference_index.source_index(references)["records"])
        self.assertEqual(manifest_path.read_bytes(), canonical_raw)
        version = json.loads((site / "catalog/v1/version.json").read_text(encoding="utf-8"))
        self.assertEqual(version["resources"]["source-index-manifest"]["sha256"], hashlib.sha256(public_path.read_bytes()).hexdigest())

    def test_source_shard_manifest_and_coverage_are_validated_before_publication(self):
        references = json.loads((self.root / "catalog/references.json").read_text(encoding="utf-8"))["records"]
        path = self.root / "catalog/source-index.json"
        reference_index.write_source_index(references, path)
        manifest_path = path.parent / "source-index-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        prefix, descriptor = next(iter(manifest["shards"].items()))
        shard = self.root / descriptor["path"]
        original_raw = shard.read_bytes()
        shard.write_text('{"schema_version":"1","records":[]}\n', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "checksum or coverage"):
            builder.load_references()
        shard.write_bytes(original_raw)
        manifest["shards"][prefix]["sha256"] = "0" * 64
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "manifest does not match"):
            builder.load_references()

    def test_generated_resources_fail_build_before_exceeding_consumer_budgets(self):
        # Per-ID documents and the small version pointer remain mandatory.
        # Large compatibility aggregates now have explicit v2 alternatives.
        cases = (("RECORD_JSON_MAX_BYTES", 1, "skill.json"),
                 ("VERSION_JSON_MAX_BYTES", 1, "version.json"))
        for constant, limit, target in cases:
            with self.subTest(resource=target), mock.patch.object(builder, constant, limit):
                with self.assertRaisesRegex(ValueError, re.escape(target) + r".*UTF-8 budget"):
                    self.build()

    def test_memory_discovery_resource_uses_the_catalog_consumer_budget(self):
        self.memory()
        with mock.patch.object(builder, "CATALOG_JSON_MAX_BYTES", 1):
            with self.assertRaisesRegex(ValueError, r"Compatibility view metadata.*UTF-8 budget"):
                builder.publish_memories(builder.load_memories(), self.root / "site", "https://example.test/hub", "1" * 40)

    def test_forced_legacy_limits_keep_complete_v2_inventory_findings_and_receipt_history(self):
        # Materialize an older aggregate in this fixture only, then prove that
        # the real bounded publisher removes it rather than retaining stale data.
        with mock.patch.object(builder, 'SEARCH_JSON_MAX_BYTES', 4 * 1024 * 1024):
            self.build()
        site = self.root / "site"
        self.assertTrue((site / "catalog/v1/search.json").exists())
        self.assertTrue((site / "catalog/v1/publication.json").exists())
        path, added = self.intake("zz-new-pinned-policy", standalone=True)
        relative = path.relative_to(self.root).as_posix()
        receipt = {"submission_id": "sub_" + "8" * 64, "skill_id": added["id"], "change_kind": "new_skill",
                   "new_record_version": added["maintenance"]["record_version"], "base": {"source_commit": added["source"]["revision"]},
                   "patch_paths": [relative], "patch_hashes": {relative: hashlib.sha256(path.read_bytes()).hexdigest()}}
        receipts = self.root / ".hub/submissions"
        receipts.mkdir(parents=True, exist_ok=True)
        (receipts / "current.json").write_text(json.dumps(receipt), encoding="utf-8")
        old_path, original, accepted, archive = self.archived_intake("zz-historical-policy", standalone=True)
        updated = copy.deepcopy(original)
        updated["maintenance"]["record_version"] = "intake-456"
        updated["summary"] = "Current metadata differs from the originally accepted source reference."
        old_path.write_text(json.dumps(updated), encoding="utf-8")
        memories = [self.memory(summary=f"Distinct useful fixture finding number {i}") for i in range(8)]
        stale = site / "catalog/v2/submissions" / ("sub_" + "0" * 64 + ".json")
        stale.write_text("stale generated file", encoding="utf-8")
        foreign = stale.with_name("operator-note.json")
        foreign.write_text("preserve unrelated file", encoding="utf-8")
        with mock.patch.multiple(builder, CATALOG_JSON_MAX_BYTES=12000, SEARCH_JSON_MAX_BYTES=1000,
                                 PUBLICATION_JSON_MAX_BYTES=1000, V2_PAGE_MAX_BYTES=8192, V2_PAGE_MAX_RECORDS=3):
            self.build()
        self.assertFalse((site / "catalog/v1/search.json").exists())
        self.assertFalse((site / "catalog/v1/publication.json").exists())
        self.assertFalse(stale.exists())
        self.assertEqual(foreign.read_text(encoding="utf-8"), "preserve unrelated file")
        version = json.loads((site / "catalog/v1/version.json").read_text(encoding="utf-8"))
        self.assertNotIn("search", version["resources"])

        def complete_pages(name):
            public_path = site / "catalog/v2" / (name + ".json")
            raw = public_path.read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), version["resources"][name]["sha256"])
            manifest = json.loads(raw)
            rows = []
            for descriptor in manifest["pages"]:
                leaf = (site / descriptor["path"]).read_bytes()
                self.assertEqual(descriptor["bytes"], len(leaf))
                self.assertEqual(descriptor["sha256"], hashlib.sha256(leaf).hexdigest())
                self.assertLessEqual(len(leaf), 8192)
                page = json.loads(leaf)
                self.assertEqual(page["hub_commit"], "1" * 40)
                self.assertEqual(descriptor["records"], len(page["records"]))
                self.assertLessEqual(len(page["records"]), 3)
                rows.extend(page["records"])
            self.assertEqual(len(rows), manifest["records"])
            return manifest, rows, raw

        search, rows, _ = complete_pages("search-manifest")
        findings, finding_rows, finding_raw = complete_pages("memory-manifest")
        self.assertEqual(search["records"], version["counts"]["recipes"] + version["counts"]["references"])
        expected_ids = {record["id"] for record in builder.load_records()}
        expected_ids.update(record["id"] for record in builder.load_references()["records"])
        self.assertEqual({row["id"] for row in rows}, expected_ids)
        self.assertEqual(search["counts"], version["counts"])
        self.assertEqual(search["memory_manifest"], {"path": "catalog/v2/memory-manifest.json", "sha256": hashlib.sha256(finding_raw).hexdigest(),
                                                   "bytes": len(finding_raw), "records": len(memories)})
        self.assertEqual(findings["records"], len(memories))
        selected = next(row for row in rows if row["id"] == added["id"])
        self.assertEqual(selected["source_url"], added["source"]["url"])
        self.assertEqual(selected["record_sha256"], hashlib.sha256((site / "references" / added["id"] / "skill.json").read_bytes()).hexdigest())
        for resource, snapshot, total, complete_name in (
                ("index", "catalog", version["counts"]["recipes"], "search-manifest"),
                ("references", "references", version["counts"]["references"], "search-manifest"),
                ("memories", "memories", len(memories), "memory-manifest")):
            public = site / "catalog/v1" / (resource + ".json")
            view = json.loads(public.read_text(encoding="utf-8"))
            offline = json.loads((self.root / "skills/find-robot-skills/assets" / (snapshot + ".snapshot.json")).read_text(encoding="utf-8"))
            self.assertLessEqual(public.stat().st_size, 12000)
            self.assertEqual(view, offline)
            self.assertEqual(view["hub_commit"], "1" * 40)
            self.assertFalse(view["coverage"]["complete"])
            self.assertEqual(view["coverage"]["total_records"], total)
            self.assertEqual(view["coverage"]["included_records"], len(view["records"]))
            self.assertLess(len(view["records"]), total)
            self.assertTrue(view["coverage"]["complete_manifest_url"].endswith("/" + complete_name + ".json"))
        subset = json.loads((site / "catalog/v1/references.json").read_text(encoding="utf-8"))
        self.assertNotIn(added["id"], [r["id"] for r in subset["records"]])
        current = json.loads((site / "catalog/v2/submissions" / (receipt["submission_id"] + ".json")).read_text(encoding="utf-8"))
        self.assertEqual(current["records"][0]["submission_ids"], [receipt["submission_id"]])
        self.assertEqual(current["records"][0]["contribution_path_hashes"], receipt["patch_hashes"])
        historical = json.loads((site / "catalog/v2/submissions" / (accepted["submission_ids"][0] + ".json")).read_text(encoding="utf-8"))
        self.assertEqual(historical["records"], [])
        self.assertEqual(historical["history"][0]["hub_commit"], "9" * 40)
        old_proof = historical["history"][0]["records"][0]
        for field in ("kind", "record_version", "source_commit", "contribution_path_hashes", "archive_sha256", "submission_ids"):
            self.assertEqual(old_proof[field], accepted[field])
        self.assertEqual((site / f"releases/{original['id']}/intake-123/skill.json").read_bytes(), archive.read_bytes())
        for memory_path, entry in memories:
            ident = entry["memory_id"]
            proof = json.loads((site / "catalog/v2/memories" / (ident + ".json")).read_text(encoding="utf-8"))["memories"][0]
            row = next(r for r in finding_rows if r["memory_id"] == ident)
            self.assertEqual((site / "memories" / (ident + ".json")).read_bytes(), memory_path.read_bytes())
            self.assertEqual(proof["content_sha256"], hashlib.sha256(memory_path.read_bytes()).hexdigest())
            self.assertEqual(row["content_sha256"], proof["content_sha256"])
            self.assertEqual(row["fingerprint"], entry["fingerprint"])

    def test_oversized_reference_metadata_cannot_publish_a_record_the_api_cannot_read(self):
        path = self.root / "catalog/references.json"
        references = json.loads(path.read_text(encoding="utf-8"))
        record = references["records"][0]
        record["summary"] = "한" * (builder.RECORD_JSON_MAX_BYTES // 3 + 1)
        path.write_text(json.dumps(references, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, r"references.*skill.json.*UTF-8 budget"):
            self.build()
        self.assertFalse((self.root / "site/references" / record["id"] / "skill.json").exists())

    def test_published_memory_keeps_exact_immutable_bytes_and_data_only_projection(self):
        path,entry = self.memory()
        self.build()
        index = json.loads((self.root/'site/catalog/v1/memories.json').read_text())
        self.assertEqual(index['interpretation'],'data_only')
        public = index['records'][0]
        self.assertNotIn('principal_id', public)
        self.assertEqual(public['curation'],'maintainer_merged')
        self.assertEqual(public['trust'],'contributor_reported')
        raw = (self.root/'site/memories'/path.name).read_bytes()
        self.assertEqual(raw,path.read_bytes())
        self.assertEqual(public['content_sha256'],hashlib.sha256(raw).hexdigest())
        manifest = json.loads((self.root/'site/catalog/v1/publication.json').read_text())
        self.assertEqual(manifest['memories'][0]['fingerprint'],entry['fingerprint'])
        self.assertEqual(manifest['memories'][0]['base_hub_commit'],entry['base']['hub_commit'])

    def test_memory_cannot_be_modified_without_a_new_content_identity(self):
        path,entry = self.memory()
        entry['observation']='This report was changed after its original intake and must fail.'
        path.write_text(json.dumps(entry),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'content identity'):
            builder.load_memories()

    def test_memory_cannot_escalate_verification_or_add_private_environment_fields(self):
        path,entry = self.memory()
        entry['evidence']['level']='task_complete'
        path.write_text(json.dumps(entry),encoding='utf-8')
        with self.assertRaises(ValueError):builder.load_memories()
        path,entry = self.memory()
        entry['environment']['api_key']='a private value'
        path.write_text(json.dumps(entry),encoding='utf-8')
        with self.assertRaises(ValueError):builder.load_memories()

    def test_memory_nullable_fields_and_schema_bounds_are_enforced(self):
        path,entry = self.memory()
        entry['resolution']={'unexpected':'object'}
        path.write_text(json.dumps(entry),encoding='utf-8')
        with self.assertRaises(ValueError):builder.load_memories()
        path,entry = self.memory()
        entry['summary']='x'*301
        path.write_text(json.dumps(entry),encoding='utf-8')
        with self.assertRaises(ValueError):builder.load_memories()

    def test_rejects_non_pinned_download(self):
        self.mutate(lambda r: r['source'].update(archive_url='https://codeload.github.com/haosulab/ManiSkill/tar.gz/main'))
        with self.assertRaisesRegex(ValueError, "exact source commit"):
            builder.load_records()

    def test_rejects_runtime_success_without_artifacts(self):
        self.mutate(lambda r: r['evidence'].update(level='task_complete', runtime_verification='task_complete', artifacts=[]))
        with self.assertRaisesRegex(ValueError, "actual runtime evidence"):
            builder.load_records()

    def test_failed_attempt_publishes_without_promoting_positive_evidence(self):
        record = json.loads(self.record_path().read_text(encoding="utf-8"))
        attempt = {"status": "failed", "execution_performed": True, "success": False,
                   "reason_code": "task_objective_not_reached", "seed": 0, "elapsed_steps": 12,
                   "terminated": False, "truncated": False, "exit_code": 1, "timed_out": False,
                   "workflow_run_id": "123", "verified_hub_commit": "1" * 40,
                   "record_version": record["maintenance"]["record_version"], "source_commit": record["source"]["commit"],
                   "environment": {key: record["compatibility"][0][key]
                                   for key in ("runtime", "runtime_version", "robot", "controller", "observation", "os")}}
        def change(row):
            row["evidence"].update(level="import_verified", runtime_verification="import_verified",
                                   artifacts=["https://example.org/pinned/runtime-report.json"],
                                   hub_verification={"level": "import_verified", "runtime": "import_verified",
                                                     "last_task_attempt": attempt})
            row["compatibility"][0]["status"] = "source_reviewed"
        self.mutate(change)
        self.build()
        search = self.search_inventory()
        row = next(r for r in search["records"] if r["id"] == record["id"])
        self.assertEqual(row["last_task_attempt"], attempt)
        self.assertEqual(row["evidence_level"], "import_verified")
        self.assertEqual(row["runtime_verification"], "import_verified")
        self.assertNotIn("hub_verified", [c["status"] for c in row["compatibility"]])
        published = json.loads((self.root / "site/skills" / record["id"] / "skill.json").read_text())
        self.assertEqual(published["evidence"]["hub_verification"]["last_task_attempt"], attempt)
        # The publisher enforces semantic consistency beyond the schema's field types.
        self.mutate(lambda r: r["evidence"]["hub_verification"]["last_task_attempt"].update(success=True))
        with self.assertRaises(ValueError):
            builder.load_records()
        self.mutate(lambda r: (r["evidence"]["hub_verification"]["last_task_attempt"].update(success=False),
                               r["evidence"].update(artifacts=[])))
        with self.assertRaisesRegex(ValueError, "actual runtime artifacts"):
            builder.load_records()

    def test_future_task_attempt_status_remains_data_without_invented_measurements(self):
        attempt = {"status": "future_unmeasured_outcome", "environment": {"os": "linux"}}
        self.mutate(lambda r: r["evidence"]["hub_verification"].update(last_task_attempt=attempt))
        record = next(r for r in builder.load_records() if r["id"] == "maniskill-panda-pick-cube")
        self.assertEqual(record["evidence"]["hub_verification"]["last_task_attempt"], attempt)
        self.assertEqual(record["evidence"]["level"], "task_complete")

    def test_rejects_contribution_paths_to_workflows(self):
        self.mutate(lambda r: r['contribution']['allowed_paths'].append('.github/workflows/pages.yml'))
        with self.assertRaisesRegex(ValueError, "outside allowed recipe"):
            builder.load_records()

    def test_snapshot_embeds_actual_recipe_and_html_escapes_metadata(self):
        self.mutate(lambda r: r.update(summary='<script>alert("unsafe")</script>'))
        self.build()
        snapshot = json.loads((self.root / "skills/find-robot-skills/assets/catalog.snapshot.json").read_text(encoding="utf-8"))
        record = next(r for r in snapshot['records'] if r['id'] == 'maniskill-panda-pick-cube')
        wrapper = (self.root / "recipes/maniskill-panda-pick-cube/run.py").read_text(encoding="utf-8")
        self.assertEqual(record['preparation']['files']['run.py'], wrapper)
        page = (self.root / "site/skills/maniskill-panda-pick-cube/index.html").read_text(encoding="utf-8")
        self.assertIn('&lt;script&gt;', page)
        self.assertNotIn('<script>alert(', page)
        manifest = json.loads((self.root / "site/catalog/v1/publication.json").read_text(encoding="utf-8"))
        published = next(r for r in manifest['records'] if r['id'] == record['id'])
        for relative, digest in published['contribution_path_hashes'].items():
            self.assertEqual(digest, hashlib.sha256((self.root / relative).read_bytes()).hexdigest())

    def test_publication_only_contains_receipt_with_current_exact_content(self):
        record = json.loads(self.record_path().read_text(encoding="utf-8"))
        relative = f"catalog/records/{record['id']}.json"
        receipt = {'submission_id':'sub_'+'2'*64, 'skill_id':record['id'], 'new_record_version':record['maintenance']['record_version'], 'patch_hashes':{relative:hashlib.sha256(self.record_path().read_bytes()).hexdigest()}}
        receipts = self.root / ".hub/submissions"
        receipts.mkdir(parents=True)
        (receipts / 'valid.json').write_text(json.dumps(receipt), encoding="utf-8")
        wrong = dict(receipt, submission_id='sub_'+'3'*64, patch_hashes={relative:'0'*64})
        (receipts / 'wrong.json').write_text(json.dumps(wrong), encoding="utf-8")
        self.build()
        manifest = json.loads((self.root / "site/catalog/v1/publication.json").read_text(encoding="utf-8"))
        published = next(r for r in manifest['records'] if r['id'] == record['id'])
        self.assertEqual(published['submission_ids'], [receipt['submission_id']])

    def test_intake_evidence_schema_and_status_are_preserved(self):
        self.mutate(lambda r: (r['evidence'].update(level='not_run', runtime_verification='not_run', hub_verification={'level':'structure_checked','runtime':'not_run'}, contributor_reported={'level':'task_complete','reported_by':'submitter'}), r['compatibility'][0].update(status='contributor_reported')))
        self.build()
        page = (self.root / "site/skills/maniskill-panda-pick-cube/index.html").read_text(encoding="utf-8")
        self.assertIn('Compatibility status: contributor_reported', page)
        self.assertIn('Runtime: not_run / not_run', page)

    def test_past_publication_keeps_original_hashes_after_notes_change(self):
        self.build()
        manifest = json.loads((self.root / "site/catalog/v1/publication.json").read_text(encoding="utf-8"))
        proof = manifest['history'][0]['records'][0]
        note = 'docs/recipes/maniskill-panda-pick-cube.md'
        self.assertNotEqual(proof['contribution_path_hashes'][note], hashlib.sha256((self.root / note).read_bytes()).hexdigest())
        self.assertTrue(proof['submission_ids'])
        archived = self.root / 'site/releases' / proof['id'] / proof['record_version']
        record = json.loads((archived / 'skill.json').read_text(encoding='utf-8'))
        self.assertEqual(record['source']['commit'], proof['source_commit'])
        self.assertIn('Pinned record JSON', (archived / 'index.html').read_text(encoding='utf-8'))

    def archived_intake(self, ident="ros2-panda-grasp", standalone=False):
        path, record = self.intake(ident, standalone=standalone)
        relative = path.relative_to(self.root).as_posix()
        archive_path = f"catalog/releases/{ident}/{record['maintenance']['record_version']}.json"
        archive = self.root / archive_path
        archive.parent.mkdir(parents=True, exist_ok=True)
        # Public snapshots can use different whitespace than the accepted patch.
        archive.write_text(json.dumps(record, indent=4) + "\n", encoding="utf-8", newline="\n")
        proof = {"id": ident, "kind": "source_reference", "record_version": record["maintenance"]["record_version"],
                 "source_commit": record["source"].get("commit") or record["source"]["revision"],
                 "recipe_url": "https://previous.example.org/references/" + ident + "/", "compatibility": record["compatibility"],
                 "contribution_path_hashes": {relative: hashlib.sha256(path.read_bytes()).hexdigest()},
                 "submission_ids": ["sub_" + hashlib.sha256(ident.encode()).hexdigest()], "archive_path": archive_path,
                 "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}
        history_path = self.root / "catalog/publication-history.json"
        history = json.loads(history_path.read_text(encoding="utf-8"))
        release = next((r for r in history["releases"] if r["hub_commit"] == "9" * 40), None)
        if release is None:
            release = {"hub_commit": "9" * 40, "records": []}
            history["releases"].append(release)
        release["records"].append(proof)
        history_path.write_text(json.dumps(history, indent=2) + "\n", encoding="utf-8")
        return path, record, proof, archive

    def test_archived_git_and_standalone_intake_proofs_survive_current_version_changes(self):
        fixtures = [self.archived_intake(), self.archived_intake("panda-policy-model", standalone=True)]
        for path, original, proof, archive in fixtures:
            updated = copy.deepcopy(original)
            updated["maintenance"]["record_version"] = "intake-456"
            updated["source"]["sha256"] = "d" * 64
            updated["summary"] = "Current metadata and source have changed since publication."
            if updated["source"].get("commit"):
                previous = updated["source"]["commit"]
                updated["source"]["commit"] = "e" * 40
                updated["source"]["url"] = updated["source"]["url"].replace(previous, "e" * 40)
            else:
                updated["source"]["revision"] = "sha256:" + "d" * 64
            path.write_text(json.dumps(updated), encoding="utf-8")
        self.build()
        manifest = json.loads((self.root / "site/catalog/v1/publication.json").read_text(encoding="utf-8"))
        release = next(r for r in manifest["history"] if r["hub_commit"] == "9" * 40)
        for path, original, accepted, archive in fixtures:
            proof = next(p for p in release["records"] if p["id"] == original["id"])
            for field in ("kind", "record_version", "source_commit", "compatibility", "contribution_path_hashes", "submission_ids", "archive_sha256"):
                self.assertEqual(proof[field], accepted[field])
            self.assertEqual(proof["record_version"], "intake-123")
            self.assertNotIn("archive_path", proof)
            self.assertNotEqual(proof["contribution_path_hashes"][path.relative_to(self.root).as_posix()], hashlib.sha256(path.read_bytes()).hexdigest())
            current = next(p for p in manifest["records"] if p["id"] == original["id"])
            self.assertEqual(current["kind"], "source_reference")
            self.assertEqual(current["record_version"], "intake-456")
            relative = f"releases/{original['id']}/intake-123/"
            self.assertEqual(proof["recipe_url"], "https://example.test/hub/" + relative)
            folder = self.root / "site" / relative
            self.assertEqual((folder / "skill.json").read_bytes(), archive.read_bytes())
            self.assertEqual(hashlib.sha256((folder / "skill.json").read_bytes()).hexdigest(), proof["archive_sha256"])
            self.assertEqual(json.loads((folder / "skill.json").read_text(encoding="utf-8")), original)
            page = (folder / "index.html").read_text(encoding="utf-8")
            self.assertIn("Historical published source reference", page)
            self.assertIn("intake-123", page)
            self.assertIn("source-" + original["source"]["sha256"], page)
            self.assertIn('rel="canonical" href="https://example.test/hub/' + relative + '"', page)
            self.assertIn("/references/" + original["id"] + "/", page)
            self.assertIn("Hub preparation adapter: <code>false</code>", page)
            self.assertIn("runtime verification: <code>not_run</code>", page)
            self.assertNotIn("preparation files", page)
            self.assertNotIn("prepare --plan", page)
            self.assertNotIn("<script", page)
            readme = (folder / "README.md").read_text(encoding="utf-8")
            self.assertIn("Historical published source reference", readme)
            self.assertIn("Record version: `intake-123`", readme)
            self.assertIn("Source identity version: `source-" + original["source"]["sha256"] + "`", readme)

    def test_archived_source_reference_cannot_become_a_recipe_or_claim_runtime_execution(self):
        _, original, proof, archive = self.archived_intake(standalone=True)
        history_path = self.root / "catalog/publication-history.json"
        original_history = json.loads(history_path.read_text(encoding="utf-8"))
        cases = (("runtime", lambda r, p: r["evidence"].update(runtime_verification="task_complete")),
                 ("adapter", lambda r, p: r["access"].update(hub_prepare=True)),
                 ("recipe kind", lambda r, p: p.update(kind="preparation_recipe")),
                 ("unknown kind", lambda r, p: p.update(kind="executable")),
                 ("source identity", lambda r, p: p.update(source_commit="sha256:" + "e" * 64)),
                 ("maintenance version", lambda r, p: p.update(record_version="source-" + r["source"]["sha256"])))
        for label, mutate in cases:
            with self.subTest(case=label):
                history = copy.deepcopy(original_history)
                candidate = copy.deepcopy(original)
                stored = next(r for r in history["releases"] if r["hub_commit"] == "9" * 40)["records"][0]
                mutate(candidate, stored)
                archive.write_text(json.dumps(candidate), encoding="utf-8")
                stored["archive_sha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
                history_path.write_text(json.dumps(history), encoding="utf-8")
                with self.assertRaises(ValueError):
                    builder.load_publication_history()

    def test_immutable_source_archives_obey_the_published_record_byte_budget(self):
        _, _, _, _ = self.archived_intake(standalone=True)
        release = next(r for r in builder.load_publication_history() if r["hub_commit"] == "9" * 40)
        with mock.patch.object(builder, "RECORD_JSON_MAX_BYTES", 1):
            with self.assertRaisesRegex(ValueError, r"skill.json.*UTF-8 budget"):
                builder.publish_history([release], self.root / "site", "https://example.test/hub")

    def test_rejects_tampered_historical_record(self):
        archive = next((self.root / 'catalog/releases').glob('*/*.json'))
        archive.write_text('{}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'archive checksum mismatch'):
            self.build()

    def test_all_agent_pages_are_plain_html(self):
        self.build()
        for path in (self.root / 'site').rglob('*.html'):
            page = path.read_text(encoding='utf-8')
            self.assertNotIn('<style', page)
            self.assertNotIn('<script', page)
            self.assertNotIn('rel="stylesheet"', page)
            self.assertNotIn(' style=', page)
        for relative in ('llms.txt','llms-full.txt','robots.txt','catalog/v1/references.json'):
            self.assertTrue((self.root / 'site' / relative).is_file(), relative)


class PublicationBudgetTests(unittest.TestCase):
    def test_exact_utf8_boundary_succeeds_and_one_more_byte_preserves_existing_file(self):
        limit = builder.VERSION_JSON_MAX_BYTES
        value = {"summary": ""}
        overhead = len((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        remaining = limit - overhead
        value["summary"] = "한" * (remaining // 3) + "x" * (remaining % 3)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "version.json"
            builder.write_json(path, value, max_bytes=limit)
            original = path.read_bytes()
            self.assertEqual(len(original), limit)
            value["summary"] += "x"
            self.assertLess(len(json.dumps(value, ensure_ascii=False, indent=2) + "\n"), limit)
            with self.assertRaisesRegex(ValueError, "UTF-8 budget"):
                builder.write_json(path, value, max_bytes=limit)
            self.assertEqual(path.read_bytes(), original)

    @staticmethod
    def source_record(ident):
        return {"id": ident, "source": {"commit": "1" * 40, "sha256": hashlib.sha256(ident.encode()).hexdigest()}}

    def test_source_manifest_and_shard_raw_byte_limits_are_checked(self):
        records = [self.source_record("capacity-fixture")]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source-index.json"
            reference_index.write_source_index(records, path)
            manifest_path = path.parent / "source-index-manifest.json"
            original = manifest_path.read_bytes()
            manifest_path.write_bytes(original + b" " * (reference_index.SOURCE_MANIFEST_MAX_BYTES + 1 - len(original)))
            with self.assertRaisesRegex(ValueError, "manifest.*UTF-8 budget"):
                reference_index.check_source_index(records, path)
            manifest_path.write_bytes(original)
            prefix = reference_index.source_prefix(records[0]["id"])
            shard = path.parent / "source-index" / (prefix + ".json")
            original = shard.read_bytes()
            shard.write_bytes(original + b" " * (reference_index.SOURCE_SHARD_MAX_BYTES + 1 - len(original)))
            with self.assertRaisesRegex(ValueError, "shard.*UTF-8 budget"):
                reference_index.check_source_index(records, path)

    def test_first_overfull_hash_bucket_is_rejected_before_index_files_change(self):
        # Exercise real hash-prefix skew with small synthetic metadata only.
        records, candidate = [], 0
        while len(records) < 1000:
            ident = f"capacity-fixture-{candidate:09d}"
            if reference_index.source_prefix(ident) == "00":
                records.append(self.source_record(ident))
            candidate += 1
        low, high = 0, len(records)
        while low < high:
            middle = (low + high + 1) // 2
            size = len(reference_index.json_bytes(reference_index.source_index(records[:middle])))
            if size <= reference_index.SOURCE_SHARD_MAX_BYTES:
                low = middle
            else:
                high = middle - 1
        self.assertGreater(low, 0)
        self.assertLess(low, len(records))
        _, shards = reference_index.source_index_shards(records[:low])
        self.assertLessEqual(len(shards["00"]), reference_index.SOURCE_SHARD_MAX_BYTES)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source-index.json"
            path.write_bytes(b"existing index remains unchanged\n")
            with self.assertRaisesRegex(ValueError, "shard 00.*UTF-8 budget"):
                reference_index.write_source_index(records[:low + 1], path)
            self.assertEqual(path.read_bytes(), b"existing index remains unchanged\n")
            self.assertFalse((path.parent / "source-index-manifest.json").exists())
            self.assertFalse((path.parent / "source-index").exists())


class AgentEntryTextTests(unittest.TestCase):
    """Agent entry text stays bounded independently of catalog inventory size."""
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.docs = self.root / "docs"
        self.docs.mkdir()
        self.quickstart = "# Agent quickstart\n\nFIRST_ACTION: find, inspect and check existing authorization.\n"
        guides = {"agent-quickstart.md": self.quickstart, "memory.md": "# Shared findings\n\nExact-source observations only.\n",
                  "new-skills.md": "# New skills\n\nPinned metadata and reviewed intake.\n",
                  "contributing.md": "# Contributions\n\nScoped existing Hub paths.\n",
                  "compatibility.md": "# Compatibility\n\nLONG_METADATA: unknown remains unknown.\n" * 100,
                  "privacy.md": "# Access measurement and privacy\n\nSet RSH_TELEMETRY=off.\n"}
        for name, text in guides.items():
            (self.docs / name).write_text(text, encoding="utf-8")
        source = self.root / "skills/find-robot-skills/references/source-files.md"
        source.parent.mkdir(parents=True)
        source.write_text("# Source-file retrieval\n\nInert bytes; no installation or execution.\n", encoding="utf-8")
        patched = mock.patch.object(builder, "ROOT", self.root)
        patched.start()
        self.addCleanup(patched.stop)

    def test_large_inventory_does_not_expand_entry_documents_or_precede_quickstart(self):
        small_recipes = [{"id": "private-recipe-sentinel", "name": "RECIPE_MUST_NOT_BE_ENUMERATED"}]
        small_references = {"records": [{"id": "private-reference-sentinel", "name": "REFERENCE_MUST_NOT_BE_ENUMERATED"}]}
        recipes = [{"id": f"synthetic-recipe-{i}", "name": "RECIPE_MUST_NOT_BE_ENUMERATED"} for i in range(10000)]
        references = {"records": [{"id": f"synthetic-reference-{i}", "name": "REFERENCE_MUST_NOT_BE_ENUMERATED",
                                   "source": {"private_fixture_marker": "FULL_RECORD_JSON_MUST_NOT_BE_EMBEDDED"}} for i in range(25000)]}
        base, hub = "https://example.test/hub", "1" * 40
        with mock.patch.object(builder, "build", side_effect=AssertionError("No catalog build")), mock.patch.object(
                builder, "markdown", side_effect=AssertionError("Do not render each recipe")), mock.patch.object(
                socket, "getaddrinfo", side_effect=AssertionError("No network")):
            small = (builder.discovery_text(small_recipes, base, small_references, memory_count=7),
                     builder.full_text(small_recipes, base, hub, small_references, memory_count=7))
            large = (builder.discovery_text(recipes, base, references, memory_count=7),
                     builder.full_text(recipes, base, hub, references, memory_count=7))
        normalize = lambda text: re.sub(r"\d+ preparation recipes and \d+ source references; \d+ published findings", "COUNTS", text)
        for minimal, expanded in zip(small, large):
            self.assertEqual(normalize(minimal), normalize(expanded))
            self.assertIn("10000 preparation recipes and 25000 source references; 7 published findings", expanded)
            for marker in ("RECIPE_MUST_NOT_BE_ENUMERATED", "REFERENCE_MUST_NOT_BE_ENUMERATED", "FULL_RECORD_JSON_MUST_NOT_BE_EMBEDDED"):
                self.assertNotIn(marker, expanded)
            for route in (builder.API + "/v1/search", builder.API + "/v1/skills/{skill_id}", builder.API + "/v1/findings", builder.API + "/mcp",
                          "/catalog/v2/search-manifest.json", "/catalog/v2/memory-manifest.json", "/catalog/v1/version.json",
                          "/schemas/skill.schema.json", "/schemas/memory.schema.json", "/schemas/intake.schema.json",
                          "/source-files.md", "/memory.md", "/new-skills.md", "/contributing.md", "/references/{skill_id}/"):
                self.assertIn(route, expanded)
        self.assertLessEqual(len(large[0].encode("utf-8")), builder.LLMS_TEXT_MAX_BYTES)
        self.assertLessEqual(len(large[1].encode("utf-8")), builder.LLMS_FULL_TEXT_MAX_BYTES)
        self.assertTrue(large[1].startswith(self.quickstart))
        self.assertLess(large[1].index("FIRST_ACTION"), large[1].index("LONG_METADATA"))
        self.assertLess(large[1].index("FIRST_ACTION"), large[1].index("# Discovery resources and publication"))
        self.assertIn("# Source-file retrieval", large[1])
        self.assertIn("# Shared findings", large[1])
        self.assertIn("# New skills", large[1])
        self.assertIn("# Contributions", large[1])

    def test_oversized_public_guide_fails_before_replacing_full_entry_file(self):
        output = self.root / "site"
        output.mkdir()
        destination = output / "llms-full.txt"
        previous = b"keep the prior full usage guide\n"
        destination.write_bytes(previous)
        (self.docs / "memory.md").write_text("# Shared findings\n\n" + "\u20ac" * (builder.LLMS_FULL_TEXT_MAX_BYTES // 3 + 1), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, r"llms-full.txt.*UTF-8 budget"):
            builder.publish_agent_entry_texts(output, [], "https://example.test/hub", "1" * 40, {"records": []}, memory_count=0)
        self.assertEqual(destination.read_bytes(), previous)
        self.assertLessEqual((output / "llms.txt").stat().st_size, builder.LLMS_TEXT_MAX_BYTES)

    def test_directory_budget_is_also_enforced_before_any_entry_file_replacement(self):
        output = self.root / "site"
        output.mkdir()
        directory = output / "llms.txt"
        previous = b"keep the prior directory\n"
        directory.write_bytes(previous)
        base = "https://example.test/" + "x" * builder.LLMS_TEXT_MAX_BYTES
        with self.assertRaisesRegex(ValueError, r"llms.txt.*UTF-8 budget"):
            builder.publish_agent_entry_texts(output, [], base, "1" * 40, {"records": []})
        self.assertEqual(directory.read_bytes(), previous)
        self.assertFalse((output / "llms-full.txt").exists())


class ReferenceAcquisitionGuidanceTests(unittest.TestCase):
    """Pure page guidance checks; no build, source download or fixture allocation."""
    HUB, REVISION, DIGEST = "a" * 40, "b" * 40, "c" * 64

    def reference(self):
        return {"id": "fixture-source", "name": "Pinned source fixture", "summary": "An inert source-reference fixture.",
                "source": {"repository": "https://github.com/example/robot", "commit": self.REVISION,
                           "path": "example/main.py", "url": f"https://github.com/example/robot/blob/{self.REVISION}/example/main.py",
                           "sha256": self.DIGEST, "bytes": 128, "authors": ["Fixture author"]},
                "license": {"spdx": "NOASSERTION", "url": f"https://github.com/example/robot/blob/{self.REVISION}/LICENSE",
                            "scope": "Unresolved source terms only.", "verified": False},
                "access": {"mode": "source_reference", "hub_prepare": False, "instructions": "Inspect the pinned upstream source and setup."},
                "evidence": {"level": "contributor_reported", "runtime_verification": "not_run"}}

    def render(self, record):
        with mock.patch.object(socket, "getaddrinfo", side_effect=AssertionError("Page guidance must not resolve source hosts")), mock.patch.object(
                builder, "build", side_effect=AssertionError("Do not run a catalog build")):
            markdown = builder.reference_markdown(record, self.HUB)
            html = builder.reference_detail(record, "https://hub.superfastrobotics.com", self.HUB)
        return markdown, html

    def test_supported_reference_offers_the_same_pinned_command_as_the_cli_plan(self):
        record = self.reference()
        original = copy.deepcopy(record)
        markdown, html = self.render(record)
        plan = builder.plan_source(record, self.HUB)
        self.assertIn("rsh.py " + " ".join(plan["fetch_args"]), markdown)
        self.assertIn("--project ./experiment --json", markdown)
        self.assertIn("fetch_source_args", html)
        self.assertNotIn("retrieval is unavailable", markdown + html)
        self.assertEqual(original, record)

    def test_large_policy_keeps_upstream_identity_without_promising_cli_download(self):
        record = self.reference()
        record["source"].update(repository="https://huggingface.co/lerobot/smolvla_base", path="model.safetensors",
                                url=f"https://huggingface.co/lerobot/smolvla_base/resolve/{self.REVISION}/model.safetensors", bytes=906712520)
        record["artifact"] = {"kind": "policy", "format": "safetensors"}
        markdown, html = self.render(record)
        self.assertNotIn("rsh.py fetch-source", markdown)
        self.assertNotIn("fetch_source_args", html)
        for document in (markdown, html):
            self.assertIn("source_too_large", document)
            self.assertIn("8 MiB", document)
            self.assertIn("Use the pinned upstream source", document)
            self.assertIn("does not download this artifact", document)
            self.assertIn(record["source"]["url"], document)
            self.assertIn(self.REVISION, document)
            self.assertIn(self.DIGEST, document)
            self.assertIn("906712520", document)
            self.assertIn("NOASSERTION", document)
        self.assertNotIn("<script", html)


if __name__ == '__main__':
    unittest.main()
