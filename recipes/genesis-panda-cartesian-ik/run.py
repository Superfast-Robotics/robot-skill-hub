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


"""MIT: Genesis Panda PD control and IK-to-dynamic-servo adaptation."""
def mainstream_backend(root,data,spec):
    import importlib.metadata
    import numpy as np
    import torch
    sys.path.insert(0,str(root))
    import genesis as gs
    for pin in spec['packages']:
        name,version=pin.split('==')
        installed=importlib.metadata.version(name).split('+')[0]
        if installed!=version:raise ContractError('Pinned package version differs: '+name)
    for relative in ['genesis/__init__.py','genesis/engine/entities/rigid_entity/rigid_entity.py']:
        installed=Path(gs.__file__).parent/Path(relative).relative_to('genesis')
        if installed.read_bytes()!=(root/relative).read_bytes():raise ContractError('Installed Genesis code differs: '+relative)
    gs.init(backend=gs.gpu,precision='32',logging_level='error',seed=data['seed'])
    scene=gs.Scene(sim_options=gs.options.SimOptions(dt=.01),show_viewer=False)
    scene.add_entity(gs.morphs.Plane())
    model=root/'genesis/assets/xml/franka_emika_panda/panda.xml'
    robot=scene.add_entity(gs.morphs.MJCF(file=str(model)));scene.build()
    joints=['joint'+str(i) for i in range(1,8)]+['finger_joint1','finger_joint2']
    indices=[robot.get_joint(name).dofs_idx_local[0] for name in joints]
    robot.set_dofs_kp(np.array([4500,4500,3500,3500,2000,2000,2000,100,100]),indices)
    robot.set_dofs_kv(np.array([450,450,350,350,200,200,200,10,10]),indices)
    robot.set_dofs_force_range(np.array([-87,-87,-87,-87,-12,-12,-12,-100,-100]),np.array([87,87,87,87,12,12,12,100,100]),indices)
    home=np.array([0,-.5,0,-1.8,0,1.4,.6,.04,.04]);robot.set_dofs_position(home,indices)
    robot.control_dofs_position(home,indices)
    for _ in range(100):scene.step()
    def cpu(value):return value.detach().cpu().numpy()
    initial=cpu(robot.get_link('hand').get_pos()).copy()
    if spec['operation']=='cartesian_ik':
        target=initial+np.asarray(data['target_offset_m'])
        desired=cpu(robot.inverse_kinematics(link=robot.get_link('hand'),pos=target))
    else:
        desired=cpu(robot.get_dofs_position()).copy();desired[indices[0]]+=data['joint_offset_rad'];target=None
    robot.control_dofs_position(desired)
    for _ in range(700):scene.step()
    final=cpu(robot.get_link('hand').get_pos());actual=cpu(robot.get_dofs_position());joint_error=float(np.max(np.abs(actual-desired)))
    if target is None:target=final.copy()
    error=float(np.linalg.norm(final-target));movement=float(np.linalg.norm(final-initial));gpu=bool(torch.cuda.is_available() and robot.get_dofs_position().is_cuda)
    return {'final_xyz_m':final.tolist(),'target_xyz_m':target.tolist(),'error_m':error,'movement_m':movement,
            'max_joint_error_rad':joint_error,'cuda_simulation':gpu,'steps':800}, {
        'cartesian_goal_reached':error<.015,'joint_goal_reached':joint_error<.04,'nontrivial_motion':movement>.015,
        'finite_state':bool(np.isfinite(actual).all()),'cuda_simulation':gpu}

