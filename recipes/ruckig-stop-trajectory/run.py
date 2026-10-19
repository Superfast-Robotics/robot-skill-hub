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


"""Parameterized local-only Ruckig Community example adaptations (MIT)."""


def ruckig_backend(root, d, spec):
    from importlib.metadata import version
    if version('ruckig')!='0.19.4': raise ContractError('Requires the tested ruckig==0.19.4 binding')
    from ruckig import InputParameter, OutputParameter, Result, Ruckig, Trajectory, ControlInterface, Synchronization
    n=len(d['current_position'])
    fields=['current_position','current_velocity','current_acceleration','target_position','target_velocity','target_acceleration','max_velocity','max_acceleration','max_jerk']
    if any(len(d[key])!=n for key in fields): raise ContractError('All axis arrays must have the same length')
    if any(v<=0 for key in ['max_velocity','max_acceleration','max_jerk'] for v in d[key]): raise ContractError('Kinematic limits must be positive')
    if any(abs(v)>lim for key,limit in [('current_velocity','max_velocity'),('target_velocity','max_velocity'),('current_acceleration','max_acceleration'),('target_acceleration','max_acceleration')] for v,lim in zip(d[key],d[limit])):
        raise ContractError('Boundary state exceeds declared limits')
    inp=InputParameter(n)
    for key in fields: setattr(inp,key,d[key])
    op=spec['operation']
    if op=='velocity': inp.control_interface=ControlInterface.Velocity
    if op=='minimum_duration': inp.minimum_duration=d['minimum_duration']
    generator=Ruckig(n,d['dt'])
    time_values=[]; positions=[]; velocities=[]; accelerations=[]
    stopped=False
    if op=='offline':
        trajectory=Trajectory(n)
        result=generator.calculate(inp,trajectory)
        if result!=Result.Working or trajectory.duration>30: raise ContractError('Trajectory calculation failed or exceeded 30 s budget')
        count=min(3000,max(2,int(math.ceil(trajectory.duration/d['dt']))+1))
        for i in range(count):
            t=trajectory.duration*i/(count-1)
            p,v,a=trajectory.at_time(t)
            time_values.append(t); positions.append(p); velocities.append(v); accelerations.append(a)
    else:
        out=OutputParameter(n)
        for tick in range(3000):
            result=generator.update(inp,out)
            if result not in (Result.Working,Result.Finished): raise ContractError('Ruckig rejected the trajectory')
            time_values.append((tick+1)*d['dt']); positions.append(list(out.new_position)); velocities.append(list(out.new_velocity)); accelerations.append(list(out.new_acceleration))
            out.pass_to_input(inp)
            if op=='stop' and not stopped and (tick+1)*d['dt']>=d['stop_time']:
                inp.control_interface=ControlInterface.Velocity; inp.synchronization=Synchronization.No
                inp.target_velocity=[0.]*n; inp.target_acceleration=[0.]*n; stopped=True
                result=Result.Working
            if result==Result.Finished: break
        else: raise ContractError('Trajectory exceeded 3000-cycle budget')
    target_velocity=[0.]*n if op=='stop' else d['target_velocity']
    target_acceleration=[0.]*n if op=='stop' else d['target_acceleration']
    checks={'terminal_velocity':max(abs(a-b) for a,b in zip(velocities[-1],target_velocity))<1e-7,
            'terminal_acceleration':max(abs(a-b) for a,b in zip(accelerations[-1],target_acceleration))<1e-7,
            'acceleration_bounds':all(abs(a)<=lim+1e-7 for sample in accelerations for a,lim in zip(sample,d['max_acceleration'])),
            'sampled_jerk_bounds':all(abs(a-b)/(t2-t1)<=lim+1e-5 for before,after,t1,t2 in zip(accelerations,accelerations[1:],time_values,time_values[1:]) for a,b,lim in zip(before,after,d['max_jerk']))}
    if op not in ['velocity','stop']:
        # Online mode reports the first control sample at/after completion. With
        # nonzero target velocity compare its analytic continuation, not zero drift.
        duration=out.trajectory.duration if op!='offline' else trajectory.duration
        extra=max(0.,time_values[-1]-duration)
        expected=[p+v*extra+.5*a*extra*extra for p,v,a in zip(d['target_position'],d['target_velocity'],d['target_acceleration'])]
        checks['terminal_position']=max(abs(a-b) for a,b in zip(positions[-1],expected))<1e-6
        checks['velocity_bounds']=all(abs(v)<=lim+1e-7 for sample in velocities for v,lim in zip(sample,d['max_velocity']))
    if op=='minimum_duration': checks['minimum_duration']=time_values[-1]+1e-8>=d['minimum_duration']
    if op=='stop': checks['stop_triggered']=stopped
    return {'time_s':time_values,'position':positions,'velocity':velocities,'acceleration':accelerations,
            'coordinate_type':d['coordinate_type'],'duration_s':time_values[-1]},checks

