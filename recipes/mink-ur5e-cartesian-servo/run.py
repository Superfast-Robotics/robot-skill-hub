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


"""MIT: bounded differential IK followed by dynamic actuator tracking."""
def mainstream_backend(root,data,spec):
    import importlib.metadata
    import numpy as np
    import mujoco
    # The archive is the selected code version; PyPI supplies locked dependency
    # installation metadata. Use its documented Python fallback explicitly.
    os.environ['MINK_DISABLE_NATIVE']='1'
    sys.path.insert(0,str(root/'src'))
    import mink
    for pin in spec['packages']:
        name,version=pin.split('==')
        if importlib.metadata.version(name)!=version:raise ContractError('Pinned package version differs: '+name)
    for relative in spec['runtime_guards']:
        module=__import__(relative,fromlist=['_'])
        path=Path(module.__file__)
        source=root/'src'/Path(*relative.split('.')).with_suffix('.py')
        if path.read_bytes()!=source.read_bytes():raise ContractError('Installed Mink code differs: '+relative)
    m=mujoco.MjModel.from_xml_path(str(root/spec['model_path']));d=mujoco.MjData(m)
    if m.nkey:mujoco.mj_resetDataKeyframe(m,d,m.key('home').id)
    mujoco.mj_forward(m,d);initial=d.site('attachment_site').xpos.copy();target=initial+np.asarray(data['target_offset_m'])
    q=mink.Configuration(m);q.update(d.qpos);task=mink.FrameTask(frame_name='attachment_site',frame_type='site',position_cost=1.,orientation_cost=1.,lm_damping=1e-6)
    posture=mink.PostureTask(m,cost=1e-3);posture.set_target_from_configuration(q)
    pose=mink.SE3.from_rotation_and_translation(mink.SO3.from_matrix(d.site('attachment_site').xmat.reshape(3,3)),target);task.set_target(pose)
    limits=[mink.ConfigurationLimit(m)]
    if spec['robot']=='ur5e':
        limits.append(mink.CollisionAvoidanceLimit(m,geom_pairs=[(['wrist_3_link'],['floor','wall'])]))
    for _ in range(300):
        velocity=mink.solve_ik(q,[task,posture],.005,'daqp',damping=1e-3,limits=limits);q.integrate_inplace(velocity,.005)
        if np.linalg.norm(task.compute_error(q))<1e-4:break
    desired=q.q.copy();indices=[]
    for a in range(m.nu):
        if m.actuator_trntype[a]==0 and m.actuator_biasprm[a,1]<0:
            j=int(m.actuator_trnid[a,0]);indices.append((a,int(m.jnt_qposadr[j])))
    if len(indices)<6:raise ContractError('Missing position actuators')
    for _ in range(3000):
        for a,j in indices:d.ctrl[a]=desired[j]
        mujoco.mj_step(m,d)
    mujoco.mj_forward(m,d);final=d.site('attachment_site').xpos.copy();error=float(np.linalg.norm(final-target))
    rotation=d.site('attachment_site').xmat.reshape(3,3);orientation_error=float(np.linalg.norm(mink.SO3.from_matrix(rotation).minus(pose.rotation())))
    return {'final_xyz_m':final.tolist(),'target_xyz_m':target.tolist(),'error_m':error,
            'movement_m':float(np.linalg.norm(final-initial)),'orientation_error_rad':orientation_error,'steps':3000}, {
        'cartesian_goal_reached':error<.015,'orientation_held':orientation_error<.05,'nontrivial_motion':bool(np.linalg.norm(final-initial)>.015),
        'finite_state':bool(np.isfinite(d.qpos).all() and np.isfinite(d.qvel).all())}

