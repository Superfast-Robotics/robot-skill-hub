"""Diverse simulation proofs must bind goals, environments and actual adapter specs."""
import contextlib,copy,io,json,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tools'))
import generate_runtime_expansion as generator
from runtime_expansion import bound_receipt,version_key

class RuntimeExpansionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.plan=json.loads((ROOT/'catalog/runtime-expansion.json').read_text())

    def test_generated_recipes_and_contracts_need_no_simulator_for_inspection(self):
        with contextlib.redirect_stdout(io.StringIO()):generator.generate(check=True)
        self.assertEqual(len(self.plan['recipes']),36)
        self.assertEqual({r['backend'] for r in self.plan['recipes']},{'menagerie','robosuite','gymrobotics','lerobot'})
        for recipe in self.plan['recipes']:
            response=subprocess.run([sys.executable,str(ROOT/'recipes'/recipe['id']/'run.py'),'--describe'],capture_output=True,text=True,check=True)
            self.assertEqual(json.loads(response.stdout)['interface'],recipe['interface'])

    def test_metadata_cannot_promote_a_different_model_or_abstraction_to_an_old_run(self):
        recipe=next(r for r in self.plan['recipes'] if r['id']=='mujoco-franka-emika-panda-joint-control')
        source=self.plan['sources'][recipe['source_id']];adapter=(ROOT/'recipes'/recipe['id']/'run.py').read_bytes()
        self.assertEqual(bound_receipt(ROOT,recipe,source,adapter)['passed'],3)
        for action in [lambda r:r['environment'].update(robot='different-robot'),lambda r:r['interface'].update(execution_domain='hardware'),lambda r:r['interface'].update(abstraction_level=3),lambda r:r['cases'][0].update(joint_offset_rad=.12)]:
            changed=copy.deepcopy(recipe);action(changed)
            with self.assertRaises(ValueError):bound_receipt(ROOT,changed,source,adapter)
        with self.assertRaises(ValueError):bound_receipt(ROOT,recipe,source,adapter+b'\n# behavior revision\n')

    def test_goal_measurements_override_a_forged_success_flag_and_failed_cases_are_retained(self):
        recipe=next(r for r in self.plan['recipes'] if r['id']=='robosuite-panda-reach')
        source=self.plan['sources'][recipe['source_id']];adapter=(ROOT/'recipes'/recipe['id']/'run.py').read_bytes()
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'evidence/runtime/diverse-sim-v1'/(recipe['id']+'.json');path.parent.mkdir(parents=True)
            proof=copy.deepcopy(bound_receipt(ROOT,recipe,source,adapter));proof['cases'][0]['result']['outputs']['error_m']=1
            path.write_text(json.dumps(proof))
            with self.assertRaises(ValueError):bound_receipt(temp,recipe,source,adapter)
        jaco=next(r for r in self.plan['recipes'] if r['id']=='robosuite-jaco-lift')
        proof=bound_receipt(ROOT,jaco,self.plan['sources'][jaco['source_id']],(ROOT/'recipes'/jaco['id']/'run.py').read_bytes())
        self.assertEqual((proof['passed'],proof['failed']),(0,3))

    def test_source_selection_and_version_normalization_preserve_safety_bounds(self):
        self.assertEqual(version_key('0.5'),version_key('0.5.0'))
        self.assertEqual(version_key('2.7.1+cu126'),version_key('2.7.1'))
        self.assertNotEqual(version_key('2.7.2'),version_key('2.7.1'))
        recipe=next(r for r in self.plan['recipes'] if r['backend']=='lerobot')
        record=json.loads((ROOT/'catalog/records'/ (recipe['id']+'.json')).read_text())
        self.assertEqual(record['preparation']['source_selection'],'declared_paths')
        self.assertIn('src/lerobot/policies/diffusion/modeling_diffusion.py',recipe['source_paths'])
        self.assertTrue(all(p.startswith('src/lerobot/') or p in ['LICENSE','NOTICE','README.md','pyproject.toml'] for p in recipe['source_paths']))

if __name__=='__main__':unittest.main()
