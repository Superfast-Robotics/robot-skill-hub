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
import tempfile
import unittest
from urllib.parse import urljoin, urlparse

import build_catalog as builder
import reference_index


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.real_root = builder.ROOT
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for folder in ("catalog", "schemas", "recipes", "docs", "web"):
            shutil.copytree(self.real_root / folder, self.root / folder)
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

    def memory(self):
        record = json.loads(self.record_path().read_text(encoding='utf-8'))
        payload = {'schema_version':'1', 'skill_id':record['id'],
                   'base':{'hub_commit':'1'*40,'record_version':record['maintenance']['record_version'],'source_commit':record['source']['commit']},
                   'kind':'compatibility_note','summary':'Preserve sources on the unsupported host',
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
        self.build()
        site = self.root / "site"
        references = json.loads((site / "catalog/v1/references.json").read_text(encoding="utf-8"))["records"]
        thin_path = site / "catalog/v1/search.json"
        self.assertLess(len(thin_path.read_bytes()), 2 * 1024 * 1024)
        thin = json.loads(thin_path.read_text(encoding="utf-8"))
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
        self.assertEqual(version["resources"]["search"]["sha256"], hashlib.sha256(thin_path.read_bytes()).hexdigest())
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
        for key in ("search_url", "api_search_url", "mcp_url", "openapi_url", "intake_schema_url"):
            self.assertIn(key, contract["resources"])
        self.assertEqual(contract["resources"]["search_url"], "https://api.superfastrobotics.com/v1/search")
        self.assertEqual(contract["resources"]["search_index_url"], "https://example.test/hub/catalog/v1/search.json")
        sitemap = (site / "sitemap.xml").read_text(encoding="utf-8")
        official = json.loads((self.root / "catalog/references.json").read_text(encoding="utf-8"))["records"][0]
        self.assertIn("/references/" + official["id"] + "/", sitemap)
        self.assertIn("/openapi.json", sitemap)

    def test_public_agent_guides_and_their_local_links_are_published(self):
        self.build()
        site = self.root / "site"
        for name in ("agent-quickstart.md", "privacy.md", "discovery.md", "new-skills.md"):
            text = (site / name).read_text(encoding="utf-8")
            self.assertEqual(text, (self.root / "docs" / name).read_text(encoding="utf-8"))
            for href in re.findall(r"\[[^\]]*\]\(([^\s)]+)\)", text):
                resolved = urlparse(urljoin(builder.DEFAULT_BASE + "/" + name, href))
                if resolved.hostname == urlparse(builder.DEFAULT_BASE).hostname:
                    self.assertTrue((site / resolved.path.lstrip("/")).is_file(), f"{name}: {href}")
        for name in ("llms.txt", "llms-full.txt"):
            text = (site / name).read_text(encoding="utf-8")
            self.assertIn("/privacy.md", text)
            self.assertIn("/discovery.md", text)
        full = (site / "llms-full.txt").read_text(encoding="utf-8")
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
                 "submission_ids": ["sub_" + "7" * 64], "archive_path": archive_path,
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


if __name__ == '__main__':
    unittest.main()
