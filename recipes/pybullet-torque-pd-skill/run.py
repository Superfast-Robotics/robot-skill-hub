# Generated from tools/recipe_adapters and catalog/executable-conversions.json.
# Hub adapter: MIT. Adapted upstream example retains its original license and authors.
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


"""Headless bounded adaptations of official PyBullet examples (Hub MIT).

Uses only procedural geometry. No model downloads, asset licenses, GUI, robot
servers or hardware calls are involved. The seven-axis arm is synthetic.
"""


def pybullet_backend(root, d, spec):
    import numpy as np
    import pybullet as p
    from importlib.metadata import version
    if version('pybullet')!='3.2.7': raise ContractError('Requires the tested pybullet==3.2.7 binding')
    client=p.connect(p.DIRECT)
    if client<0: raise ContractError('DIRECT simulation unavailable')
    try:
        p.setPhysicsEngineParameter(deterministicOverlappingPairs=1,numSolverIterations=100)
        p.setTimeStep(1/240)
        def box(position,mass=1.,half=.1):
            shape=p.createCollisionShape(p.GEOM_BOX,halfExtents=[half]*3)
            return p.createMultiBody(baseMass=mass,baseCollisionShapeIndex=shape,basePosition=position)
        def arm():
            shape=p.createCollisionShape(p.GEOM_SPHERE,radius=.035)
            robot=p.createMultiBody(baseMass=0,basePosition=[0,0,0],
                linkMasses=[1.]*7,linkCollisionShapeIndices=[shape]*7,linkVisualShapeIndices=[-1]*7,
                linkPositions=[[0,0,.2]]*7,linkOrientations=[[0,0,0,1]]*7,
                linkInertialFramePositions=[[0,0,0]]*7,linkInertialFrameOrientations=[[0,0,0,1]]*7,
                linkParentIndices=list(range(7)),linkJointTypes=[p.JOINT_REVOLUTE]*7,
                linkJointAxis=[[0,0,1],[0,1,0],[0,1,0],[1,0,0],[0,1,0],[1,0,0],[0,0,1]])
            p.setJointMotorControlArray(robot,list(range(7)),p.VELOCITY_CONTROL,forces=[0.]*7)
            return robot
        op=spec['operation']
        if op in ['ik','jacobian','inverse_dynamics','position_control','torque_pd','force_torque']:
            robot=arm(); q=d['joint_angles']
            for j,v in enumerate(q): p.resetJointState(robot,j,v)
            if op=='ik':
                target=d['target_xyz']
                joints=p.calculateInverseKinematics(robot,6,target,maxNumIterations=1000,residualThreshold=1e-7)
                for j,v in enumerate(joints): p.resetJointState(robot,j,v)
                point=p.getLinkState(robot,6,computeForwardKinematics=1)[4]
                error=math.dist(point,target)
                return {'joint_angles_rad':joints,'end_effector_xyz_m':point,'position_error_m':error}, {'target_residual':error<.002}
            if op=='jacobian':
                linear,angular=p.calculateJacobian(robot,6,[0,0,0],q,[0.]*7,[0.]*7)
                finite_difference=np.zeros((3,7)); eps=1e-5
                for j in range(7):
                    p.resetJointState(robot,j,q[j]+eps); plus=np.array(p.getLinkState(robot,6,computeForwardKinematics=1)[0])
                    p.resetJointState(robot,j,q[j]-eps); minus=np.array(p.getLinkState(robot,6,computeForwardKinematics=1)[0])
                    p.resetJointState(robot,j,q[j]); finite_difference[:,j]=(plus-minus)/(2*eps)
                error=float(np.max(np.abs(np.array(linear)-finite_difference)))
                return {'linear_jacobian':linear,'angular_jacobian':angular,'finite_difference_max_error':error}, {'matches_finite_difference':error<1e-5}
            if op=='inverse_dynamics':
                p.setGravity(0,0,-9.81)
                accel=d['joint_acceleration']; gravity=np.array(p.calculateInverseDynamics(robot,q,[0.]*7,[0.]*7))
                torque=np.array(p.calculateInverseDynamics(robot,q,[0.]*7,accel)); mass=np.array(p.calculateMassMatrix(robot,q))
                residual=float(np.max(np.abs(torque-gravity-mass@np.array(accel))))
                return {'torque_nm':torque,'gravity_torque_nm':gravity,'mass_matrix':mass,'dynamics_residual_nm':residual}, {
                    'mass_matrix_symmetric':bool(np.allclose(mass,mass.T,atol=1e-9)), 'mass_matrix_positive_definite':bool(np.linalg.eigvalsh(mass).min()>0), 'inverse_dynamics_identity':residual<1e-7}
            if op=='force_torque':
                p.setGravity(0,0,-9.81); p.enableJointForceTorqueSensor(robot,3,enableSensor=1)
                p.setJointMotorControlArray(robot,list(range(7)),p.POSITION_CONTROL,targetPositions=q,forces=[200]*7)
                for _ in range(240): p.stepSimulation()
                force=p.getJointState(robot,3)[2]
                return {'reaction_force_torque':force}, {'sensor_has_six_components':len(force)==6,'finite_sensor':all(math.isfinite(v) for v in force),'load_observed':math.sqrt(sum(v*v for v in force))>1e-3}
            target=np.array(d['target_joint_angles'])
            if op=='position_control':
                p.setJointMotorControlArray(robot,list(range(7)),p.POSITION_CONTROL,targetPositions=target.tolist(),forces=[200.]*7)
                for _ in range(720): p.stepSimulation()
            else:
                for _ in range(1440):
                    state=p.getJointStates(robot,list(range(7))); positions=np.array([s[0] for s in state]); velocities=np.array([s[1] for s in state])
                    # The synthetic chain has widely different axis inertias;
                    # mass-scaled PD uses inverse dynamics for those coordinates.
                    acceleration=40*(target-positions)-12*velocities
                    tau=p.calculateInverseDynamics(robot,positions.tolist(),velocities.tolist(),acceleration.tolist())
                    p.setJointMotorControlArray(robot,list(range(7)),p.TORQUE_CONTROL,forces=tau)
                    p.stepSimulation()
            achieved=[s[0] for s in p.getJointStates(robot,list(range(7)))]; error=max(abs(a-b) for a,b in zip(achieved,target))
            return {'joint_angles_rad':achieved,'maximum_joint_error_rad':error}, {'target_joint_residual':error<.02}
        if op in ['fall','friction']:
            p.setGravity(0,0,-9.81)
            plane=p.createMultiBody(baseMass=0,baseCollisionShapeIndex=p.createCollisionShape(p.GEOM_PLANE))
            body=box([0,0,d['height']],d['mass'])
            p.changeDynamics(plane,-1,lateralFriction=d['friction'],restitution=0)
            p.changeDynamics(body,-1,lateralFriction=d['friction'],restitution=0)
            if op=='friction':
                for _ in range(240): p.stepSimulation()
                p.resetBaseVelocity(body,linearVelocity=[1.,0,0])
            for _ in range(720): p.stepSimulation()
            position=p.getBasePositionAndOrientation(body)[0]; velocity=p.getBaseVelocity(body)[0]; contacts=p.getContactPoints(body,plane)
            checks={'settled_height':abs(position[2]-.1)<.005,'floor_contact':len(contacts)>0,'bounded_penetration':all(c[8]>-.005 for c in contacts)}
            if op=='friction': checks['sliding_stopped']=math.hypot(velocity[0],velocity[1])<.02
            return {'position_xyz_m':position,'velocity_xyz_m_s':velocity,'contact_count':len(contacts)},checks
        if op=='raycast':
            body=box(d['box_center'],mass=0)
            result=p.rayTest(d['ray_from'],d['ray_to'])[0]
            point=result[3]
            return {'hit':result[0]==body,'hit_fraction':result[2],'hit_xyz_m':point,'normal_xyz':result[4]}, {
                'expected_body_hit':result[0]==body,'fraction_in_segment':0<=result[2]<=1,
                'intersection_on_box_surface':abs(max(abs(a-b) for a,b in zip(point,d['box_center']))-.1)<1e-6}
        if op=='collision_filter':
            a=box([0,0,1],mass=0); b=box([d['offset'],0,1])
            p.performCollisionDetection(); before=len(p.getContactPoints(a,b))
            p.setCollisionFilterPair(a,b,-1,-1,enableCollision=0); p.performCollisionDetection(); after=len(p.getContactPoints(a,b))
            return {'contacts_enabled':before,'contacts_disabled':after}, {'overlap_detected':before>0,'filter_removed_contacts':after==0}
        if op=='constraint':
            p.setGravity(0,0,-9.81)
            a=box([0,0,1],mass=0); b=box([0,0,1.5],mass=d['mass'])
            p.createConstraint(a,-1,b,-1,p.JOINT_FIXED,[0,0,0],[0,0,.5],[0,0,0])
            for _ in range(720): p.stepSimulation()
            position=p.getBasePositionAndOrientation(b)[0]; error=math.dist(position,[0,0,1.5])
            return {'child_xyz_m':position,'anchor_error_m':error}, {'fixed_constraint_holds':error<.005}
        if op=='save_restore':
            body=box(d['position']); state=p.saveState()
            p.resetBasePositionAndOrientation(body,[3,2,1],[0,0,0,1]); p.restoreState(stateId=state)
            position=p.getBasePositionAndOrientation(body)[0]; p.removeState(state)
            return {'restored_xyz_m':position}, {'original_state_restored':math.dist(position,d['position'])<1e-10}
        raise ContractError('Unknown reviewed simulation operation')
    finally:
        p.disconnect(client)

