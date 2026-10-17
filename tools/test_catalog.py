"""Meaningful catalog integrity and publication proof tests (standard library)."""
import argparse
import contextlib
import hashlib
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest

import build_catalog as builder


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.real_root = builder.ROOT
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for folder in ("catalog", "schemas", "recipes", "docs/recipes", "web"):
            shutil.copytree(self.real_root / folder, self.root / folder)
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

    def test_rejects_non_pinned_download(self):
        self.mutate(lambda r: r['source'].update(archive_url='https://codeload.github.com/haosulab/ManiSkill/tar.gz/main'))
        with self.assertRaisesRegex(ValueError, "exact source commit"):
            builder.load_records()

    def test_rejects_runtime_success_without_artifacts(self):
        self.mutate(lambda r: r['evidence'].update(level='task_complete', runtime_verification='task_complete'))
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