SPEC = json.loads('{"id":"ruckig-stop-trajectory","name":"Controlled stop jerk-limited trajectory","operation":"stop","source_path":"examples/06_stop.py","source_commit":"a8db97a4e9c55e5160a3855f739fa3b270df8e4c","source_hashes":{"LICENSE":"f0880ac5e5026c92e12c9e2859a7b338c593aaca1a435f29498bd96cbb64d7d3","examples/06_stop.py":"ae1fa70e28f1b5bf0c8f605aff627f2450903ec49f3525ec7e5e63619a28219a"},"interface":{"version":"1","kind":"trajectory_generator","abstraction_level":0,"execution_domain":"computation","language":"python","input_transport":"json_file_or_inline","output_transport":"json_stdout","conventions":{"linear_unit":"m","angular_unit":"rad","time_unit":"s","coordinate_frame":"independent_axes_in_input_array_order","joint_order":"input_array_order","quaternion_order":"not_used"},"input_schema":{"type":"object","required":["current_position","current_velocity","current_acceleration","target_position","target_velocity","target_acceleration","max_velocity","max_acceleration","max_jerk","dt","coordinate_type","stop_time"],"additionalProperties":false,"properties":{"current_position":{"type":"array","minItems":1,"maxItems":8,"items":{"type":"number","minimum":-10,"maximum":10},"x-unit":"coordinate_type:m_or_rad","x-frame":"independent_axes_in_input_array_order","description":"current_position; units=coordinate_type:m_or_rad; frame=independent_axes_in_input_array_order"},"current_velocity":{"type":"array","minItems":1,"maxItems":8,"items":{"type":"number","minimum":-10,"maximum":10},"x-unit":"coordinate_type:m/s_or_rad/s","x-frame":"independent_axes_in_input_array_order","description":"current_velocity; units=coordinate_type:m/s_or_rad/s; frame=independent_axes_in_input_array_order"},"current_acceleration":{"type":"array","minItems":1,"maxItems":8,"items":{"type":"number","minimum":-10,"maximum":10},"x-unit":"coordinate_type:m/s^2_or_rad/s^2","x-frame":"independent_axes_in_input_array_order","description":"current_acceleration; units=coordinate_type:m/s^2_or_rad/s^2; frame=independent_axes_in_input_array_order"},"target_position":{"type":"array","minItems":1,"maxItems":8,"items":{"type":"number","minimum":-10,"maximum":10},"x-unit":"coordinate_type:m_or_rad","x-frame":"independent_axes_in_input_array_order","description":"target_position; units=coordinate_type:m_or_rad; frame=independent_axes_in_input_array_order"},"target_velocity":{"type":"array","minItems":1,"maxItems":8,"items":{"type":"number","minimum":-10,"maximum":10},"x-unit":"coordinate_type:m/s_or_rad/s","x-frame":"independent_axes_in_input_array_order","description":"target_velocity; units=coordinate_type:m/s_or_rad/s; frame=independent_axes_in_input_array_order"},"target_acceleration":{"type":"array","minItems":1,"maxItems":8,"items":{"type":"number","minimum":-10,"maximum":10},"x-unit":"coordinate_type:m/s^2_or_rad/s^2","x-frame":"independent_axes_in_input_array_order","description":"target_acceleration; units=coordinate_type:m/s^2_or_rad/s^2; frame=independent_axes_in_input_array_order"},"max_velocity":{"type":"array","minItems":1,"maxItems":8,"items":{"type":"number","minimum":-10,"maximum":10},"x-unit":"coordinate_type:m/s_or_rad/s","x-frame":"independent_axes_in_input_array_order","description":"max_velocity; units=coordinate_type:m/s_or_rad/s; frame=independent_axes_in_input_array_order"},"max_acceleration":{"type":"array","minItems":1,"maxItems":8,"items":{"type":"number","minimum":-10,"maximum":10},"x-unit":"coordinate_type:m/s^2_or_rad/s^2","x-frame":"independent_axes_in_input_array_order","description":"max_acceleration; units=coordinate_type:m/s^2_or_rad/s^2; frame=independent_axes_in_input_array_order"},"max_jerk":{"type":"array","minItems":1,"maxItems":8,"items":{"type":"number","minimum":-10,"maximum":10},"x-unit":"coordinate_type:m/s^3_or_rad/s^3","x-frame":"independent_axes_in_input_array_order","description":"max_jerk; units=coordinate_type:m/s^3_or_rad/s^3; frame=independent_axes_in_input_array_order"},"dt":{"type":"number","minimum":0.01,"maximum":0.05,"x-unit":"s","x-frame":"independent_axes_in_input_array_order","description":"dt; units=s; frame=independent_axes_in_input_array_order"},"coordinate_type":{"type":"string","enum":["revolute_rad","linear_m"],"x-unit":"dimensionless","x-frame":"independent_axes_in_input_array_order","description":"coordinate_type; units=dimensionless; frame=independent_axes_in_input_array_order"},"stop_time":{"type":"number","minimum":0.1,"maximum":2,"x-unit":"s","x-frame":"independent_axes_in_input_array_order","description":"stop_time; units=s; frame=independent_axes_in_input_array_order"}}},"output_schema":{"type":"object","required":["time_s","position","velocity","acceleration","coordinate_type","duration_s"],"additionalProperties":false,"properties":{"time_s":{"type":"array","minItems":2,"maxItems":3000,"items":{"type":"number","minimum":0,"maximum":150},"x-unit":"s","x-frame":"independent_axes_in_input_array_order","description":"time_s; units=s; frame=independent_axes_in_input_array_order"},"position":{"type":"array","minItems":2,"maxItems":3000,"items":{"type":"array","minItems":1,"maxItems":8,"items":{"type":"number","minimum":-10000,"maximum":10000}},"x-unit":"coordinate_type:m_or_rad","x-frame":"independent_axes_in_input_array_order","description":"position; units=coordinate_type:m_or_rad; frame=independent_axes_in_input_array_order"},"velocity":{"type":"array","minItems":2,"maxItems":3000,"items":{"type":"array","minItems":1,"maxItems":8,"items":{"type":"number","minimum":-1000,"maximum":1000}},"x-unit":"coordinate_type:m/s_or_rad/s","x-frame":"independent_axes_in_input_array_order","description":"velocity; units=coordinate_type:m/s_or_rad/s; frame=independent_axes_in_input_array_order"},"acceleration":{"type":"array","minItems":2,"maxItems":3000,"items":{"type":"array","minItems":1,"maxItems":8,"items":{"type":"number","minimum":-1000,"maximum":1000}},"x-unit":"coordinate_type:m/s^2_or_rad/s^2","x-frame":"independent_axes_in_input_array_order","description":"acceleration; units=coordinate_type:m/s^2_or_rad/s^2; frame=independent_axes_in_input_array_order"},"coordinate_type":{"type":"string","enum":["revolute_rad","linear_m"],"x-unit":"dimensionless","x-frame":"independent_axes_in_input_array_order","description":"coordinate_type; units=dimensionless; frame=independent_axes_in_input_array_order"},"duration_s":{"type":"number","minimum":0,"maximum":150,"x-unit":"s","x-frame":"independent_axes_in_input_array_order","description":"duration_s; units=s; frame=independent_axes_in_input_array_order"}}},"preconditions":["Ruckig Community 0.19.4; no cloud client, IK, collision or physical control.","All axes share coordinate_type; m or rad and corresponding derivatives per second.","Velocity/stop modes do not guarantee target position. Maximum 3000 online cycles or 30 s offline trajectory."],"postconditions":["All declared checks must pass and all outputs must be finite.","Success applies only to this operation and model, not higher-level task completion."],"failure_codes":["invalid_input_or_environment","execution_failed","task_failed"],"composition":{"depends_on":[],"automatic_frame_conversion":false,"automatic_hardware_execution":false},"output_selector":"outputs"},"example":{"current_position":[0,0,0.5],"current_velocity":[0.3,-0.2,0.1],"current_acceleration":[0,0,0],"target_position":[1,-0.5,0.25],"target_velocity":[0,0,0],"target_acceleration":[0,0,0],"max_velocity":[1,1,1],"max_acceleration":[2,2,2],"max_jerk":[4,4,4],"dt":0.01,"coordinate_type":"revolute_rad","stop_time":0.5}}')

if __name__ == "__main__":
    raise SystemExit(adapter_main(SPEC, ruckig_backend))
