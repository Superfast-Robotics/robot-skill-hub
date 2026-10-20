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


"""MIT: bounded simulation controllers; no physical I/O or model training."""

def mainstream_backend(root, data, spec):
    import importlib.metadata
    import numpy as np
    for package in spec['packages']:
        name,version=package.split('==',1)
        actual=importlib.metadata.version(name).split('+')[0].split('.')
        expected=version.split('.')
        while len(actual)>1 and actual[-1]=='0':actual.pop()
        while len(expected)>1 and expected[-1]=='0':expected.pop()
        if actual!=expected:raise ContractError('Pinned package version differs: '+name)
    os.environ.setdefault('MUJOCO_GL','egl')
    os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
    os.environ['WANDB_MODE']='disabled'
    backend=spec['backend'];seed=data['seed']
    np.random.seed(seed)
    if backend=='menagerie':
        import mujoco
        model=mujoco.MjModel.from_xml_path(str(root/spec['model_path']))
        state=mujoco.MjData(model)
        if model.nkey:mujoco.mj_resetDataKeyframe(model,state,0)
        mujoco.mj_forward(model,state)
        indices=[]
        for name in spec['interface']['output_schema']['properties']['joint_positions_rad']['x-order']:
            joint=model.joint(name).id
            candidates=[a for a in range(model.nu) if model.actuator_trntype[a]==0 and model.actuator_trnid[a,0]==joint and model.actuator_biasprm[a,1]<0]
            if len(candidates)!=1:raise ContractError('Expected one position actuator per declared joint')
            indices.append(candidates[0])
        joints=[int(model.actuator_trnid[a,0]) for a in indices]
        qaddrs=[int(model.jnt_qposadr[j]) for j in joints]
        for a,q in zip(indices,qaddrs):state.ctrl[a]=state.qpos[q]
        for _ in range(500):mujoco.mj_step(model,state)
        start=state.qpos[qaddrs].copy();target=start+data['joint_offset_rad']
        for k,(a,j) in enumerate(zip(indices,joints)):
            if model.jnt_limited[j]:target[k]=np.clip(target[k],model.jnt_range[j,0]+.02,model.jnt_range[j,1]-.02)
            if model.actuator_ctrllimited[a]:target[k]=np.clip(target[k],*model.actuator_ctrlrange[a])
            state.ctrl[a]=target[k]
        for _ in range(2500):mujoco.mj_step(model,state)
        final=state.qpos[qaddrs];error=float(np.max(np.abs(final-target)))
        moved=float(np.max(np.abs(final-start)));demand=float(np.max(np.abs(target-start)))
        return {'joint_positions_rad':final.tolist(),'target_joint_positions_rad':target.tolist(),'max_error_rad':error,'movement_rad':moved}, {
            'nontrivial_target':demand>=.03,'joint_goal_reached':error<.035,
            'actual_motion':moved>=.02,'finite_state':bool(np.isfinite(state.qpos).all() and np.isfinite(state.qvel).all())}
    if backend=='robosuite':
        sys.path.insert(0,str(root))
        import robosuite as suite
        env=suite.make('Lift',robots=spec['robot'],has_renderer=False,has_offscreen_renderer=False,use_camera_obs=False,
                       control_freq=20,horizon=500,ignore_done=True,initialization_noise=None)
        try:
            obs=env.reset();start=obs['robot0_eef_pos'].copy();initial_cube=obs['cube_pos'].copy()
            def drive(target,grip,steps):
                nonlocal obs
                for _ in range(steps):
                    action=np.zeros(env.action_dim);action[:3]=np.clip((target-obs['robot0_eef_pos'])*10,-1,1);action[-1]=grip
                    obs,_,_,_=env.step(action)
            if spec['operation']=='reach':
                target=start+np.asarray(data['offset_xyz_m']);drive(target,-1,150)
                error=float(np.linalg.norm(obs['robot0_eef_pos']-target))
                return {'final_xyz_m':obs['robot0_eef_pos'].tolist(),'target_xyz_m':target.tolist(),'error_m':error}, {
                    'nontrivial_target':bool(np.linalg.norm(target-start)>.025),'target_reached':error<.015,
                    'actual_motion':bool(np.linalg.norm(obs['robot0_eef_pos']-start)>.02),'finite_state':bool(np.isfinite(env.sim.data.qpos).all())}
            drive(initial_cube+np.array([0,0,.12]),-1,80)
            drive(initial_cube+np.array([0,0,.005]),-1,100)
            drive(initial_cube+np.array([0,0,.005]),1,50)
            drive(initial_cube+np.array([0,0,data['lift_height_m']]),1,120)
            height=float(obs['cube_pos'][2]-initial_cube[2]);success=bool(env._check_success())
            return {'cube_lift_m':height,'cube_xyz_m':obs['cube_pos'].tolist(),'environment_success':success}, {
                'environment_goal':success,'object_lifted':height>.07,'finite_state':bool(np.isfinite(env.sim.data.qpos).all())}
        finally:env.close()
    if backend=='gymrobotics':
        sys.path.insert(0,str(root))
        import gymnasium as gym,gymnasium_robotics
        gym.register_envs(gymnasium_robotics)
        env=gym.make(spec['env_id'],max_episode_steps=4000 if spec['operation']=='maze' else 1000)
        try:
            obs,info=env.reset(seed=seed);steps=0
            def move(target,grip,limit):
                nonlocal obs,info,steps
                for _ in range(limit):
                    action=np.r_[np.clip((target-obs['observation'][:3])*6,-1,1),grip]
                    obs,_,_,_,info=env.step(action);steps+=1
            if spec['operation']=='reach':move(obs['desired_goal'],0,100)
            elif spec['operation']=='pick_place':
                obj=obs['observation'][3:6].copy();goal=obs['desired_goal'].copy()
                move(obj+np.array([0,0,.12]),1,35);move(obj+np.array([0,0,.005]),1,30)
                move(obj+np.array([0,0,.005]),-1,30);move(obj+np.array([0,0,.2]),-1,35)
                move(goal+np.array([0,0,.08]),-1,40);move(goal,-1,35)
                move(goal,-1 if goal[2]>obj[2]+.04 else 1,30)
            elif spec['operation']=='push':
                obj=obs['observation'][3:6].copy();goal=obs['desired_goal'].copy()
                direction=goal[:2]-obj[:2];direction/=max(np.linalg.norm(direction),1e-6)
                behind=obj-np.r_[direction*.08,0]
                move(behind+np.array([0,0,.12]),1,35);move(behind,1,35)
                for _ in range(160):
                    obj=obs['observation'][3:6].copy();delta=goal[:2]-obj[:2]
                    if np.linalg.norm(delta)<.025:break
                    aim=goal.copy();aim[2]=obj[2];move(aim,1,1)
            else:
                from collections import deque
                maze=env.unwrapped.maze;grid=maze.maze_map
                begin=tuple(maze.cell_xy_to_rowcol(obs['achieved_goal']));goalcell=tuple(maze.cell_xy_to_rowcol(obs['desired_goal']))
                queue=deque([begin]);parents={begin:None}
                while queue:
                    cell=queue.popleft()
                    if cell==goalcell:break
                    for dx,dy in [(0,1),(0,-1),(1,0),(-1,0)]:
                        nxt=(cell[0]+dx,cell[1]+dy)
                        if 0<=nxt[0]<len(grid) and 0<=nxt[1]<len(grid[0]) and grid[nxt[0]][nxt[1]]!=1 and nxt not in parents:
                            parents[nxt]=cell;queue.append(nxt)
                if goalcell not in parents:raise ContractError('Goal unreachable in declared maze')
                route=[];cell=goalcell
                while cell!=begin:route.append(cell);cell=parents[cell]
                targets=[maze.cell_rowcol_to_xy(c) for c in reversed(route)]+[obs['desired_goal'].copy()]
                for target in targets:
                    for _ in range(160):
                        error=target-obs['achieved_goal']
                        if np.linalg.norm(error)<.12:break
                        velocity=obs['observation'][2:4]
                        action=np.clip(error*10-velocity*3,-1,1)
                        obs,_,_,_,info=env.step(action);steps+=1
                        if steps>=3800:break
                    if steps>=3800:break
            error=float(np.linalg.norm(obs['achieved_goal']-obs['desired_goal']))
            success=bool(info.get('is_success',info.get('success',False)))
            return {'achieved_goal':obs['achieved_goal'].tolist(),'desired_goal':obs['desired_goal'].tolist(),'error_m':error,'steps':steps,'environment_success':success}, {
                'environment_goal':success,'finite_state':bool(np.isfinite(obs['observation']).all()),'bounded_steps':steps<=(3800 if spec['operation']=='maze' else 950)}
        finally:env.close()
    if backend=='lerobot':
        sys.path.insert(0,str(root/'src'))
        os.environ['SDL_VIDEODRIVER']='dummy'
        import torch,gymnasium as gym,gym_pusht
        from huggingface_hub import snapshot_download
        from lerobot.policies.diffusion.modeling_diffusion import DiffusionPolicy
        torch.manual_seed(seed);torch.cuda.manual_seed_all(seed);torch.set_num_threads(2)
        if not torch.cuda.is_available():raise ContractError('This validated policy environment requires CUDA')
        folder=snapshot_download(spec['policy_repo'],revision=spec['policy_revision'],allow_patterns=['config.json','model.safetensors','README.md'])
        for name,expected in spec['policy_hashes'].items():
            if hashlib.sha256((Path(folder)/name).read_bytes()).hexdigest()!=expected:raise ContractError('Policy artifact checksum changed')
        policy=DiffusionPolicy.from_pretrained(folder).to('cuda').eval();policy.reset()
        env=gym.make('gym_pusht/PushT-v0',obs_type='pixels_agent_pos',render_mode='rgb_array',max_episode_steps=300)
        try:
            obs,info=env.reset(seed=seed);maximum=0.;success=False
            for step in range(300):
                batch={'observation.image':torch.from_numpy(obs['pixels']).permute(2,0,1).float().div(255).unsqueeze(0).to('cuda'),
                       'observation.state':torch.from_numpy(obs['agent_pos']).float().unsqueeze(0).to('cuda')}
                with torch.inference_mode():action=policy.select_action(batch)[0].cpu().numpy()
                obs,reward,terminated,truncated,info=env.step(action);maximum=max(maximum,float(info['coverage']))
                success=success or bool(info.get('is_success',False)) or terminated
                if terminated or truncated:break
            return {'maximum_coverage':maximum,'steps':step+1,'environment_success':success,'cuda_inference':True}, {
                'environment_goal':success,'coverage_threshold':maximum>=.95,'cuda_inference':True}
        finally:env.close()
    raise ContractError('Unsupported pinned simulation backend')

