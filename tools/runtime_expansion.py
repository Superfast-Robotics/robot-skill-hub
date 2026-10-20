"""Exact-byte, finite-case evidence binding for diverse simulation adapters."""
import ast,hashlib,json,math,re,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/find-robot-skills/scripts'))
from rshlib.interfaces import validate_value

def encoded(value):return json.dumps(value,sort_keys=True,separators=(',',':')).encode()
def sha(value):return hashlib.sha256(value).hexdigest()
def version_key(value):
    parts=value.split('+')[0].split('.')
    while len(parts)>1 and parts[-1]=='0':parts.pop()
    return parts

def measured_goal(recipe,outputs):
    backend=recipe['backend']
    if backend=='menagerie':
        if recipe['operation']=='quadruped_stand':return .15<outputs['base_xyz_m'][2]<.5 and outputs['minimum_base_height_m']>.15 and outputs['upright_z']>.9 and outputs['max_joint_error_rad']<.18
        return outputs['max_error_rad']<.035 and outputs['movement_rad']>=.02 and abs(max(abs(a-b) for a,b in zip(outputs['joint_positions_rad'],outputs['target_joint_positions_rad']))-outputs['max_error_rad'])<1e-6
    if backend=='robosuite':
        if recipe['operation']=='lift':return outputs['environment_success'] is True and outputs['cube_lift_m']>.07
        if recipe['operation'] in ['stack','pick_place_can']:
            error=math.dist(outputs['object_xyz_m'],outputs['target_xyz_m'])
            return outputs['environment_success'] is True and error<.08 and abs(error-outputs['error_m'])<1e-6
        error=math.dist(outputs['final_xyz_m'],outputs['target_xyz_m'])
        return error<.015 and abs(error-outputs['error_m'])<1e-6
    if backend=='gymrobotics':
        error=math.dist(outputs['achieved_goal'],outputs['desired_goal'])
        return outputs['environment_success'] is True and error<(.45 if recipe['operation']=='maze' else .05) and abs(error-outputs['error_m'])<1e-6
    if backend=='lerobot':return outputs['environment_success'] is True and outputs['cuda_inference'] is True and outputs['maximum_coverage']>=.95
    if backend=='pandagym':
        error=math.dist(outputs['achieved_goal'],outputs['desired_goal'])
        return outputs['environment_success'] is True and error<(.06 if recipe['operation']=='stack' else .04) and abs(error-outputs['error_m'])<1e-6
    if backend=='dmcontrol':
        window=outputs['reward_window']
        return (len(window)==100 and abs(sum(window)/len(window)-outputs['final_window_mean_reward'])<1e-9
            and outputs['final_reward']==window[-1] and outputs['minimum_window_reward']==min(window)
            and outputs['final_window_mean_reward']>=(.6 if recipe['domain']=='finger' else .9) and outputs['control_effort']>0)
    return False

def bound_receipt(root, recipe, source, adapter):
    path=Path(root)/'evidence/runtime/diverse-sim-v1'/(recipe['id']+'.json')
    if not path.exists():return None
    if recipe['interface']['execution_domain']!='simulation':raise ValueError('These receipts only establish simulation')
    assignments=[node for node in ast.parse(adapter.decode('utf-8')).body if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='SPEC' for t in node.targets)]
    if len(assignments)!=1:raise ValueError('Expected one literal executed specification')
    call=assignments[0].value
    if not isinstance(call,ast.Call) or len(call.args)!=1:raise ValueError('Invalid executed specification')
    executed_spec=json.loads(ast.literal_eval(call.args[0]))
    for key in ['id','backend','operation','interface','source_hashes','model_path','actuator_names','actuator_indices','robot','env_id','policy_repo','policy_revision','policy_hashes','domain','task']:
        if executed_spec.get(key)!=recipe.get(key):raise ValueError('Manifest differs from executed adapter: '+key)
    if executed_spec.get('source_commit')!=source['commit'] or executed_spec.get('packages')!=source['packages']:raise ValueError('Executed source/package specification differs')
    proof=json.loads(path.read_text(encoding='utf-8'))
    if proof.get('schema_version')!='1' or proof.get('skill_id')!=recipe['id']:raise ValueError('Receipt identity differs')
    if not re.fullmatch('[a-f0-9]{40}',proof.get('hub_commit','')):raise ValueError('Missing execution source commit')
    if proof.get('adapter_sha256')!=sha(adapter) or proof.get('source_commit')!=source['commit'] or proof.get('archive_sha256')!=source['archive_sha256']:
        raise ValueError(recipe['id']+': stale adapter or source evidence')
    if proof.get('case_plan_sha256')!=sha(encoded(recipe['cases'])) or proof.get('source_guards_sha256')!=sha(encoded(recipe['source_hashes'])):
        raise ValueError(recipe['id']+': stale input/source-guard plan')
    if proof.get('environment')!=recipe['environment'] or proof.get('hardware_execution') is not False:
        raise ValueError(recipe['id']+': wrong environment/domain')
    if proof.get('negative_unknown_field_rejected') is not True or proof.get('negative_source_drift_rejected') is not True:
        raise ValueError(recipe['id']+': missing rejection checks')
    cases=proof.get('cases',[])
    if [c.get('input') for c in cases]!=recipe['cases'] or not all(type(c.get('passed')) is bool for c in cases):
        raise ValueError(recipe['id']+': different case inventory')
    for package in source['packages']:
        name,version=package.split('==')
        if version_key(proof.get('packages',{}).get(name,''))!=version_key(version):raise ValueError(recipe['id']+': package drift')
    for case in cases:
        result=case.get('result',{})
        if result.get('outputs') is not None:validate_value(result['outputs'],recipe['interface']['output_schema'])
        if case['passed'] and (case.get('exit_code')!=0 or result.get('success') is not True or result.get('status')!='task_complete'
            or result.get('hardware_execution') is not False or result.get('source_commit')!=source['commit']
            or result.get('execution_domain')!='simulation' or not result.get('checks') or not all(v is True for v in result['checks'].values())):
            raise ValueError(recipe['id']+': unsupported success claim')
        if case['passed'] and not measured_goal(recipe,result.get('outputs',{})):raise ValueError(recipe['id']+': measured goal disagrees with reported success')
    passed=sum(c['passed'] for c in cases)
    if proof.get('passed')!=passed or proof.get('failed')!=len(cases)-passed:raise ValueError(recipe['id']+': inconsistent totals')
    return proof
