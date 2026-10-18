import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import import_curated_sources as curated


class CuratedSourcesTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.cache=Path(self.tmp.name)
        real=json.loads((ROOT/'catalog/curated-source-projects.json').read_text(encoding='utf-8'))
        self.project=copy.deepcopy(real['projects'][0])
        def pin(path,text):
            raw=text.encode(); digest=hashlib.sha256(raw).hexdigest()
            (self.cache/(digest+'.txt')).write_bytes(raw)
            return {'path':path,'sha256':digest,'bytes':len(raw),'git_blob':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}
        self.project['license']={**self.project['license'],**pin('LICENSE','Apache License Version 2.0 - test fixture only')}
        self.project['evidence_files']=[]
        source=copy.deepcopy(self.project['artifacts'][0])
        text="from pathlib import Path\nPath('must-not-execute').write_text('bad')\n"
        source.update(pin('examples/fixture.py',text),format='python',contains=["write_text('bad')"])
        self.project['artifacts']=[source]
        self.manifest={'schema_version':'1','projects':[self.project]}

    def tearDown(self):
        self.tmp.cleanup()

    def test_source_is_parsed_as_data_and_retains_exact_pins(self):
        import os
        previous=Path.cwd()
        try:
            os.chdir(self.cache)
            result=curated.build(self.manifest,{'records':[]},self.cache)
        finally:
            os.chdir(previous)
        self.assertFalse((self.cache/'must-not-execute').exists())
        record=result['records'][0]
        self.assertEqual(record['source']['sha256'],self.project['artifacts'][0]['sha256'])
        self.assertEqual(record['evidence']['runtime_verification'],'not_run')
        self.assertFalse(record['access']['hub_prepare'])

    def test_corrupted_source_and_duplicate_identity_are_rejected(self):
        result=curated.build(self.manifest,{'records':[]},self.cache)
        existing=copy.deepcopy(result['records'][0]);existing['source_registry']='another-registry'
        with self.assertRaisesRegex(ValueError,'Duplicate'):
            curated.build(self.manifest,{'records':[existing]},self.cache)
        path=self.cache/(self.project['artifacts'][0]['sha256']+'.txt')
        path.write_text('changed')
        with self.assertRaisesRegex(ValueError,'identity mismatch'):
            curated.build(self.manifest,{'records':[]},self.cache)

    def test_actual_manifest_and_generated_records_agree_without_network(self):
        manifest=json.loads((ROOT/'catalog/curated-source-projects.json').read_text(encoding='utf-8'))
        records=json.loads((ROOT/'catalog/references.json').read_text(encoding='utf-8'))['records']
        actual={r['id']:r for r in records if r.get('source_registry')==curated.REGISTRY}
        expected={a['id']:(p,a) for p in manifest['projects'] for a in p['artifacts']}
        self.assertEqual(set(actual),set(expected))
        for ident,(project,artifact) in expected.items():
            record=actual[ident]
            self.assertEqual(record['source']['commit'],project['commit'])
            self.assertEqual(record['source']['sha256'],artifact['sha256'])
            self.assertEqual(record['requirements']['execution_domain'],artifact['execution_domain'])
            self.assertEqual(record['evidence']['runtime_verification'],'not_run')


if __name__=='__main__': unittest.main()
