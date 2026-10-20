# Hub-authored adapter: MIT. Upstream source/models retain their original licenses.
"""Source template for standalone, bounded JSON recipe adapters (MIT, Hub authors).

The generator embeds this template and a reviewed backend in each published
recipe. Importing this template does not import or execute upstream source.
"""
import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import random
import sys


class ContractError(ValueError):
    pass


def validate_data(value, schema, path='$'):
    """Supported, published JSON Schema subset; bool is never a number."""
    kind = schema.get('type')
    checks = {'object': lambda: isinstance(value, dict), 'array': lambda: isinstance(value, list),
              'number': lambda: type(value) in (int, float) and math.isfinite(value),
              'integer': lambda: type(value) is int, 'string': lambda: isinstance(value, str),
              'boolean': lambda: isinstance(value, bool), 'null': lambda: value is None}
    if kind and (kind not in checks or not checks[kind]()):
        raise ContractError(path + ': expected ' + str(kind))
    if 'enum' in schema and value not in schema['enum']:
        raise ContractError(path + ': unsupported value')
    if type(value) in (int, float):
        if not math.isfinite(value) or value < schema.get('minimum', value) or value > schema.get('maximum', value):
            raise ContractError(path + ': outside numeric bounds')
    if isinstance(value, dict):
        if len(value) > 32: raise ContractError(path + ': too many keys')
        for name in schema.get('required', []):
            if name not in value: raise ContractError(path + '.' + name + ': required')
        props = schema.get('properties', {})
        for name, item in value.items():
            if name not in props and schema.get('additionalProperties') is False:
                raise ContractError(path + '.' + name + ': unknown field')
            validate_data(item, props.get(name, {}), path + '.' + name)
    elif isinstance(value, list):
        if not schema.get('minItems', 0) <= len(value) <= schema.get('maxItems', 4096):
            raise ContractError(path + ': invalid array length')
        for i, item in enumerate(value): validate_data(item, schema.get('items', {}), path + '[' + str(i) + ']')
    elif isinstance(value, str) and len(value) > schema.get('maxLength', 4096):
        raise ContractError(path + ': string too long')


def verify_source(root, spec):
    root = Path(root).resolve()
    for name, expected in spec['source_hashes'].items():
        target = root / name
        if target.is_symlink() or not target.resolve().is_relative_to(root) or not target.is_file():
            raise ContractError('Pinned source missing or outside source root: ' + name)
        if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
            raise ContractError('Pinned source checksum changed: ' + name)
    return root


def load_upstream(root, relative):
    """Only a generator-pinned path is accepted; never a path from task input."""
    target = root / relative
    for directory in [root, root / 'PathPlanning', target.parent]:
        sys.path.insert(0, str(directory))
    module_spec = importlib.util.spec_from_file_location('rsh_upstream', target)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    if hasattr(module, 'show_animation'): module.show_animation = False
    return module


def clean_json(value):
    if hasattr(value, 'tolist'): return clean_json(value.tolist())
    if isinstance(value, dict): return {k: clean_json(v) for k,v in value.items()}
    if isinstance(value, (tuple, list)): return [clean_json(v) for v in value]
    if hasattr(value, 'item'): return clean_json(value.item())
    if isinstance(value, float) and not math.isfinite(value): raise ContractError('Non-finite output')
    return value


