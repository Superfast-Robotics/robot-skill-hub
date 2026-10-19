"""Interface, source-selection and generation contracts; no upstream execution."""
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
sys.path.insert(0,str(ROOT/'skills/find-robot-skills/scripts'))
from rshlib.interfaces import validate_interface,validate_handoff,validate_value
from rshlib.prepare import extract_archive
from rshlib.core import RshError,inspect
from generate_executable_recipes import render_adapter
import build_catalog as builder


class ExecutableContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan=json.loads((ROOT/'catalog/executable-conversions.json').read_text())
        cls.recipes={r['id']:r for r in cls.plan['recipes']}

    def test_all_contracts_validate_and_generated_adapters_match_reviewed_inputs(self):
        records=builder.load_records()
        for record in records:validate_interface(record['interface'])
        for recipe in self.recipes.values():
            self.assertEqual((ROOT/'recipes'/recipe['id']/'run.py').read_bytes(),render_adapter(recipe).encode())
            validate_value(recipe['example'],recipe['interface']['input_schema'])
        self.assertEqual(17+len(self.recipes),len(records))

    def test_source_adaptations_bind_exact_file_and_revision_without_promoting_reference(self):
        records=builder.load_records();refs=builder.load_references(r['id'] for r in records)
        links=builder.prepared_adaptation_map(records,refs,'https://hub.superfastrobotics.com')
        self.assertIn('pybullet-inverse-kinematics',links)
        ref=next(r for r in refs['records'] if r['id']=='pybullet-inverse-kinematics')
        result=inspect({'records':records,'references':{'records':[ref]}},ref['id'])
        self.assertEqual('source_reference',result['kind'])
        self.assertFalse(result['hub_prepare'])
        self.assertEqual('not_run',result['evidence']['runtime_verification'])
        self.assertEqual('pybullet-ik-skill',result['prepared_adaptations'][0]['id'])
        damaged=copy.deepcopy(records)
        target=next(r for r in damaged if r['id']=='pybullet-ik-skill');target['source']['commit']='0'*40
        with self.assertRaises(ValueError):builder.prepared_adaptation_map(damaged,refs,'https://hub.superfastrobotics.com')

    def test_concrete_handoff_requires_same_units_frame_order_and_actual_input_bounds(self):
        source=self.recipes['pythonrobotics-astar-planner']['interface']
        target=self.recipes['pythonrobotics-path-smoothing']['interface']
        path=[[2.,2.],[3.,3.],[4.,4.]]
        self.assertIs(validate_handoff(path,source,'path_xy',target,'path_xy'),path)
        for changes in [{'linear_unit':'cm'},{'coordinate_frame':'robot_base'}]:
            other=copy.deepcopy(target);other['conventions'].update(changes)
            with self.assertRaises(ValueError):validate_handoff(path,source,'path_xy',other,'path_xy')
        other=copy.deepcopy(target);other['input_schema']['properties']['path_xy']['x-order']=['y','x']
        with self.assertRaises(ValueError):validate_handoff(path,source,'path_xy',other,'path_xy')
        with self.assertRaises(ValueError):validate_handoff(path*100,source,'path_xy',target,'path_xy')

    def test_interface_rejects_unknown_or_unbounded_schemas_and_nonfinite_data(self):
        original=self.recipes['pythonrobotics-astar-planner']['interface']
        for transform in [lambda c:c['input_schema'].update({'$ref':'https://attacker.invalid/schema'}),
                          lambda c:c['input_schema']['properties']['start'].pop('maxItems'),
                          lambda c:c['conventions'].update(angular_unit='deg')]:
            damaged=copy.deepcopy(original);transform(damaged)
            with self.assertRaises(ValueError):validate_interface(damaged)
        for data in [{'start':[True,2]},{'start':[float('nan'),2]}]:
            bad={**self.recipes['pythonrobotics-astar-planner']['example'],**data}
            with self.assertRaises(ValueError):validate_value(bad,original['input_schema'])

    def test_describe_is_standalone_and_bad_input_precedes_source_or_dependency_loading(self):
        for ident in ['pythonrobotics-astar-planner','ruckig-online-trajectory','pybullet-ik-skill']:
            adapter=ROOT/'recipes'/ident/'run.py'
            result=subprocess.run([sys.executable,str(adapter),'--describe'],capture_output=True,text=True,check=True)
            self.assertEqual(ident,json.loads(result.stdout)['skill_id'])
            result=subprocess.run([sys.executable,str(adapter),'--input-json','{"unknown":true}'],capture_output=True,text=True)
            self.assertEqual(2,result.returncode)
            self.assertEqual('invalid_input_or_environment',json.loads(result.stdout)['reason_code'])

    def test_declared_file_extraction_preserves_full_archive_validation_without_creating_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);archive=root/'source.tar.gz';commit='a'*40
            with tarfile.open(archive,'w:gz') as bundle:
                item=tarfile.TarInfo('repo-'+commit);item.type=tarfile.DIRTYPE;bundle.addfile(item)
                for name,data in [('source.py',b'pass\n'),('LICENSE',b'license\n'),('unused.txt',b'not extracted')]:
                    item=tarfile.TarInfo('repo-'+commit+'/'+name);item.size=len(data);bundle.addfile(item,io.BytesIO(data))
                link=tarfile.TarInfo('repo-'+commit+'/link');link.type=tarfile.SYMTYPE;link.linkname='../../outside';bundle.addfile(link)
            out=root/'selected'
            hashes=extract_archive(archive,out,commit,{'source.py','LICENSE'})
            self.assertEqual({'source.py','LICENSE'},set(hashes))
            self.assertFalse((out/'unused.txt').exists());self.assertFalse((out/'link').exists())
            with self.assertRaises(RshError):extract_archive(archive,root/'unsafe',commit,{'link'})


if __name__=='__main__':unittest.main()
