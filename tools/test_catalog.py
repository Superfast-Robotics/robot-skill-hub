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