def adapter_main(spec, backend):
    parser = argparse.ArgumentParser(description=spec['name'])
    parser.add_argument('--source-dir')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--input', type=Path, help='UTF-8 JSON file; no code or paths inside task input')
    group.add_argument('--input-json', help='Inline JSON task input')
    group.add_argument('--example', action='store_true', help='Run the declared example input')
    group.add_argument('--describe', action='store_true', help='Read the contract without importing upstream code')
    args = parser.parse_args()
    try:
        if args.describe:
            print(json.dumps({'skill_id': spec['id'], 'interface': spec['interface'], 'example_input': spec['example']}, allow_nan=False))
            return 0
        if args.input:
            with args.input.open('rb') as stream: raw=stream.read(65537)
        else: raw=args.input_json.encode() if args.input_json else None
        if raw is not None and len(raw) > 65536: raise ContractError('Input exceeds 64 KiB')
        data = json.loads(raw) if raw is not None else spec['example']
        validate_data(data, spec['interface']['input_schema'])
        if not args.source_dir: raise ContractError('--source-dir is required for execution')
        root = verify_source(args.source_dir, spec)
        os.environ['MPLBACKEND'] = 'Agg'
        os.environ.setdefault('OMP_NUM_THREADS', '1')
        random.seed(data.get('seed', 0))
        # Upstream diagnostic prints do not contaminate the machine response.
        with contextlib.redirect_stdout(sys.stderr):
            outputs, checks = backend(root, data, spec)
        outputs, checks = clean_json(outputs), clean_json(checks)
        validate_data(outputs, spec['interface']['output_schema'])
        if not checks or not all(type(v) is bool for v in checks.values()): raise ContractError('Invalid postcondition report')
        ok = all(checks.values())
        print(json.dumps({'schema_version':'1','skill_id':spec['id'],'status':'task_complete' if ok else 'task_failed',
            'success':ok,'outputs':outputs,'checks':checks,'execution_domain':spec['interface']['execution_domain'],
            'source_commit':spec['source_commit'],'interface_version':'1','hardware_execution':False}, allow_nan=False, separators=(',',':')))
        return 0 if ok else 1
    except (ContractError, ValueError, OSError, ImportError) as error:
        print(json.dumps({'schema_version':'1','skill_id':spec['id'],'status':'failed','success':False,
            'reason_code':'invalid_input_or_environment','message':str(error),'hardware_execution':False}, allow_nan=False))
        return 2
    except Exception as error:
        print(json.dumps({'schema_version':'1','skill_id':spec['id'],'status':'failed','success':False,
            'reason_code':'execution_failed','message':str(error)[:1000],'hardware_execution':False}, allow_nan=False))
        return 1


"""MIT: finite simulation starting policies; simulator state is privileged input."""