SPEC = json.loads('{"id":"robosuite-sawyer-reach","name":"Sawyer Cartesian reaching","backend":"robosuite","operation":"reach","interface":{"version":"1","kind":"controller","abstraction_level":1,"execution_domain":"simulation","language":"python","input_transport":"json_file_or_inline","output_transport":"json_stdout","output_selector":"outputs","conventions":{"linear_unit":"m","angular_unit":"rad","time_unit":"s","coordinate_frame":"right_handed_world_xyz; +z_up","joint_order":"not_used","quaternion_order":"not_used"},"input_schema":{"type":"object","required":["seed","offset_xyz_m"],"properties":{"seed":{"type":"integer","minimum":0,"maximum":10000},"offset_xyz_m":{"type":"array","minItems":3,"maxItems":3,"items":{"type":"number","minimum":-0.15,"maximum":0.15},"x-unit":"m","x-frame":"right_handed_world_xyz; +z_up","x-order":["x","y","z"]}},"additionalProperties":false},"output_schema":{"type":"object","required":["final_xyz_m","target_xyz_m","error_m"],"properties":{"final_xyz_m":{"type":"array","minItems":3,"maxItems":3,"items":{"type":"number","minimum":-10,"maximum":10},"x-unit":"m","x-frame":"right_handed_world_xyz; +z_up","x-order":["x","y","z"]},"target_xyz_m":{"type":"array","minItems":3,"maxItems":3,"items":{"type":"number","minimum":-10,"maximum":10},"x-unit":"m","x-frame":"right_handed_world_xyz; +z_up","x-order":["x","y","z"]},"error_m":{"type":"number","minimum":0,"maximum":20,"x-unit":"m"}},"additionalProperties":false},"preconditions":["Use the exact recorded source, Linux Python 3.10 environment and pinned direct packages.","No physical robot, network actuation or external robot credentials."],"postconditions":["All reported checks must be true and all output numbers finite.","Success covers the declared goal and frozen cases, not arbitrary tasks or physical hardware."],"failure_codes":["invalid_input_or_environment","execution_failed","task_failed"],"composition":{"depends_on":[],"automatic_frame_conversion":false,"automatic_hardware_execution":false}},"example":{"seed":0,"offset_xyz_m":[0.05,0.02,0.04]},"source_hashes":{"LICENSE":"177978cbece0a4c454c2aaec5b3f145b39270814874c43109da9e829c39d9cba","robosuite/__init__.py":"366c86888aab75328eb314cc0d4f3c2a460a06cf9e81ad25a6abbbdfa7ebd0dd","robosuite/environments/manipulation/lift.py":"2d88a5e350a68d32461e08b3f24d00bdf5d269257b33f9db5da86e8aea19ce7e","robosuite/controllers/parts/arm/osc.py":"e406c0620b039156e4643fae68983a6ca19234632897b8a87bd6062b98869796"},"summary":"Sawyer Cartesian reaching. Source-pinned, bounded simulation with explicit goal checks; no physical execution.","observation_description":"Privileged simulator state and declared goals; no perception or real sensor validation.","goal_scope":"Operational-space feedback; end-effector error <0.015 m with actual motion.","robot":"Sawyer","source_commit":"824ac14cefcfb7ec125fe5eb2e0bad7364466154","packages":["robosuite==1.5.2","mujoco==3.3.7","numpy==1.26.4"]}')

if __name__ == "__main__":
    raise SystemExit(adapter_main(SPEC, mainstream_backend))
