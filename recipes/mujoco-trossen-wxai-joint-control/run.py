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


"""MIT: position-servo feedback compensates static load without changing the goal."""
def mainstream_backend(root,data,spec):
    import importlib.metadata
    import numpy as np
    import mujoco
    for pin in spec['packages']:
        name,version=pin.split('==')
        if importlib.metadata.version(name)!=version:raise ContractError('Pinned package version differs: '+name)
    m=mujoco.MjModel.from_xml_path(str(root/spec['model_path']));d=mujoco.MjData(m)
    if m.nkey:mujoco.mj_resetDataKeyframe(m,d,0)
    mujoco.mj_forward(m,d);indices=[]
    for name in spec['interface']['output_schema']['properties']['joint_positions_rad']['x-order']:
        joint=m.joint(name).id
        candidates=[a for a in range(m.nu) if m.actuator_trntype[a]==0 and m.actuator_trnid[a,0]==joint and m.actuator_biasprm[a,1]<0]
        if len(candidates)!=1:raise ContractError('Expected one position actuator per joint')
        indices.append(candidates[0])
    joints=[int(m.actuator_trnid[a,0]) for a in indices];qaddrs=[int(m.jnt_qposadr[j]) for j in joints]
    for a,q in zip(indices,qaddrs):d.ctrl[a]=d.qpos[q]
    for _ in range(500):mujoco.mj_step(m,d)
    initial=d.qpos[qaddrs].copy();target=initial+data['joint_offset_rad'];integral=np.zeros(len(joints))
    for k,(a,j) in enumerate(zip(indices,joints)):
        if m.jnt_limited[j]:target[k]=np.clip(target[k],m.jnt_range[j,0]+.02,m.jnt_range[j,1]-.02)
        if m.actuator_ctrllimited[a]:target[k]=np.clip(target[k],*m.actuator_ctrlrange[a])
    for _ in range(4000):
        integral=np.clip(integral+3*m.opt.timestep*(target-d.qpos[qaddrs]),-.4,.4)
        for k,a in enumerate(indices):
            command=target[k]+integral[k]
            d.ctrl[a]=np.clip(command,*m.actuator_ctrlrange[a]) if m.actuator_ctrllimited[a] else command
        mujoco.mj_step(m,d)
    final=d.qpos[qaddrs];error=float(np.max(np.abs(final-target)));motion=float(np.max(np.abs(final-initial)))
    return {'joint_positions_rad':final.tolist(),'target_joint_positions_rad':target.tolist(),'max_error_rad':error,'movement_rad':motion},{
        'nontrivial_target':bool(np.max(np.abs(target-initial))>=.03),'joint_goal_reached':error<.035,'actual_motion':motion>=.02,
        'finite_state':bool(np.isfinite(d.qpos).all() and np.isfinite(d.qvel).all())}

SPEC = json.loads('{"id":"mujoco-trossen-wxai-joint-control","name":"trossen wxai joint-position control","backend":"menagerie","operation":"joint_control","interface":{"version":"1","kind":"controller","abstraction_level":1,"execution_domain":"simulation","language":"python","input_transport":"json_file_or_inline","output_transport":"json_stdout","output_selector":"outputs","conventions":{"linear_unit":"m","angular_unit":"rad","time_unit":"s","coordinate_frame":"right_handed_world_xyz; +z_up","joint_order":"left/joint_0,left/joint_1,left/joint_2,left/joint_3,left/joint_4,left/joint_5,right/joint_0,right/joint_1,right/joint_2,right/joint_3,right/joint_4,right/joint_5","quaternion_order":"not_used"},"input_schema":{"type":"object","required":["seed","joint_offset_rad"],"properties":{"seed":{"type":"integer","minimum":0,"maximum":10000},"joint_offset_rad":{"type":"number","minimum":-0.15,"maximum":0.15,"x-unit":"rad"}},"additionalProperties":false},"output_schema":{"type":"object","required":["joint_positions_rad","target_joint_positions_rad","max_error_rad","movement_rad"],"properties":{"joint_positions_rad":{"type":"array","minItems":12,"maxItems":12,"items":{"type":"number","minimum":-20,"maximum":20},"x-unit":"rad","x-frame":"named_model_joint_coordinates","x-order":["left/joint_0","left/joint_1","left/joint_2","left/joint_3","left/joint_4","left/joint_5","right/joint_0","right/joint_1","right/joint_2","right/joint_3","right/joint_4","right/joint_5"]},"target_joint_positions_rad":{"type":"array","minItems":12,"maxItems":12,"items":{"type":"number","minimum":-20,"maximum":20},"x-unit":"rad","x-frame":"named_model_joint_coordinates","x-order":["left/joint_0","left/joint_1","left/joint_2","left/joint_3","left/joint_4","left/joint_5","right/joint_0","right/joint_1","right/joint_2","right/joint_3","right/joint_4","right/joint_5"]},"max_error_rad":{"type":"number","minimum":0,"maximum":50,"x-unit":"rad"},"movement_rad":{"type":"number","minimum":0,"maximum":50,"x-unit":"rad"}},"additionalProperties":false},"preconditions":["Use the exact recorded source, Linux Python 3.10 environment and pinned direct packages.","No physical robot, network actuation or external robot credentials."],"postconditions":["All reported checks must be true and all output numbers finite.","Success covers the declared goal and frozen cases, not arbitrary tasks or physical hardware."],"failure_codes":["invalid_input_or_environment","execution_failed","task_failed"],"composition":{"depends_on":[],"automatic_frame_conversion":false,"automatic_hardware_execution":false}},"example":{"seed":0,"joint_offset_rad":0.08},"source_hashes":{"trossen_wxai/LICENSE":"110a998ebd9a901d31173892d43224f8f59f12ebfd6398b9f3dea0ee9a01ab16","trossen_wxai/scene.xml":"90c315c4ec91076bbe6922c92993bcdc6efe49d9d18857671516b0cf3ad9c015","trossen_wxai/wxai_follower.xml":"a6431f2b6b9af1a5bea0d49eb92e805ad4fae12480de9935105838944ad94a1a","trossen_wxai/wxai_follower_biarm.xml":"e091ebbab95f07fe156fb2545175194e9b4b05efa31747f24c87d2636b773b36"},"summary":"trossen wxai joint-position control. Bounded simulated joint offsets from the original reset pose; not locomotion or object-task validation.","observation_description":"Privileged simulator state and declared goals; no perception or real sensor validation.","goal_scope":"Move the named actuated hinge joints by a bounded offset from the reset/settled pose; max residual <0.035 rad and nonzero actual motion. This is not end-effector planning, balance, locomotion or hardware control.","model_path":"trossen_wxai/scene.xml","actuator_names":["left/joint_0","left/joint_1","left/joint_2","left/joint_3","left/joint_4","left/joint_5","right/joint_0","right/joint_1","right/joint_2","right/joint_3","right/joint_4","right/joint_5"],"adapter_template":"joint_feedback","source_commit":"62ab00f2bc44f6f20c1c9b7a13f3fb1dd41a4e35","packages":["mujoco==3.3.7","numpy==1.26.4"]}')

if __name__ == "__main__":
    raise SystemExit(adapter_main(SPEC, mainstream_backend))
