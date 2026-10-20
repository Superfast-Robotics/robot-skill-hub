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

SPEC = json.loads('{"id":"dmcontrol-point-mass-easy","name":"DM Control point mass easy feedback policy","backend":"dmcontrol","operation":"feedback_control","interface":{"version":"1","kind":"task","abstraction_level":2,"execution_domain":"simulation","language":"python","input_transport":"json_file_or_inline","output_transport":"json_stdout","output_selector":"outputs","conventions":{"linear_unit":"m","angular_unit":"rad","time_unit":"s","coordinate_frame":"Native pinned DM Control model world frame; no external frame conversion","joint_order":"not_used","quaternion_order":"not_used"},"input_schema":{"type":"object","required":["seed"],"properties":{"seed":{"type":"integer","minimum":0,"maximum":10000}},"additionalProperties":false},"output_schema":{"type":"object","required":["final_window_mean_reward","final_reward","minimum_window_reward","reward_window","steps","control_effort"],"properties":{"final_window_mean_reward":{"type":"number","minimum":0,"maximum":1},"final_reward":{"type":"number","minimum":0,"maximum":1},"minimum_window_reward":{"type":"number","minimum":0,"maximum":1},"reward_window":{"type":"array","minItems":100,"maxItems":100,"items":{"type":"number","minimum":0,"maximum":1}},"steps":{"type":"integer","minimum":100,"maximum":1000},"control_effort":{"type":"number","minimum":0,"maximum":100000}},"additionalProperties":false},"preconditions":["Use the exact recorded source, Linux Python 3.10 environment and pinned direct packages.","No physical robot, network actuation or external robot credentials."],"postconditions":["All reported checks must be true and all output numbers finite.","Success covers the declared goal and frozen cases, not arbitrary tasks or physical hardware."],"failure_codes":["invalid_input_or_environment","execution_failed","task_failed"],"composition":{"depends_on":[],"automatic_frame_conversion":false,"automatic_hardware_execution":false}},"example":{"seed":0},"source_hashes":{"README.md":"e53d82509e4fa008a85a55639a41a2bd941e2377d111b6eb3a05e3630bfffc75","setup.py":"8721942e69bb47ff0b1d2e3cb613f8a13783f77a44312a187e53624deab3ffe1","LICENSE":"58d1e17ffe5109a7ae296caafcadfdbe6a7d176f0bc4ab01e12a689b0499d8bd","pyproject.toml":"4b7828b34764595ad552cf26edaf9bf46b6e044fa18ba2ab11df558e2fb70302","dm_control/__init__.py":"6e1e701748b0aac62a82286062b742e5ae7184af86a7e05a947322a6ab4bd0f6","dm_control/mujoco/math.py":"b7d2ebf9854c58e293288cf4adb3394769bed5646fc0cc5f1a727cf5cfae05a5","dm_control/mujoco/index.py":"0fe26111e41458321723220137166db3b06a47f9fc7cbee443d78509f3df8c41","dm_control/mujoco/engine.py":"77acb7855c6615e79b2b4de2b4df2cfbf76c8d223d7d9f58f52635003a1c7b2c","dm_control/mujoco/__init__.py":"4779f19ed04a11c347b6aae355c27c07225165ebc6bd0cdabaef74b3150b8fe7","dm_control/mujoco/testing/image_utils.py":"be9b91739c27aea000d4f73713397820bd5ef04787c8a8cd9a53e30988d2f419","dm_control/mujoco/testing/generate_frames.py":"23fe0f5195aa61a9333f525a15338106fb013cf3f207d4d74f3740bd7fd1f84e","dm_control/mujoco/testing/decorators.py":"287ab2e70328a00cec3af42888ab8e3e04235cefb9569a5a59ce5e4fc0bdd16c","dm_control/mujoco/testing/__init__.py":"6e1e701748b0aac62a82286062b742e5ae7184af86a7e05a947322a6ab4bd0f6","dm_control/mujoco/testing/assets/model_with_third_order_actuators.xml":"94358c3483f29c71f214a6e5f78760613b64abf2dc3bcbc3ca05b7eaeac7d492","dm_control/mujoco/testing/assets/sphere.xml":"c79508a3036f69ddbf3060bdaa96c90316e35c2ff9bdc8832b6ca9fd9372a8e4","dm_control/mujoco/testing/assets/humanoid.xml":"a60a1694bc3e9a01863e91693d2959e318711ac57a4c2244fd34060944ec7504","dm_control/mujoco/testing/assets/cartpole_no_names.xml":"0cce65d3fcb57e05f76f5f0d55694ff7ed494f425e8ec96b726ff0542b3b2eb4","dm_control/mujoco/testing/assets/model_with_assets.xml":"9da8d495f5640b9c9c142f1ab61aba1506edb25634d4b084e400d3ad7b073617","dm_control/mujoco/testing/assets/model_with_ball_joints.xml":"d981e0384bd154fcefd0c2719168a9dd97bb1767410dfb812f1b19a2894548b3","dm_control/mujoco/testing/assets/cartpole.xml":"5bfa239f42814a62aa6b4b4cdd0c327560f6abf18d9654729f5a39638b8b3efd","dm_control/mujoco/testing/assets/arm.xml":"ed9744c53b7ac16fd64eb423a478ea22106a07d61a35214719f213fe8fbd7e98","dm_control/mujoco/testing/assets/__init__.py":"d455ec7aac5cbf1683f6dbb83e37a1c61e8b4a80907063b74f7cdd4b5adf2373","dm_control/mujoco/wrapper/util.py":"5e44851a15fe4124a05eeaeaa9b3ed8fcdfd37f66ab7f581924dbb3d6ebef06a","dm_control/mujoco/wrapper/core.py":"d55cdfa420a234d89c3436e1125036eb60b8e483e57edadcd04d12c44d514f86","dm_control/mujoco/wrapper/__init__.py":"d7bcb67c81652e021f769c8cf00b064b4c460433b1f1b1f86af5e932c4933225","dm_control/mujoco/wrapper/mjbindings/functions.py":"b2a480daec441172a3e1a40d90b992182007e0e1c8e58e2556b88a2c8adfa84a","dm_control/mujoco/wrapper/mjbindings/__init__.py":"7ac135552270f5c9db5f930e50df8989bb54a9655bb51bed06b5425a37e6a8f5","dm_control/suite/stacker.py":"2d49781742e8ffab61be5d8d16ffaaef8756e41d904280bf45064fc4cdcc6b3d","dm_control/suite/pendulum.xml":"6ce0aceacde5bd30bf9965d08a7f4e31e61319d85b59b03c1bda523e5710a115","dm_control/suite/finger.xml":"7d106eafc8c7ec95dd4cfb00c9216d1522862aa7bdf2ee86f64f923c551dacef","dm_control/suite/dog.xml":"ef63b1aabd9c318e0f8302995348b2750f21a1e49234beeca27a49d50e54067f","dm_control/suite/humanoid.py":"a9b2dc126200605a2f91e18402eccc23bea2f537ba43d859102f49b659992303","dm_control/suite/cheetah.py":"782f1119fe5dc3ffaa58fef72fb67161a114523195a405397d4d03d2364f602e","dm_control/suite/lqr.xml":"c4b128e316a36c2e1f4dd7385f970fbbfa072167864bc12ada35c7a9bdd3813b","dm_control/suite/humanoid_CMU.xml":"a3c1950d663225d85e2d6cf003ce1d77913877e791dba09307a125ae4f4fc5ca","dm_control/suite/quadruped.xml":"c6b0ade5f3160b155bbe673aec3e0430eed3273ae13b60880855647e82bf8334","dm_control/suite/humanoid.xml":"3aea178a6030ad10fde4889a0806085ee5d2cf69c4b5996577a7f7f8cfa39451","dm_control/suite/fish.xml":"a08777b8b3623359ff68a8d35f2df10ecae1e771c97fa270926bbd29254394c9","dm_control/suite/dog.py":"856d9c77b97d706e9650147ff28a3775b3d12201908cb2b41bdcf5087ba20113","dm_control/suite/acrobot.xml":"e203285c5779113bace0d9e1c6a1b1c7246dc019df6ded9790a99b8185ec5ed8","dm_control/suite/base.py":"1683c47ba2e89bab6be2ac7999c0d80f33a7a1fe9c58fa2ac8283d4f23cd9b5d","dm_control/suite/point_mass.xml":"2567ced7cf592f28fb4551e9de26074fd11ad0e343d2928b03ce5b21b9d9c8d0","dm_control/suite/humanoid_CMU.py":"dc69a0d9ac723af9154aa0dec03ba307589712d5086f8a6a23d93ddf4fee7b88","dm_control/suite/cartpole.py":"484bd4b71ed36bd44e8ebff850dab1475e6e2a1ac9c8b30296909332d5f682d8","dm_control/suite/lqr_solver.py":"2d753fd875168ff845d35376dcb6519a7a04d63deeea08abf3be7c1bc336b3df","dm_control/suite/ball_in_cup.xml":"34c70aafdc3459db807acb61f401e7157cfc35369bbcb712eda0e820ccb3a4f5","dm_control/suite/pendulum.py":"9ae4397928b64605a89bca00decd4d4a60a542d3fb46b9f3082e3a67f56fcc73","dm_control/suite/point_mass.py":"1319d4391287ec00d27008349aa2638048cb943db9ade9c89ce87b6606dfc1f7","dm_control/suite/manipulator.xml":"7f00a4b2c90104d6ac73769bda5913a18f89eabf06f2daa83dcaef2974e9e59b","dm_control/suite/reacher.py":"ee829f7f1130664f650144188ddefb7349d74e3102ac6337b37bac7d23612a78","dm_control/suite/quadruped.py":"044cd72860fe0fb7902657d48bc3c4afbad431f954c9ff9741422e7a65319a68","dm_control/suite/acrobot.py":"0cc44b7260ffafedb295d8ac387a4dd44d94748db9fa9b50c753d6e9dda41659","dm_control/suite/hopper.xml":"6e86c37515e34af796af664c4e24e0586e4047fe5243f304de119e83769048b8","dm_control/suite/finger.py":"5649c41be05647aacd427fadc335b999c4aa2306f682e72bfa7cca273dfc9f2f","dm_control/suite/swimmer.xml":"5ac233aa94bd0df6369ec683dfd56878e6431c2911f49c6a7bfc768e664bf3a1","dm_control/suite/stacker.xml":"b817e44c3ccf561ebd0ab922bcf1cb338973373891442fca622687f2f94db7fe","dm_control/suite/ball_in_cup.py":"84425b4252bfabb8c1ca1d8215b4ea0b0362013daea366bdf4e328f2ecde657d","dm_control/suite/fish.py":"f37abefbec54dd9fd4f942cde063e5061c81f4914cdd3c074f612cb590c4f6e9","dm_control/suite/explore.py":"91302fce061796055bb3015d00377c97ce6cf0e19a362047dba333876d61ef8f","dm_control/suite/walker.py":"826178d2a9a3299a5113c3d916a0469f44173143dd8561e4768d62a1e6ebf7db","dm_control/suite/hopper.py":"e59b6dd29b3c7f18c073bf73d0fd28ee8d5efdcda0bca3da5032563b3b713030","dm_control/suite/reacher.xml":"849e1e3dd8e79b8f5796bd6e32b0d7a51b916355584402d8f803d74ad35ad193","dm_control/suite/cheetah.xml":"47e3152e1213d6895ef36b36bbd399f1c7e0edf7d39f05675cd72bc5fbc14faa","dm_control/suite/lqr.py":"93bfd7a746247c28168c6f47621b5d1775a7eb40a3827b2977c379396f7457a9","dm_control/suite/cartpole.xml":"b1d184ffa2f74260a6ad3113cbf6f539a048055fcf735b7ca2dbe426dd66fc22","dm_control/suite/swimmer.py":"352ca41dd508a66933971a1a6688b7e8b58ef3f23f0d46c71a8ac3781e85bed7","dm_control/suite/__init__.py":"9b7002e4b70d7223376258173fff8ff7fa8ce53dd3535992f9e6dcb21a233760","dm_control/suite/manipulator.py":"c5ca13e50fadac40344ed67e42b6660c38edc70e2ea70cc8fa2b1adcc20e10c9","dm_control/suite/walker.xml":"e8b6dd3bb40826dffed0faed978d9c5dd0aead7efaa28c27c4bb2df663af874c","dm_control/suite/wrappers/pixels.py":"f335705592e40582df7d7c678aa75124ca5c48d4625ede90bece060c88519aa9","dm_control/suite/wrappers/mujoco_profiling.py":"7eaed9cdade26e5e960e57003a7973a67adee0c229f8f49b7ede24802684c1ec","dm_control/suite/wrappers/action_scale.py":"45ecdf70ed8e471a4c483652b1e958a7fe3f7d04f42337623756247ead313214","dm_control/suite/wrappers/action_noise.py":"b872188f4f9da642df416a90965357598ecb47db3b71d719c6cee9560f08240b","dm_control/suite/wrappers/__init__.py":"b7fb2d9d00a8df3a94486a3e6f9c837fee4cd76852c3a2ee53b7eb4af630e83a","dm_control/suite/utils/randomizers.py":"01a4621e187040054b1dedf8fa0e58508bf416fc6db23c76aca17b9ecc5ed351","dm_control/suite/utils/parse_amc.py":"85bd049fd326dfc9376baea824dfad6f752e13e2e07909fa72d56564ae88907e","dm_control/suite/utils/__init__.py":"631fc2ee727eaaf95af72b107408d013d1915edd83faaea7388e3f33b379f589","dm_control/suite/demos/mocap_demo.py":"f2a0197f88cb43da830e5a64de5dfb320b9aa2a3733204c50660ad7d49ca2667","dm_control/suite/common/visual.xml":"1e338ca511de35b902c4ca944d857c23fe4e7a5aea46a475cdc317dd454245b0","dm_control/suite/common/materials.xml":"83ee4f7d3f0c9b3003ad121c2c35169a32a922c437321278f27db60d577ccfac","dm_control/suite/common/skybox.xml":"71db77c7c88dd4e1b54eb394deecfba673bbf539d110de68aa229dee00abf107","dm_control/suite/common/__init__.py":"066d3b7f5095c0b915e05dc5a6dfc2dc11da637fc84323718a6fec9ca516a5da","dm_control/rl/control.py":"3ac4b726242ea31f28235cfc94ff87ebbd7238bc71a673024281c74b9aef1606","dm_control/rl/__init__.py":"2882f11418b38e0a5faa582a318610b6fd99b8a7bbe5fea0c27ffa2b73623612","dm_control/utils/rewards.py":"009f02389fd2af84b2955324707638e79a0e18b6a540dd7c254abf5096e157f3","dm_control/utils/inverse_kinematics.py":"efeba89184589aba0322437faef394b52960256187ee40b2144f2485752746ba","dm_control/utils/xml_tools.py":"546fdf5961323d47576e0cb9f76541d72236a4b91e037894fd7ba11cd58c914c","dm_control/utils/io.py":"9f1f0feb730ce818b191db725b320c594d0409d5c6d380da146c21a17f67d900","dm_control/utils/containers.py":"8c234b9e63bfff0b9f56418ad3d516660e6b6e777fef0f4089be53de40339cbb","dm_control/utils/transformations.py":"cdfd83831234aebd9a0121b93243cfb20a4ce4f795d0af9f14af8d081db165d6","dm_control/utils/__init__.py":"6e1e701748b0aac62a82286062b742e5ae7184af86a7e05a947322a6ab4bd0f6"},"summary":"DM Control point mass easy feedback policy. Bounded native-control simulation with privileged state; not a trained policy or hardware deployment.","observation_description":"Privileged simulator state and declared goals; no perception or real sensor validation.","goal_scope":"Mean native task reward over the final 100 control steps >= 0.9 with finite state and nonzero control. Episode rewards are not task-agnostic accuracy.","adapter_template":"seed_tasks","domain":"point_mass","task":"easy","source_commit":"3831fa523c160fe653d83a829d0a0c59715f5725","packages":["dm-control==1.0.34","mujoco==3.3.7","numpy==1.26.4"]}')

if __name__ == "__main__":
    raise SystemExit(adapter_main(SPEC, mainstream_backend))
