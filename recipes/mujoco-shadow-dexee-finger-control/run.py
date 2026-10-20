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


"""MIT: native Shadow DexEE PID setpoints and torque-limited Go2 standing."""
def mainstream_backend(root,data,spec):
    import importlib.metadata
    import numpy as np
    os.environ.setdefault('MUJOCO_GL','egl')
    for pin in spec['packages']:
        name,expected=pin.split('==');actual=importlib.metadata.version(name).split('+')[0]
        if actual!=expected:raise ContractError('Pinned package version differs: '+name)
    import mujoco
    m=mujoco.MjModel.from_xml_path(str(root/spec['model_path']));d=mujoco.MjData(m)
    if m.nkey:mujoco.mj_resetDataKeyframe(m,d,0)
    mujoco.mj_forward(m,d)
    indices=spec['actuator_indices'];joints=[int(m.actuator_trnid[a,0]) for a in indices]
    qaddrs=[int(m.jnt_qposadr[j]) for j in joints];vaddrs=[int(m.jnt_dofadr[j]) for j in joints]
    if spec['operation']=='quadruped_stand':
        target=d.qpos[qaddrs].copy();d.qvel[0]=data['push_velocity_m_s']
        body=int(m.jnt_bodyid[0]);minimum_height=10.
        for step in range(3500):
            torque=90*(target-d.qpos[qaddrs])-3*d.qvel[vaddrs]
            for k,a in enumerate(indices):d.ctrl[a]=np.clip(torque[k],*m.actuator_ctrlrange[a])
            mujoco.mj_step(m,d)
            if step>500:minimum_height=min(minimum_height,float(d.xpos[body,2]))
        error=float(np.max(np.abs(target-d.qpos[qaddrs])));up=float(d.xmat[body,8])
        xyz=d.xpos[body].tolist()
        return {'base_xyz_m':xyz,'minimum_base_height_m':minimum_height,'upright_z':up,'max_joint_error_rad':error}, {
            'standing_height':.15<xyz[2]<.5 and minimum_height>.15,'upright':up>.9,'joint_tracking':error<.18,
            'finite_state':bool(np.isfinite(d.qpos).all())}
    for a,q in zip(indices,qaddrs):d.ctrl[a]=d.qpos[q]
    for _ in range(500):mujoco.mj_step(m,d)
    start=d.qpos[qaddrs].copy();target=start+data['joint_offset_rad']
    for k,(a,j) in enumerate(zip(indices,joints)):
        target[k]=np.clip(target[k],m.jnt_range[j,0]+.02,m.jnt_range[j,1]-.02)
        target[k]=np.clip(target[k],*m.actuator_ctrlrange[a]);d.ctrl[a]=target[k]
    for _ in range(2500):mujoco.mj_step(m,d)
    final=d.qpos[qaddrs];error=float(np.max(np.abs(final-target)));moved=float(np.max(np.abs(final-start)))
    return {'joint_positions_rad':final.tolist(),'target_joint_positions_rad':target.tolist(),'max_error_rad':error,'movement_rad':moved}, {
        'nontrivial_target':bool(np.max(np.abs(target-start))>=.03),'joint_goal_reached':error<.035,'actual_motion':moved>=.02,
        'finite_state':bool(np.isfinite(d.qpos).all())}

SPEC = json.loads('{"id":"mujoco-shadow-dexee-finger-control","name":"Shadow DexEE distal-finger curl control","backend":"menagerie","operation":"joint_control","interface":{"version":"1","kind":"controller","abstraction_level":1,"execution_domain":"simulation","language":"python","input_transport":"json_file_or_inline","output_transport":"json_stdout","output_selector":"outputs","conventions":{"linear_unit":"m","angular_unit":"rad","time_unit":"s","coordinate_frame":"right_handed_world_xyz; +z_up","joint_order":"F0/J2,F0/J3,F1/J2,F1/J3,F2/J2,F2/J3","quaternion_order":"not_used"},"input_schema":{"type":"object","required":["seed","joint_offset_rad"],"properties":{"seed":{"type":"integer","minimum":0,"maximum":10000},"joint_offset_rad":{"type":"number","minimum":-0.15,"maximum":0.15,"x-unit":"rad"}},"additionalProperties":false},"output_schema":{"type":"object","required":["joint_positions_rad","target_joint_positions_rad","max_error_rad","movement_rad"],"properties":{"joint_positions_rad":{"type":"array","minItems":6,"maxItems":6,"items":{"type":"number","minimum":-20,"maximum":20},"x-unit":"rad","x-frame":"named_model_joint_coordinates","x-order":["F0/J2","F0/J3","F1/J2","F1/J3","F2/J2","F2/J3"]},"target_joint_positions_rad":{"type":"array","minItems":6,"maxItems":6,"items":{"type":"number","minimum":-20,"maximum":20},"x-unit":"rad","x-frame":"named_model_joint_coordinates","x-order":["F0/J2","F0/J3","F1/J2","F1/J3","F2/J2","F2/J3"]},"max_error_rad":{"type":"number","minimum":0,"maximum":50,"x-unit":"rad"},"movement_rad":{"type":"number","minimum":0,"maximum":50,"x-unit":"rad"}},"additionalProperties":false},"preconditions":["Use the exact recorded source, Linux Python 3.10 environment and pinned direct packages.","No physical robot, network actuation or external robot credentials."],"postconditions":["All reported checks must be true and all output numbers finite.","Success covers the declared goal and frozen cases, not arbitrary tasks or physical hardware."],"failure_codes":["invalid_input_or_environment","execution_failed","task_failed"],"composition":{"depends_on":[],"automatic_frame_conversion":false,"automatic_hardware_execution":false}},"example":{"seed":0,"joint_offset_rad":0.08},"source_hashes":{"shadow_dexee/shadow_dexee.xml":"7d7ad518b01451f58d3e5f3e59e58719741efead2d7730c9cf800f7d766f267a","shadow_dexee/LICENSE":"d42cae9a0f292b7a713597ba26e1e1e23d50df906c488f0d36fd3538af200bc1","shadow_dexee/scene.xml":"72abc14afb7aab117941947ffe8befe1daffdfd22ad6b23eb02faab3f20bbd9e"},"summary":"Control six named distal finger joints through the original MuJoCo PID plugin; no object-grasp or hardware claim.","observation_description":"Privileged simulator state and declared goals; no perception or real sensor validation.","goal_scope":"Control the six J2/J3 distal finger joints through the original PID plugin. Other hand joints retain their native reset controls. This is finger curl, not all-joint hand posture or object grasping.","model_path":"shadow_dexee/scene.xml","adapter_template":"mujoco_extra","actuator_indices":[2,3,6,7,10,11],"source_commit":"62ab00f2bc44f6f20c1c9b7a13f3fb1dd41a4e35","packages":["mujoco==3.3.7","numpy==1.26.4"]}')

if __name__ == "__main__":
    raise SystemExit(adapter_main(SPEC, mainstream_backend))
