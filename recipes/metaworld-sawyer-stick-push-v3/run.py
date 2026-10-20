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


"""MIT: bounded runner for the pinned upstream goal-observable scripted policy."""
def mainstream_backend(root,data,spec):
    import importlib.metadata
    import numpy as np
    for pin in spec['packages']:
        name,version=pin.split('==')
        if importlib.metadata.version(name)!=version:raise ContractError('Pinned package version differs: '+name)
    # Load the actual archived controllers and task implementation, not an
    # unpinned policy with the same class name from a different installation.
    sys.path.insert(0,str(root))
    import metaworld
    from metaworld.env_dict import ALL_V3_ENVIRONMENTS_GOAL_OBSERVABLE
    from importlib import import_module
    policy=getattr(import_module(spec['policy_module']),spec['policy_class'])()
    env=ALL_V3_ENVIRONMENTS_GOAL_OBSERVABLE[spec['env_id']+'-goal-observable'](seed=data['seed'])
    try:
        obs,_=env.reset(seed=data['seed']);initial=obs[:3].copy();window=[];control=0.;finite=True
        for step in range(500):
            action=np.asarray(policy.get_action(obs),dtype=np.float64)
            if action.shape!=(4,) or not np.isfinite(action).all():raise ContractError('Invalid policy action')
            action=np.clip(action,env.action_space.low,env.action_space.high);control+=float(np.linalg.norm(action))
            obs,reward,terminated,truncated,info=env.step(action)
            finite=finite and bool(np.isfinite(obs).all() and math.isfinite(float(reward)))
            window.append(bool(info.get('success',False)));window=window[-20:]
            if len(window)>=5 and all(window[-5:]):break
            if terminated or truncated:break
        metrics=[{'name':k,'value':float(v)} for k,v in sorted(info.items()) if isinstance(v,(int,float,np.number)) and np.isfinite(v)]
        complete=len(window)>=5 and all(window[-5:])
        return {'success_window':window,'native_success':bool(info.get('success',False)),
                'steps':step+1,'control_effort':control,'hand_movement_m':float(np.linalg.norm(obs[:3]-initial)),
                'native_metrics':metrics}, {'sustained_native_task_predicate':complete,'finite_state':finite,
                'nonzero_control':control>0,'physical_simulation_steps':step+1>=5}
    finally:env.close()

SPEC = json.loads('{"id":"metaworld-sawyer-stick-push-v3","name":"Meta-World Sawyer stick-push-v3 scripted controller","backend":"metaworld","operation":"scripted-policy","adapter_template":"metaworld_policy","interface":{"version":"1","kind":"task","abstraction_level":2,"execution_domain":"simulation","language":"python","input_transport":"json_file_or_inline","output_transport":"json_stdout","output_selector":"outputs","conventions":{"linear_unit":"m","angular_unit":"rad","time_unit":"s","coordinate_frame":"right_handed_world_xyz; +z_up","joint_order":"not_used","quaternion_order":"not_used"},"input_schema":{"type":"object","required":["seed"],"properties":{"seed":{"type":"integer","minimum":0,"maximum":10000}},"additionalProperties":false},"output_schema":{"type":"object","required":["success_window","native_success","steps","control_effort","hand_movement_m","native_metrics"],"properties":{"success_window":{"type":"array","minItems":1,"maxItems":20,"items":{"type":"boolean"}},"native_success":{"type":"boolean"},"steps":{"type":"integer","minimum":1,"maximum":500},"control_effort":{"type":"number","minimum":0,"maximum":10000},"hand_movement_m":{"type":"number","minimum":0,"maximum":10,"x-unit":"m"},"native_metrics":{"type":"array","minItems":0,"maxItems":32,"items":{"type":"object","required":["name","value"],"properties":{"name":{"type":"string","maxLength":80},"value":{"type":"number","minimum":-10000,"maximum":10000}},"additionalProperties":false}}},"additionalProperties":false},"preconditions":["Use the exact recorded source, Linux Python 3.11 environment and pinned direct packages.","No physical robot, network actuation or external robot credentials."],"postconditions":["All reported checks must be true and all output numbers finite.","Success covers the declared goal and frozen cases, not arbitrary tasks or physical hardware."],"failure_codes":["invalid_input_or_environment","execution_failed","task_failed"],"composition":{"depends_on":[],"automatic_frame_conversion":false,"automatic_hardware_execution":false}},"example":{"seed":0},"source_hashes":{"LICENSE":"a85291ff6ec82ee24b4218644df5d62522562e06acb8f17437513ef2136a3393","pyproject.toml":"e8e481b95d3d26e31a33dbe8690036687755eee75d2c6ac07cd6d91aa144b70e","metaworld/__init__.py":"8613586a1f5236a8c10079809d6ea94a2c2e597fcdb1fbd6241468419dba22d7","metaworld/env_dict.py":"f9e6380a04d5c5c64f4d2e595a591692ec2a92af2613bb2ddd10d1567e61edf6","metaworld/sawyer_xyz_env.py":"4282580b80befc557f67d25acffffec737ad0dae2c440601be76fc09139f351d","metaworld/policies/policy.py":"bf07b7d6511a2973c125993e7d598ab2d9705fd21588d42b5c9e449e2580c208","metaworld/policies/action.py":"0d4bf73b0505bf4e4e95e683bd0371111db7a5e25b1e255db9be9fdde606058e","metaworld/policies/sawyer_stick_push_v3_policy.py":"39da669cdd597d4ec350d9608d43e56316ac39d5c7347acafe80b86ca127bea8","metaworld/envs/sawyer_stick_push_v3.py":"043621a7e9c6cc31630e8d76d76bb7675f5c1f85527d26fbf34a985f54ac4bd2"},"summary":"Meta-World Sawyer stick-push-v3 scripted controller. Bounded, source-pinned simulation with an explicit task contract and retained fixed-case outcomes.","observation_description":"Privileged simulator observations and goal/state feedback. No physical sensor validation.","goal_scope":"Five consecutive native task-success predicates within 500 dynamic simulation steps. Task-specific success definitions come from the pinned upstream environment; this is not a general manipulation score.","env_id":"stick-push-v3","policy_module":"metaworld.policies.sawyer_stick_push_v3_policy","policy_class":"SawyerStickPushV3Policy","source_commit":"c0dafaf1557f31cad3b96ba2b62462f45638f5a5","packages":["metaworld==3.1.1","mujoco==3.3.0","numpy==1.26.4","gymnasium==1.2.0"]}')

if __name__ == "__main__":
    raise SystemExit(adapter_main(SPEC, mainstream_backend))