def seed_backend(root, data, spec):
    import importlib.metadata
    import numpy as np
    for pin in spec['packages']:
        name,version=pin.split('==')
        if importlib.metadata.version(name).split('+')[0]!=version:raise ContractError('Pinned package version differs: '+name)
    os.environ.setdefault('MUJOCO_GL','egl')
    if spec['backend']!='dmcontrol':sys.path.insert(0,str(root))
    if spec['backend']=='robosuite':
        import robosuite as suite
        env=suite.make('Stack' if spec['operation']=='stack' else 'PickPlaceCan',robots=spec['robot'],has_renderer=False,has_offscreen_renderer=False,use_camera_obs=False,control_freq=20,horizon=800,ignore_done=True,initialization_noise=None)
        try:
            np.random.seed(data['seed']);obs=env.reset();steps=0
            def drive(target,grip,limit):
                nonlocal obs,steps
                for _ in range(limit):
                    a=np.zeros(env.action_dim);a[:3]=np.clip((target-obs['robot0_eef_pos'])*10,-1,1);a[-1]=grip
                    obs,_,_,_=env.step(a);steps+=1
            if spec['operation']=='stack':
                object_key='cubeA_pos';target=obs['cubeB_pos'].copy()+np.array([0,0,.045])
            else:
                object_key='Can_pos';target=np.asarray(env.target_bin_placements[3]).copy()+np.array([0,0,.06])
            initial=obs[object_key].copy()
            drive(initial+np.array([0,0,.15]),-1,80);drive(initial+np.array([0,0,.005]),-1,100)
            drive(initial+np.array([0,0,.005]),1,50);drive(initial+np.array([0,0,.22]),1,90)
            drive(target+np.array([0,0,.17]),1,100);drive(target,1,90)
            drive(target,-1,50);drive(target+np.array([0,0,.18]),-1,70)
            final=obs[object_key].copy();error=float(np.linalg.norm(final-target));success=bool(env._check_success())
            return {'object_xyz_m':final.tolist(),'target_xyz_m':target.tolist(),'error_m':error,'steps':steps,'environment_success':success}, {
                'native_environment_goal':success,'target_proximity':error<.08,'object_moved':bool(np.linalg.norm(final-initial)>.025),'finite_state':bool(np.isfinite(env.sim.data.qpos).all())}
        finally:env.close()
    if spec['backend']=='pandagym':
        import gymnasium as gym,panda_gym
        env=gym.make(spec['env_id'],render_mode='rgb_array',max_episode_steps=1500)
        try:
            obs,info=env.reset(seed=data['seed']);steps=0
            def move(target,grip,limit):
                nonlocal obs,info,steps
                for _ in range(limit):
                    action=np.clip((target-obs['observation'][:3])*12,-1,1)
                    if env.action_space.shape[0]==4:action=np.r_[action,grip]
                    obs,_,_,_,info=env.step(action);steps+=1
            def transfer(body,target,release=True):
                obj=np.asarray(env.unwrapped.sim.get_base_position(body)).copy()
                move(obj+np.array([0,0,.13]),1,35);move(obj+np.array([0,0,.003]),1,35)
                move(obj+np.array([0,0,.003]),-1,25);move(obj+np.array([0,0,.18]),-1,40)
                move(target+np.array([0,0,.16]),-1,45);move(target,-1,45)
                if release:
                    move(target,1,25);move(target+np.array([0,0,.15]),1,30)
                else:move(target,-1,40)
            goal=obs['desired_goal'].copy()
            if spec['operation']=='reach':move(goal,0,120)
            elif spec['operation']=='pick_place':transfer('object',goal,release=goal[2]<.06)
            elif spec['operation']=='stack':
                transfer('object1',goal[:3]);transfer('object2',goal[3:])
            else:
                obj=np.asarray(env.unwrapped.sim.get_base_position('object')).copy()
                direction=goal[:2]-obj[:2];direction/=max(np.linalg.norm(direction),1e-8)
                behind=obj-np.r_[direction*.08,0]
                move(behind+np.array([0,0,.12]),1,35);move(behind,1,35)
                for _ in range(220):
                    obj=np.asarray(env.unwrapped.sim.get_base_position('object'))
                    if np.linalg.norm(goal[:2]-obj[:2])<.025:break
                    target=goal.copy();target[2]=obj[2];move(target,1,1)
                move(obs['observation'][:3]+np.array([0,0,.12]),1,30)
            error=float(np.linalg.norm(obs['achieved_goal']-goal))
            success=bool(info['is_success']);tolerance=.04 if spec['operation']!='stack' else .06
            return {'achieved_goal':obs['achieved_goal'].tolist(),'desired_goal':goal.tolist(),'error_m':error,'steps':steps,'environment_success':success}, {
                'native_environment_goal':success,'strict_goal_error':error<tolerance,'finite_state':bool(np.isfinite(obs['observation']).all())}
        finally:env.close()
    if spec['backend']=='dmcontrol':
        # dm_control's wheel includes generated MuJoCo bindings absent from git.
        # Use that pinned distribution, and bind its runtime source to the archive.
        import dm_control
        installed=Path(dm_control.__file__).resolve().parent.parent
        for name,expected in spec['source_hashes'].items():
            if name.startswith('dm_control/') and hashlib.sha256((installed/name).read_bytes()).hexdigest()!=expected:
                raise ContractError('Installed DM Control differs from pinned source: '+name)
        from dm_control import suite
        from scipy.linalg import solve_discrete_are
        env=suite.load(spec['domain'],spec['task'],task_kwargs={'random':data['seed']})
        try:
            env.reset();p=env.physics;domain=spec['domain'];target=None;gain=None
            if domain=='reacher':
                # Solve kinematics in a separate physics copy; active state is never set.
                from scipy.optimize import least_squares
                probe=p.copy(share_model=True)
                def residual(q):
                    with probe.reset_context():probe.data.qpos[:]=q
                    return probe.finger_to_target()
                solutions=[least_squares(residual,q,max_nfev=150) for q in [p.data.qpos.copy(),np.zeros(2),np.array([1.,-2.]),np.array([-1.,2.])]]
                target=min(solutions,key=lambda s:np.linalg.norm(s.fun)).x
            elif domain=='cartpole':
                import mujoco
                probe=p.copy(share_model=True)
                with probe.reset_context():probe.data.qpos[:]=0;probe.data.qvel[:]=0
                n=2*probe.model.nv;A=np.zeros((n,n));B=np.zeros((n,probe.model.nu))
                mujoco.mjd_transitionFD(probe.model.ptr,probe.data.ptr,1e-6,True,A,B,None,None)
                Q=np.diag([2.,25.,1.,2.]);R=np.eye(1)*.01
                P=solve_discrete_are(A,B,Q,R);gain=np.linalg.solve(R+B.T@P@B,B.T@P@A)
            rewards=[];actions=[]
            for step in range(1000):
                if domain=='reacher':
                    error=(target-p.data.qpos+np.pi)%(2*np.pi)-np.pi
                    action=error*8-p.data.qvel*1.5
                elif domain=='point_mass':
                    error=p.named.data.geom_xpos['target',:2]-p.named.data.geom_xpos['pointmass',:2]
                    force=error*20-p.data.qvel*5
                    # Hard task randomizes the actuator directions. Invert the declared gears.
                    gear=np.asarray(p.model.wrap_prm).reshape(2,2).T
                    action=np.linalg.pinv(gear)@force
                elif domain=='cartpole':
                    q=p.data.qpos.copy();q[1]=(q[1]+np.pi)%(2*np.pi)-np.pi
                    action=-(gain@np.r_[q,p.data.qvel])
                elif domain=='pendulum':
                    theta=float(p.data.qpos[0]);velocity=float(p.data.qvel[0]);upright=np.cos(theta)
                    if upright>.8:action=np.array([-4*((theta+np.pi)%(2*np.pi)-np.pi)-.8*velocity])
                    else:
                        energy=.5*.025*velocity**2+.981*np.cos(theta)
                        direction=velocity if abs(velocity)>.05 else 1.
                        action=np.array([2.5*(.981-energy)*np.sign(direction)])
                elif domain=='finger':action=np.ones(env.action_spec().shape)*.8
                else:
                    # Cup tracks ball horizontally and damps its own velocity.
                    observation=env.task.get_observation(p);position=observation['position'];velocity=observation['velocity']
                    action=np.array([(position[2]-position[0])*20-velocity[0]*4, -velocity[1]*4])
                action=np.clip(action,env.action_spec().minimum,env.action_spec().maximum)
                ts=env.step(action);rewards.append(float(ts.reward));actions.append(float(np.linalg.norm(action)))
                if ts.last():break
            window=rewards[-100:];mean=float(np.mean(window));threshold=.6 if domain=='finger' else .9
            return {'final_window_mean_reward':mean,'final_reward':rewards[-1],'minimum_window_reward':min(window),'reward_window':window,'steps':len(rewards),'control_effort':float(np.sum(actions))}, {
                'sustained_native_reward':mean>=threshold,'nonzero_control':max(actions)>1e-5,
                'finite_state':bool(np.isfinite(p.data.qpos).all() and np.isfinite(p.data.qvel).all())}
        finally:env.close()
    raise ContractError('Unknown simulation backend')

