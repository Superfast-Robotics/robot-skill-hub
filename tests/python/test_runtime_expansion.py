"""Diverse simulation proofs must bind goals, environments and actual adapter specs."""
import contextlib,copy,io,json,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tools'))
import generate_runtime_expansion as generator
from runtime_expansion import bound_receipt,version_key,measured_goal

class RuntimeExpansionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.plan=json.loads((ROOT/'catalog/runtime-expansion.json').read_text())

    def test_generated_recipes_and_contracts_need_no_simulator_for_inspection(self):
        with contextlib.redirect_stdout(io.StringIO()):generator.generate(check=True)
        self.assertEqual(len(self.plan['recipes']),132)
        self.assertEqual({r['backend'] for r in self.plan['recipes']},{'menagerie','robosuite','gymrobotics','lerobot','pandagym','dmcontrol','metaworld','mink','genesis'})
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

    def test_native_task_success_requires_a_sustained_window_not_one_transient_flag(self):
        recipe=next(r for r in self.plan['recipes'] if r['backend']=='metaworld')
        outputs={'success_window':[True]*5,'native_success':True,'control_effort':1.,'steps':5}
        self.assertTrue(measured_goal(recipe,outputs))
        for mutate in [lambda v:v.update(success_window=[True]),lambda v:v.update(success_window=[True,True,False,True,True]),
                       lambda v:v.update(native_success=False),lambda v:v.update(control_effort=0),lambda v:v.update(steps=1)]:
            changed=copy.deepcopy(outputs);mutate(changed);self.assertFalse(measured_goal(recipe,changed))
        recipe=next(r for r in self.plan['recipes'] if r['id']=='metaworld-sawyer-reach-v3')
        adapter=(ROOT/'recipes'/recipe['id']/'run.py').read_bytes();source=self.plan['sources'][recipe['source_id']]
        self.assertEqual(bound_receipt(ROOT,recipe,source,adapter)['passed'],3)
        changed=copy.deepcopy(recipe);changed['policy_class']='DifferentPolicy'
        with self.assertRaises(ValueError):bound_receipt(ROOT,changed,source,adapter)
        box=next(r for r in self.plan['recipes'] if r['id']=='metaworld-sawyer-box-close-v3')
        proof=bound_receipt(ROOT,box,source,(ROOT/'recipes'/box['id']/'run.py').read_bytes())
        self.assertEqual((proof['passed'],proof['failed']),(2,1))

    def test_cuda_controller_cannot_pass_on_a_forged_joint_error_or_cpu_run(self):
        recipe=next(r for r in self.plan['recipes'] if r['id']=='genesis-panda-joint-servo')
        outputs={'arm_joint_positions_rad':[.1]*7,'target_arm_joint_positions_rad':[.1]*7,'max_joint_error_rad':0.,
                 'finger_error_m':0.,'movement_m':.03,'cuda_simulation':True}
        self.assertTrue(measured_goal(recipe,outputs))
        for mutate in [lambda v:v.update(arm_joint_positions_rad=[1]*7),lambda v:v.update(cuda_simulation=False),
                       lambda v:v.update(finger_error_m=.01),lambda v:v.update(movement_m=0)]:
            changed=copy.deepcopy(outputs);mutate(changed);self.assertFalse(measured_goal(recipe,changed))

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

    def test_sustained_reward_claims_bind_the_complete_final_window(self):
        recipe=next(r for r in self.plan['recipes'] if r['id']=='dmcontrol-cartpole-balance')
        values={'reward_window':[1.]*100,'final_window_mean_reward':1.,'final_reward':1.,'minimum_window_reward':1.,'control_effort':1.}
        self.assertTrue(measured_goal(recipe,values))
        for mutate in [lambda v:v.update(reward_window=[0.]*100),lambda v:v.update(final_reward=0),lambda v:v.update(minimum_window_reward=0),lambda v:v.update(control_effort=0),lambda v:v.update(reward_window=[1.]*99)]:
            changed=copy.deepcopy(values);mutate(changed);self.assertFalse(measured_goal(recipe,changed))

    def test_new_runtime_preparation_keeps_regular_source_selection_and_native_goal_measurements(self):
        for ident in ['pandagym-panda-stack','dmcontrol-cartpole-balance']:
            record=json.loads((ROOT/'catalog/records'/(ident+'.json')).read_text())
            self.assertEqual(record['preparation']['source_selection'],'declared_paths')
            self.assertTrue(any(p.endswith('LICENSE') for p in record['source']['paths']))
        recipe=next(r for r in self.plan['recipes'] if r['id']=='pandagym-panda-stack')
        self.assertFalse(measured_goal(recipe,{'achieved_goal':[0]*6,'desired_goal':[1]*6,'error_m':0,'environment_success':True,'stack_height_m':0,'stack_alignment_m':0}))
        # Native Stack permits a flat pair at error 0.04; actual support is required.
        flat={'achieved_goal':[0,0,.02,0,0,.02],'desired_goal':[0,0,.02,0,0,.06],
              'error_m':.04,'environment_success':True,'stack_height_m':0,'stack_alignment_m':0}
        self.assertFalse(measured_goal(recipe,flat))
        good=copy.deepcopy(flat);good.update(achieved_goal=[0,0,.02,0,0,.06],error_m=0,stack_height_m=.04)
        self.assertTrue(measured_goal(recipe,good))
        forged=copy.deepcopy(flat);forged.update(error_m=0,stack_height_m=.04)
        self.assertFalse(measured_goal(recipe,forged))

if __name__=='__main__':unittest.main()
