"""Evidence-backed totals, overlapping declarations and license boundaries."""
import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import build_catalog as builder
from coverage_report import build_coverage, coverage_tables, coverage_markdown


class CoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records=builder.load_records()
        cls.references=builder.load_references(r['id'] for r in cls.records)

    def test_current_complete_inventory_separates_computation_simulation_failed_and_unexecuted(self):
        report=build_coverage(self.records,self.references,ROOT,'a'*40,'https://example.test')
        self.assertEqual(report['totals'],{'preparation_recipes':194,'source_references':1897,'completed':169,
            'failed':14,'not_executed':11,'evidence_unbound':0,'completed_computations':33,
            'completed_simulations':136,'completed_hardware':0,'tested_environment_combinations':60,'reference_frameworks':67})
        self.assertEqual(report['case_runs_by_os'],{'linux':537,'windows':99})
        by_id={r['id']:r for r in report['recipes']}
        self.assertEqual(by_id['maniskill-panda-stack-pyramid']['state'],'failed')
        self.assertEqual(by_id['maniskill-xarm6-pick-cube']['tested_os'],[])
        self.assertEqual(by_id['pythonrobotics-astar-planner']['tested_os'],['linux','windows'])
        self.assertEqual(by_id['mujoco-unitree-go2-stand-control']['state'],'completed')
        self.assertEqual(by_id['mujoco-shadow-dexee-finger-control']['state'],'completed')
        self.assertEqual(by_id['robosuite-jaco-lift']['state'],'failed')
        self.assertEqual(by_id['lerobot-diffusion-pusht']['state'],'failed')
        self.assertEqual(sum(r['references'] for r in report['references']['by_framework']),1897)

    def test_changed_adapter_or_frozen_plan_never_inherits_old_completion(self):
        record=copy.deepcopy(next(r for r in self.records if r['id']=='pythonrobotics-astar-planner'))
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            paths=['catalog/executable-conversions.json','recipes/'+record['id']+'/run.py',
                   'evidence/runtime/executable-conversions-v1/'+record['id']+'.json']
            for name in paths:
                target=root/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/name,target)
            original=build_coverage([record],{'records':[]},root,'a'*40,'https://example.test')
            self.assertEqual(original['totals']['completed'],1)
            adapter=root/paths[1];old=adapter.read_bytes();adapter.write_bytes(old+b'\n# changed\n')
            changed=build_coverage([record],{'records':[]},root,'a'*40,'https://example.test')
            self.assertEqual(changed['totals']['completed'],0);self.assertEqual(changed['totals']['evidence_unbound'],1)
            self.assertEqual(changed['case_runs_by_os'],{})
            adapter.write_bytes(old)
            plan=json.loads((root/paths[0]).read_text());recipe=next(r for r in plan['recipes'] if r['id']==record['id'])
            recipe['cases'][0]['start']=[3,3];(root/paths[0]).write_text(json.dumps(plan))
            self.assertEqual(build_coverage([record],{'records':[]},root,'a'*40,'https://example.test')['totals']['evidence_unbound'],1)

    def test_reference_labels_are_declarations_count_each_tag_once_and_escape_html(self):
        refs={'records':[{'framework':'one','robots':['declared-only'], 'robot_types':['arm','arm','mobile'],
                          'capabilities':['<script>','<script>','planning'],'compatibility':[],
                          'evidence':{'runtime_verification':'not_run'}},
                         {'framework':'one','robots':[],'robot_types':['arm'],'capabilities':['planning'],
                          'compatibility':[],'evidence':{'runtime_verification':'not_run'}}]}
        report=build_coverage([],refs,ROOT,'a'*40,'https://example.test')
        self.assertEqual(report['references']['by_framework'],[{'label':'one','references':2}])
        self.assertEqual(report['references']['by_robot_type'][0],{'label':'arm','references':2})
        self.assertEqual(report['totals']['completed_hardware'],0)
        page=coverage_tables(report,'https://example.test',full=True)
        self.assertIn('&lt;script&gt;',page);self.assertNotIn('<script>',page)
        self.assertIn('Tags overlap',page)

    def test_metadata_cannot_relabel_simulation_as_hardware_or_claim_a_different_robot(self):
        original=next(r for r in self.records if r['id']=='pybullet-ik-skill')
        for change in [lambda r:r['interface'].update(execution_domain='hardware'),
                       lambda r:r['compatibility'][0].update(robot='real-panda')]:
            record=copy.deepcopy(original);change(record)
            report=build_coverage([record],{'records':[]},ROOT,'a'*40,'https://example.test')
            self.assertEqual(report['totals']['completed'],0)
            self.assertEqual(report['totals']['completed_hardware'],0)
            self.assertEqual(report['totals']['evidence_unbound'],1)

    def test_licenses_are_packaged_without_relabeling_upstream_or_modifying_verified_adapters(self):
        self.assertIn('Apache License',(ROOT/'LICENSE').read_text())
        self.assertEqual((ROOT/'recipes/LICENSE').read_bytes(),(ROOT/'tools/recipe_adapters/LICENSE').read_bytes())
        self.assertIn('MIT License',(ROOT/'recipes/LICENSE').read_text())
        self.assertEqual((ROOT/'LICENSE').read_bytes(),(ROOT/'plugins/robot-skill-hub/LICENSE').read_bytes())
        self.assertEqual((ROOT/'LICENSE').read_bytes(),(ROOT/'skills/find-robot-skills/LICENSE').read_bytes())
        for record in self.records:
            self.assertIn('MIT License',record['preparation']['files']['LICENSE'])
            self.assertIn('upstream',record['preparation']['files']['LICENSE_SCOPE.md'])
        self.assertEqual({r['license']['spdx'] for r in self.records},{'MIT','Apache-2.0','Zlib','BSD-3-Clause','BSD-3-Clause-Clear'})

    def test_repository_main_readme_uses_the_same_generated_statistics(self):
        report=build_coverage(self.records,self.references,ROOT,'a'*40,builder.DEFAULT_BASE)
        readme=(ROOT/'README.md').read_text(encoding='utf-8')
        section=readme.split('<!-- rsh-coverage:start -->\n',1)[1].split('<!-- rsh-coverage:end -->',1)[0]
        self.assertEqual(section,coverage_markdown(report,builder.DEFAULT_BASE))


if __name__=='__main__':unittest.main()