SPEC = json.loads('{"id":"pybullet-torque-pd-skill","name":"Computed-torque PD control in headless procedural simulation","operation":"torque_pd","source_path":"examples/pybullet/examples/pdControl.py","source_commit":"2c204c49e56ed15ec5fcfa71d199ab6d6570b3f5","source_hashes":{"LICENSE.txt":"885cd516a8420acb7c3e0b1a7119913b686495001ae564e3229740460e8cff59","examples/pybullet/examples/pdControl.py":"1506818d6b5c47ed3eb55dee4531694e2a72612646223caf2d3c7a3c378607da"},"interface":{"version":"1","kind":"controller","abstraction_level":1,"execution_domain":"simulation","language":"python","input_transport":"json_file_or_inline","output_transport":"json_stdout","conventions":{"linear_unit":"m","angular_unit":"rad","time_unit":"s","coordinate_frame":"right_handed_world_xyz; +z_up; procedural_arm_base=world_origin","joint_order":"input_array_order","quaternion_order":"not_used"},"input_schema":{"type":"object","required":["joint_angles","target_joint_angles"],"additionalProperties":false,"properties":{"joint_angles":{"type":"array","minItems":7,"maxItems":7,"items":{"type":"number","minimum":-3,"maximum":3},"x-unit":"rad","x-frame":"right_handed_world_xyz; +z_up; procedural_arm_base=world_origin","description":"joint_angles; units=rad; frame=right_handed_world_xyz; +z_up; procedural_arm_base=world_origin"},"target_joint_angles":{"type":"array","minItems":7,"maxItems":7,"items":{"type":"number","minimum":-1,"maximum":1},"x-unit":"rad","x-frame":"right_handed_world_xyz; +z_up; procedural_arm_base=world_origin","description":"target_joint_angles; units=rad; frame=right_handed_world_xyz; +z_up; procedural_arm_base=world_origin"}}},"output_schema":{"type":"object","required":["joint_angles_rad","maximum_joint_error_rad"],"additionalProperties":false,"properties":{"joint_angles_rad":{"type":"array","minItems":7,"maxItems":7,"items":{"type":"number","minimum":-100,"maximum":100},"x-unit":"rad","x-frame":"right_handed_world_xyz; +z_up; procedural_arm_base=world_origin","description":"joint_angles_rad; units=rad; frame=right_handed_world_xyz; +z_up; procedural_arm_base=world_origin"},"maximum_joint_error_rad":{"type":"number","minimum":0,"maximum":100,"x-unit":"rad","x-frame":"right_handed_world_xyz; +z_up; procedural_arm_base=world_origin","description":"maximum_joint_error_rad; units=rad; frame=right_handed_world_xyz; +z_up; procedural_arm_base=world_origin"}}},"preconditions":["PyBullet DIRECT CPU simulation with procedural shapes and a synthetic seven-axis arm where applicable; no downloaded models.","This is an adaptation of the referenced API example, not verification of its original robot model or hardware.","Simulation steps are fixed and bounded; force/torque order is Fx,Fy,Fz,Mx,My,Mz in the joint sensor frame."],"postconditions":["All declared checks must pass and all outputs must be finite.","Success applies only to this operation and model, not higher-level task completion."],"failure_codes":["invalid_input_or_environment","execution_failed","task_failed"],"composition":{"depends_on":[],"automatic_frame_conversion":false,"automatic_hardware_execution":false},"output_selector":"outputs"},"example":{"joint_angles":[0.1,-0.3,0.4,0.2,-0.2,0.1,0.1],"target_joint_angles":[0.2,-0.2,0.3,0.1,-0.1,0.2,0]}}')

if __name__ == "__main__":
    raise SystemExit(adapter_main(SPEC, pybullet_backend))
