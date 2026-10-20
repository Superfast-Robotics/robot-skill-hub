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


"""MIT: contact stacking with native IK and explicit two-object geometry checks."""
def stack_backend(root,data,spec):
    import importlib.metadata
    import numpy as np
    for pin in spec['packages']:
        name,version=pin.split('==')
        if importlib.metadata.version(name)!=version:raise ContractError('Pinned package version differs: '+name)
    sys.path.insert(0,str(root))
    import gymnasium as gym,panda_gym
    env=gym.make(spec['env_id'],render_mode='rgb_array',max_episode_steps=1500)
    try:
        obs,info=env.reset(seed=data['seed']);steps=0;sim=env.unwrapped.sim
        def move(target,grip,limit):
            nonlocal obs,info,steps
            for _ in range(limit):
                a=np.r_[np.clip((target-obs['observation'][:3])*10,-.6,.6),grip]
                obs,_,_,_,info=env.step(a);steps+=1
        def carry(body,target,limit):
            for _ in range(limit):
                actual=np.asarray(sim.get_base_position(body))
                move(obs['observation'][:3]+target-actual,-1,1)
        def transfer(body,target):
            obj=np.asarray(sim.get_base_position(body)).copy()
            move(obj+np.array([0,0,.13]),1,40);move(obj+np.array([0,0,.003]),1,40)
            move(obj+np.array([0,0,.003]),-1,30);carry(body,obj+np.array([0,0,.18]),45)
            carry(body,target+np.array([0,0,.15]),50);carry(body,target,60)
            released=obs['observation'][:3].copy();move(released,1,30)
            move(released+np.array([0,0,.15]),1,40)
        goal=obs['desired_goal'].copy();transfer('object1',goal[:3])
        # Stack on the measured lower cube, rather than assuming a perfect first placement.
        lower=np.asarray(sim.get_base_position('object1')).copy()
        transfer('object2',lower+np.array([0,0,.041]))
        achieved=obs['achieved_goal'];error=float(np.linalg.norm(achieved-goal))
        height=float(achieved[5]-achieved[2]);alignment=float(np.linalg.norm(achieved[:2]-achieved[3:5]))
        success=bool(info['is_success'])
        return {'achieved_goal':achieved.tolist(),'desired_goal':goal.tolist(),'error_m':error,'steps':steps,'environment_success':success,
                'stack_height_m':height,'stack_alignment_m':alignment},{
            'native_environment_goal':success,'strict_goal_error':error<.04,'upper_cube_above_lower':.03<height<.05,
            'horizontal_support_alignment':alignment<.015,'finite_state':bool(np.isfinite(obs['observation']).all())}
    finally:env.close()

def mainstream_backend(root,data,spec):
    import ctypes
    saved=os.dup(1)
    try:
        os.dup2(2,1);return stack_backend(root,data,spec)
    finally:
        ctypes.CDLL(None).fflush(None);os.dup2(saved,1);os.close(saved)