SPEC = json.loads('{"id":"mink-ur5e-cartesian-servo","name":"Mink ur5e differential IK and actuator servo","backend":"mink","operation":"cartesian-servo","adapter_template":"mink_servo","interface":{"version":"1","kind":"controller","abstraction_level":1,"execution_domain":"simulation","language":"python","input_transport":"json_file_or_inline","output_transport":"json_stdout","output_selector":"outputs","conventions":{"linear_unit":"m","angular_unit":"rad","time_unit":"s","coordinate_frame":"right_handed_world_xyz; +z_up","joint_order":"not_used","quaternion_order":"not_used"},"input_schema":{"type":"object","required":["target_offset_m"],"properties":{"target_offset_m":{"type":"array","minItems":3,"maxItems":3,"items":{"type":"number","minimum":-0.06,"maximum":0.06},"x-unit":"m","x-frame":"right_handed_world_xyz; +z_up"}},"additionalProperties":false},"output_schema":{"type":"object","required":["final_xyz_m","target_xyz_m","error_m","movement_m","orientation_error_rad","steps"],"properties":{"final_xyz_m":{"type":"array","minItems":3,"maxItems":3,"items":{"type":"number","minimum":-20,"maximum":20},"x-unit":"m","x-frame":"right_handed_world_xyz; +z_up"},"target_xyz_m":{"type":"array","minItems":3,"maxItems":3,"items":{"type":"number","minimum":-20,"maximum":20},"x-unit":"m","x-frame":"right_handed_world_xyz; +z_up"},"error_m":{"type":"number","minimum":0,"maximum":50,"x-unit":"m"},"movement_m":{"type":"number","minimum":0,"maximum":50,"x-unit":"m"},"orientation_error_rad":{"type":"number","minimum":0,"maximum":10,"x-unit":"rad"},"steps":{"type":"integer","minimum":1,"maximum":3000}},"additionalProperties":false},"preconditions":["Use the exact recorded source, Linux Python 3.11 environment and pinned direct packages.","No physical robot, network actuation or external robot credentials."],"postconditions":["All reported checks must be true and all output numbers finite.","Success covers the declared goal and frozen cases, not arbitrary tasks or physical hardware."],"failure_codes":["invalid_input_or_environment","execution_failed","task_failed"],"composition":{"depends_on":[],"automatic_frame_conversion":false,"automatic_hardware_execution":false}},"example":{"target_offset_m":[0.03,0,0]},"source_hashes":{"LICENSE":"c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4","pyproject.toml":"ac00d1492aa3d6504e878f6410073714d656eac3693ba3d59cf3ef4f7fbcb6a2","examples/arm_ur5e.py":"4024a9e3a11ee1a4caba82f2684e4e16dc0756bf0ac04244d81f74f9fc8b8eb8","examples/universal_robots_ur5e/scene.xml":"ea3719fdc8696af6878bc7240eb345dd89ec3e2631a70d2dba7d9e45504abd93","examples/universal_robots_ur5e/scene_plain.xml":"1d7c5b6c393e637a94df455eae85b36ce65a4fd3bdb4e710b36a88a719cd0562","examples/universal_robots_ur5e/scene_wrist_cam.xml":"e92d8ba520dae013fd6077f12f9b022c136bbe01cd30edbef1f500372d64143c","examples/universal_robots_ur5e/ur5e.xml":"b7366d561c45478d7b98efeec8c7d0df42ff9f0780de213e005d20e54cbe8b99","src/mink/configuration.py":"9dcc5690dd3e39742309280c6eb88cb2a91d46633062448d87699caebede3cb7","src/mink/tasks/frame_task.py":"7e50da2cbc5c35b91784a9ed19c573171d99b3ca0976b1c9a3070256b1bc0ab1","src/mink/tasks/posture_task.py":"ba39ac22c2e3004e3545a1f881e2cf6b27d4c80a4b3352cfa30e68dfcc9fd595","src/mink/solve_ik.py":"6812037b9f15b2a55cc6a6fe5344201f0d2c7f1fecec57f6a6a72bc3036f0ceb","src/mink/limits/configuration_limit.py":"b70517432dcdc52dc995320a8fed7f994f13093510aff89e61ada52dcc39d100"},"summary":"Mink ur5e differential IK and actuator servo. Bounded, source-pinned simulation with an explicit task contract and retained fixed-case outcomes.","observation_description":"Privileged simulator observations and goal/state feedback. No physical sensor validation.","goal_scope":"Differential IK with configuration limits, followed by 3000 MuJoCo dynamics steps using position actuators; final position error below 15 mm and orientation error below 0.05 rad. No qpos teleport after reset.","robot":"ur5e","model_path":"examples/universal_robots_ur5e/scene.xml","runtime_guards":["mink.configuration","mink.tasks.frame_task","mink.tasks.posture_task","mink.solve_ik","mink.limits.configuration_limit"],"source_commit":"ae6759602593113ed7e5431ac7c65726ea27dc29","packages":["mink==1.3.0","mujoco==3.10.0","numpy==1.26.4","qpsolvers==4.12.0","daqp==0.8.6"]}')

if __name__ == "__main__":
    raise SystemExit(adapter_main(SPEC, mainstream_backend))