def mainstream_backend(root,data,spec):
    # Bullet emits native diagnostics through fd 1, beyond Python redirect_stdout.
    # Preserve the single-object stdout protocol for ordinary callers as well.
    import ctypes
    saved=os.dup(1)
    try:
        os.dup2(2,1)
        return seed_backend(root,data,spec)
    finally:
        ctypes.CDLL(None).fflush(None)
        os.dup2(saved,1);os.close(saved)

SPEC = json.loads('{"id":"pandagym-panda-stack","name":"Panda Gym Stack closed-loop starting policy","backend":"pandagym","operation":"stack","interface":{"version":"1","kind":"task","abstraction_level":2,"execution_domain":"simulation","language":"python","input_transport":"json_file_or_inline","output_transport":"json_stdout","output_selector":"outputs","conventions":{"linear_unit":"m","angular_unit":"rad","time_unit":"s","coordinate_frame":"right_handed_world_xyz; +z_up","joint_order":"not_used","quaternion_order":"not_used"},"input_schema":{"type":"object","required":["seed"],"properties":{"seed":{"type":"integer","minimum":0,"maximum":10000}},"additionalProperties":false},"output_schema":{"type":"object","required":["achieved_goal","desired_goal","error_m","steps","environment_success"],"properties":{"achieved_goal":{"type":"array","minItems":6,"maxItems":6,"items":{"type":"number","minimum":-30,"maximum":30},"x-unit":"m","x-frame":"right_handed_world_xyz; +z_up"},"desired_goal":{"type":"array","minItems":6,"maxItems":6,"items":{"type":"number","minimum":-30,"maximum":30},"x-unit":"m","x-frame":"right_handed_world_xyz; +z_up"},"error_m":{"type":"number","minimum":0,"maximum":50},"steps":{"type":"integer","minimum":1,"maximum":1500},"environment_success":{"type":"boolean"}},"additionalProperties":false},"preconditions":["Use the exact recorded source, Linux Python 3.10 environment and pinned direct packages.","No physical robot, network actuation or external robot credentials."],"postconditions":["All reported checks must be true and all output numbers finite.","Success covers the declared goal and frozen cases, not arbitrary tasks or physical hardware."],"failure_codes":["invalid_input_or_environment","execution_failed","task_failed"],"composition":{"depends_on":[],"automatic_frame_conversion":false,"automatic_hardware_execution":false}},"example":{"seed":0},"source_hashes":{"README.md":"3d125f16b96d40e745deed1197bac861e576d68f42c8b7794b1cf656920411a9","setup.py":"959f21cee326dacfb8ad52a5e19e416496f0f270d53587a2ac6c722986b9f164","LICENSE":"6d6fb3fbccaa0000bb00c69b94a4393adcafcfe00717c1f2c7a38bdbad4e00c5","panda_gym/pybullet.py":"af07722bd0ced414c85de4e29ecae36823ef0a6842a3c4157530e9529a0b3b37","panda_gym/utils.py":"ce5c4d4579e3f17c726bdd7f68950adcd9c51cf483757cc81129de49d4fed570","panda_gym/__init__.py":"4f8da02b1c77b077601cca57f52155e47df9219aefab4279c5216f514181e63d","panda_gym/envs/panda_tasks.py":"a6f957c0ab0c396881cb6db11b4d55ea73e4821d45e69b2c50841a5aadcca37b","panda_gym/envs/core.py":"36b1d73344584f0b705952510de75dbe0255035061ef34bef1f907697c0e8fba","panda_gym/envs/__init__.py":"23fc4234af8c7baaead0586a675fb515953ebbc34fb1a79d024ed3f1b839c093","panda_gym/envs/tasks/stack.py":"ca80b5b981b658a29c56593c45fc7212cecaa6ae8683de00079cc78b5c9cfbc8","panda_gym/envs/tasks/flip.py":"9d405205134ba72b0e5ab1d6795016788af3ad99d07873bc8a78c47a440d221a","panda_gym/envs/tasks/slide.py":"587b72f1ab7716b759dc25456eef51b3d444d58125f4d0f50f3e6155a547377e","panda_gym/envs/tasks/push.py":"6e15494b78d93b127ac1c0e5e54ddf24deb7221cddce1f8e29e9a19c50fef8a8","panda_gym/envs/tasks/pick_and_place.py":"2e94a75c2b0ea0e6d59aaf124bf8526b3a886a2d07f44fafe9828b0dd792585d","panda_gym/envs/tasks/reach.py":"dd4907bc88f8e9fbc2b79d07291ae7d50c86eb5264d8c11ad6ee25607adbf9a7","panda_gym/envs/tasks/__init__.py":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855","panda_gym/envs/robots/panda.py":"f01efa5236849cb944a9f69ce525c843518d4edd4d00be35570dd730bfc377dd","panda_gym/envs/robots/__init__.py":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855","panda_gym/assets/__init__.py":"910ce1095335ad8321d7e3f6b44e5551ff3645ff9cb1db5f0a7fb4baeddd27ac"},"summary":"Panda Gym Stack closed-loop starting policy. Native IK actions, privileged simulator observations and a frozen three-seed evaluation; no state teleportation after reset.","observation_description":"Privileged simulator state and declared goals; no perception or real sensor validation.","goal_scope":"Native task success plus final Euclidean goal error <.06 m for the six-dimensional stack goal.","env_id":"PandaStack-v3","adapter_template":"seed_tasks","source_commit":"14d944120037a5bb637e629965f88bb9e13dba3b","packages":["panda-gym==3.0.7","pybullet==3.2.7","gymnasium==1.2.0","numpy==1.26.4"]}')

if __name__ == "__main__":
    raise SystemExit(adapter_main(SPEC, mainstream_backend))