SPEC = json.loads('{"id":"pandagym-panda-stack","name":"Panda Gym Stack closed-loop starting policy","backend":"pandagym","operation":"stack","interface":{"version":"1","kind":"task","abstraction_level":2,"execution_domain":"simulation","language":"python","input_transport":"json_file_or_inline","output_transport":"json_stdout","output_selector":"outputs","conventions":{"linear_unit":"m","angular_unit":"rad","time_unit":"s","coordinate_frame":"right_handed_world_xyz; +z_up","joint_order":"not_used","quaternion_order":"not_used"},"input_schema":{"type":"object","required":["seed"],"properties":{"seed":{"type":"integer","minimum":0,"maximum":10000}},"additionalProperties":false},"output_schema":{"type":"object","required":["achieved_goal","desired_goal","error_m","steps","environment_success","stack_height_m","stack_alignment_m"],"properties":{"achieved_goal":{"type":"array","minItems":6,"maxItems":6,"items":{"type":"number","minimum":-30,"maximum":30},"x-unit":"m","x-frame":"right_handed_world_xyz; +z_up"},"desired_goal":{"type":"array","minItems":6,"maxItems":6,"items":{"type":"number","minimum":-30,"maximum":30},"x-unit":"m","x-frame":"right_handed_world_xyz; +z_up"},"error_m":{"type":"number","minimum":0,"maximum":50},"steps":{"type":"integer","minimum":1,"maximum":1500},"environment_success":{"type":"boolean"},"stack_height_m":{"type":"number","minimum":-5,"maximum":5,"x-unit":"m"},"stack_alignment_m":{"type":"number","minimum":0,"maximum":50,"x-unit":"m"}},"additionalProperties":false},"preconditions":["Use the exact recorded source, Linux Python 3.10 environment and pinned direct packages.","No physical robot, network actuation or external robot credentials."],"postconditions":["All reported checks must be true and all output numbers finite.","Success covers the declared goal and frozen cases, not arbitrary tasks or physical hardware."],"failure_codes":["invalid_input_or_environment","execution_failed","task_failed"],"composition":{"depends_on":[],"automatic_frame_conversion":false,"automatic_hardware_execution":false}},"example":{"seed":0},"source_hashes":{"README.md":"3d125f16b96d40e745deed1197bac861e576d68f42c8b7794b1cf656920411a9","setup.py":"959f21cee326dacfb8ad52a5e19e416496f0f270d53587a2ac6c722986b9f164","LICENSE":"6d6fb3fbccaa0000bb00c69b94a4393adcafcfe00717c1f2c7a38bdbad4e00c5","panda_gym/pybullet.py":"af07722bd0ced414c85de4e29ecae36823ef0a6842a3c4157530e9529a0b3b37","panda_gym/utils.py":"ce5c4d4579e3f17c726bdd7f68950adcd9c51cf483757cc81129de49d4fed570","panda_gym/__init__.py":"4f8da02b1c77b077601cca57f52155e47df9219aefab4279c5216f514181e63d","panda_gym/envs/panda_tasks.py":"a6f957c0ab0c396881cb6db11b4d55ea73e4821d45e69b2c50841a5aadcca37b","panda_gym/envs/core.py":"36b1d73344584f0b705952510de75dbe0255035061ef34bef1f907697c0e8fba","panda_gym/envs/__init__.py":"23fc4234af8c7baaead0586a675fb515953ebbc34fb1a79d024ed3f1b839c093","panda_gym/envs/tasks/stack.py":"ca80b5b981b658a29c56593c45fc7212cecaa6ae8683de00079cc78b5c9cfbc8","panda_gym/envs/tasks/flip.py":"9d405205134ba72b0e5ab1d6795016788af3ad99d07873bc8a78c47a440d221a","panda_gym/envs/tasks/slide.py":"587b72f1ab7716b759dc25456eef51b3d444d58125f4d0f50f3e6155a547377e","panda_gym/envs/tasks/push.py":"6e15494b78d93b127ac1c0e5e54ddf24deb7221cddce1f8e29e9a19c50fef8a8","panda_gym/envs/tasks/pick_and_place.py":"2e94a75c2b0ea0e6d59aaf124bf8526b3a886a2d07f44fafe9828b0dd792585d","panda_gym/envs/tasks/reach.py":"dd4907bc88f8e9fbc2b79d07291ae7d50c86eb5264d8c11ad6ee25607adbf9a7","panda_gym/envs/tasks/__init__.py":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855","panda_gym/envs/robots/panda.py":"f01efa5236849cb944a9f69ce525c843518d4edd4d00be35570dd730bfc377dd","panda_gym/envs/robots/__init__.py":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855","panda_gym/assets/__init__.py":"910ce1095335ad8321d7e3f6b44e5551ff3645ff9cb1db5f0a7fb4baeddd27ac"},"summary":"Panda Gym Stack closed-loop starting policy. Native IK actions, privileged simulator observations and a frozen three-seed evaluation; no state teleportation after reset.","observation_description":"Privileged simulator state and declared goals; no perception or real sensor validation.","goal_scope":"Native success AND final six-dimensional goal error <.04 m AND upper/lower cube height difference between .03 and .05 m AND horizontal center separation <.015 m after release and retreat. A flat pair of cubes cannot pass.","env_id":"PandaStack-v3","adapter_template":"panda_stack","source_commit":"14d944120037a5bb637e629965f88bb9e13dba3b","packages":["panda-gym==3.0.7","pybullet==3.2.7","gymnasium==1.2.0","numpy==1.26.4"]}')

if __name__ == "__main__":
    raise SystemExit(adapter_main(SPEC, mainstream_backend))
