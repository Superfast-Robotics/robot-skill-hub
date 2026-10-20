"""Exact-byte, finite-case evidence binding for diverse simulation adapters."""
import hashlib,json
from pathlib import Path

def encoded(value):return json.dumps(value,sort_keys=True,separators=(',',':')).encode()
def sha(value):return hashlib.sha256(value).hexdigest()

def bound_receipt(root, recipe, source, adapter):
    path=Path(root)/'evidence/runtime/diverse-sim-v1'/(recipe['id']+'.json')
    if not path.exists():return None
    proof=json.loads(path.read_text(encoding='utf-8'))
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
        if proof.get('packages',{}).get(name,'').split('+')[0]!=version:raise ValueError(recipe['id']+': package drift')
    for case in cases:
        result=case.get('result',{})
        if case['passed'] and (case.get('exit_code')!=0 or result.get('success') is not True or result.get('status')!='task_complete'
            or result.get('hardware_execution') is not False or result.get('source_commit')!=source['commit']
            or result.get('execution_domain')!='simulation' or not result.get('checks') or not all(v is True for v in result['checks'].values())):
            raise ValueError(recipe['id']+': unsupported success claim')
    passed=sum(c['passed'] for c in cases)
    if proof.get('passed')!=passed or proof.get('failed')!=len(cases)-passed:raise ValueError(recipe['id']+': inconsistent totals')
    return proof