SPEC = json.loads('{"id":"genesis-panda-cartesian-ik","name":"Genesis Panda cartesian ik","backend":"genesis","operation":"cartesian_ik","adapter_template":"genesis_servo","interface":{"version":"1","kind":"controller","abstraction_level":1,"execution_domain":"simulation","language":"python","input_transport":"json_file_or_inline","output_transport":"json_stdout","output_selector":"outputs","conventions":{"linear_unit":"m","angular_unit":"rad","time_unit":"s","coordinate_frame":"right_handed_world_xyz; +z_up","joint_order":"not_used","quaternion_order":"not_used"},"input_schema":{"type":"object","required":["seed","target_offset_m"],"properties":{"seed":{"type":"integer","minimum":0,"maximum":10000},"target_offset_m":{"type":"array","minItems":3,"maxItems":3,"items":{"type":"number","minimum":-0.06,"maximum":0.06},"x-unit":"m","x-frame":"right_handed_world_xyz; +z_up"}},"additionalProperties":false},"output_schema":{"type":"object","required":["final_xyz_m","target_xyz_m","error_m","movement_m","max_joint_error_rad","cuda_simulation","steps"],"properties":{"final_xyz_m":{"type":"array","minItems":3,"maxItems":3,"items":{"type":"number","minimum":-20,"maximum":20},"x-unit":"m","x-frame":"right_handed_world_xyz; +z_up"},"target_xyz_m":{"type":"array","minItems":3,"maxItems":3,"items":{"type":"number","minimum":-20,"maximum":20},"x-unit":"m","x-frame":"right_handed_world_xyz; +z_up"},"error_m":{"type":"number","minimum":0,"maximum":50,"x-unit":"m"},"movement_m":{"type":"number","minimum":0,"maximum":50,"x-unit":"m"},"max_joint_error_rad":{"type":"number","minimum":0,"maximum":50,"x-unit":"rad"},"cuda_simulation":{"type":"boolean"},"steps":{"type":"integer","minimum":1,"maximum":1000}},"additionalProperties":false},"preconditions":["Use the exact recorded source, Linux Python 3.11 environment and pinned direct packages.","No physical robot, network actuation or external robot credentials."],"postconditions":["All reported checks must be true and all output numbers finite.","Success covers the declared goal and frozen cases, not arbitrary tasks or physical hardware."],"failure_codes":["invalid_input_or_environment","execution_failed","task_failed"],"composition":{"depends_on":[],"automatic_frame_conversion":false,"automatic_hardware_execution":false}},"example":{"seed":0,"target_offset_m":[0.03,0,0]},"source_hashes":{"LICENSE":"43070e2d4e532684de521b885f385d0841030efa2b1a20bafb76133a5e1379c1","pyproject.toml":"9bfad1a08ba311c27a5c755bee1c4a5d9c4b363dbc3134a96c2f82f9a4f03db6","examples/rigid/ik_franka.py":"aef185ae08966badb82858384377c5b88e4ca76af45f129004b0a046a7f9c541","genesis/__init__.py":"c54d4997ad438981108c42c59d8fbd2036ca52107c4120c9b471cecae118633c","genesis/engine/entities/rigid_entity/rigid_entity.py":"62898c01e530fb8de1f8c90e7bc4607d2280c1c52202b579aeb3ef17addbc017","genesis/assets/xml/franka_emika_panda/panda.xml":"e502e07fcef6219024be02dfb9cd65d5c194b4767adf381ca51f10172ff8a32d"},"summary":"Genesis Panda cartesian ik. Bounded, source-pinned simulation with an explicit task contract and retained fixed-case outcomes.","observation_description":"Privileged simulator observations and goal/state feedback. No physical sensor validation.","goal_scope":"CUDA dynamic simulation after reset. PD tracking below 0.04 rad and nontrivial hand motion; IK variant also requires final hand position error below 15 mm. Source example kinematic visualization is adapted to real simulation stepping.","timeout_seconds":600,"source_commit":"a5c4e9a73aca221fa26e611281f2696c5f8b0ca8","packages":["genesis-world==1.4.4","torch==2.8.0","numpy==1.26.4"]}')

if __name__ == "__main__":
    raise SystemExit(adapter_main(SPEC, mainstream_backend))
