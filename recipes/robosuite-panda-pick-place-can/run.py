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
            # Track the grasped object's pose, including its measured grasp offset.
            for desired,limit in [(target+np.array([0,0,.17]),100),(target,90)]:
                for _ in range(limit):drive(obs['robot0_eef_pos']+desired-obs[object_key],1,1)
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
                    direction=goal[:2]-obj[:2];direction/=max(np.linalg.norm(direction),1e-8)
                    target=obj+np.r_[direction*.025,0]
                    action=np.clip((target-obs['observation'][:3])*4,-.35,.35)
                    if env.action_space.shape[0]==4:action=np.r_[action,1]
                    obs,_,_,_,info=env.step(action);steps+=1
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

SPEC = json.loads('{"id":"robosuite-panda-pick-place-can","name":"Panda can pick and place into bin","backend":"robosuite","operation":"pick_place_can","interface":{"version":"1","kind":"task","abstraction_level":2,"execution_domain":"simulation","language":"python","input_transport":"json_file_or_inline","output_transport":"json_stdout","output_selector":"outputs","conventions":{"linear_unit":"m","angular_unit":"rad","time_unit":"s","coordinate_frame":"right_handed_world_xyz; +z_up","joint_order":"not_used","quaternion_order":"not_used"},"input_schema":{"type":"object","required":["seed"],"properties":{"seed":{"type":"integer","minimum":0,"maximum":10000}},"additionalProperties":false},"output_schema":{"type":"object","required":["object_xyz_m","target_xyz_m","error_m","steps","environment_success"],"properties":{"object_xyz_m":{"type":"array","minItems":3,"maxItems":3,"items":{"type":"number","minimum":-30,"maximum":30},"x-unit":"m","x-frame":"right_handed_world_xyz; +z_up"},"target_xyz_m":{"type":"array","minItems":3,"maxItems":3,"items":{"type":"number","minimum":-30,"maximum":30},"x-unit":"m","x-frame":"right_handed_world_xyz; +z_up"},"error_m":{"type":"number","minimum":0,"maximum":50},"steps":{"type":"integer","minimum":1,"maximum":800},"environment_success":{"type":"boolean"}},"additionalProperties":false},"preconditions":["Use the exact recorded source, Linux Python 3.10 environment and pinned direct packages.","No physical robot, network actuation or external robot credentials."],"postconditions":["All reported checks must be true and all output numbers finite.","Success covers the declared goal and frozen cases, not arbitrary tasks or physical hardware."],"failure_codes":["invalid_input_or_environment","execution_failed","task_failed"],"composition":{"depends_on":[],"automatic_frame_conversion":false,"automatic_hardware_execution":false}},"example":{"seed":0},"source_hashes":{"LICENSE":"177978cbece0a4c454c2aaec5b3f145b39270814874c43109da9e829c39d9cba","robosuite/__init__.py":"366c86888aab75328eb314cc0d4f3c2a460a06cf9e81ad25a6abbbdfa7ebd0dd","robosuite/environments/manipulation/lift.py":"2d88a5e350a68d32461e08b3f24d00bdf5d269257b33f9db5da86e8aea19ce7e","robosuite/controllers/parts/arm/osc.py":"e406c0620b039156e4643fae68983a6ca19234632897b8a87bd6062b98869796","robosuite/environments/manipulation/stack.py":"a1f3fd3ad687bb1ac8dd6032408adab26616076767da3ea0afa20807fee6133f","robosuite/environments/manipulation/pick_place.py":"58b435f32246f42bf8658d3d83f4e5d44e65513c3e84724f33663e012d8270de"},"summary":"Panda can pick and place into bin. Bounded operational-space feedback, simulated contact and native task success checks.","observation_description":"Privileged simulator state and declared goals; no perception or real sensor validation.","goal_scope":"Native Stack or PickPlaceCan task success plus object/target distance <.08 m after release and retreat. No object teleportation after reset.","robot":"Panda","adapter_template":"seed_tasks","source_commit":"824ac14cefcfb7ec125fe5eb2e0bad7364466154","packages":["robosuite==1.5.2","mujoco==3.3.7","numpy==1.26.4"]}')

if __name__ == "__main__":
    raise SystemExit(adapter_main(SPEC, mainstream_backend))
