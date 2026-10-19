"""Generate the finite reviewed conversion cohort; no downloads or execution.

The source manifest and templates are the editable inputs. Runtime evidence is
accepted only when its adapter, source and case-plan hashes still match.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
MANIFEST=ROOT/'catalog/executable-conversions.json'
EVIDENCE=ROOT/'evidence/runtime/executable-conversions-v1'


def digest(raw): return hashlib.sha256(raw).hexdigest()
def encoded(value): return json.dumps(value,sort_keys=True,separators=(',',':')).encode()
def write(path,body,check):
    raw=body.encode('utf-8')
    if check:
        if not path.is_file() or path.read_bytes()!=raw: raise ValueError('Generated file differs: '+str(path.relative_to(ROOT)))
    else:
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)


def render_adapter(recipe):
    spec={key:recipe[key] for key in ['id','name','operation','source_path','source_commit','source_hashes','interface','example']}
    if 'class' in recipe:spec['class']=recipe['class']
    header='# Generated from tools/recipe_adapters and catalog/executable-conversions.json.\n# Hub adapter: MIT. Adapted upstream example retains its original license and authors.\n'
    source=(ROOT/'tools/recipe_adapters/core.py').read_text(encoding='utf-8').rstrip('\n')+'\n\n\n'+(ROOT/f"tools/recipe_adapters/{recipe['backend']}.py").read_text(encoding='utf-8')
    return header+source+'\nSPEC = json.loads('+repr(json.dumps(spec,separators=(',',':')))+')\n\nif __name__ == "__main__":\n    raise SystemExit(adapter_main(SPEC, '+recipe['backend']+'_backend))\n'


def build_record(recipe,archive,adapter,requirements):
    ident=recipe['id']; version='1.0.0'
    interface=copy.deepcopy(recipe['interface'])
    interface['origin_reference_ids']=recipe['origin_reference_ids']
    interface['origin_relationship']='adapted_from; inspect declared model and inputs, not original robot compatibility'
    if recipe['operation']=='smoothing':
        interface['origin_relationship']+='; upstream shortcut loop with corrected arclength interpolation and exact segment/circle checks in the Hub wrapper'
    receipt=EVIDENCE/(ident+'.json')
    proofs=[]
    if receipt.exists():
        proof=json.loads(receipt.read_text(encoding='utf-8'))
        for run in [proof]+proof.get('additional_runs',[]):
            if run['adapter_sha256']!=digest(adapter.encode()) or run['case_plan_sha256']!=digest(encoded(recipe['cases'])) or run['source_commit']!=archive['commit'] or run['source_guards_sha256']!=digest(encoded(recipe['source_hashes'])):
                raise ValueError(ident+': runtime proof is stale; rerun rather than relabel it')
            if run['passed']!=len(recipe['cases']) or run['failed']!=0 or run.get('negative_unknown_field_rejected') is not True or [c['input'] for c in run['cases']]!=recipe['cases'] or not all(c['passed'] and c['exit_code']==0 for c in run['cases']): raise ValueError(ident+': not all frozen cases and input rejections passed')
            if not set(archive['packages'])<=set(run['packages']):raise ValueError(ident+': declared runtime versions differ from the measured environment')
        proofs=[receipt.relative_to(ROOT).as_posix()]
    systems=['linux'] if recipe['backend']=='pybullet' else ['windows','linux']
    tested={system for run in [proof]+proof.get('additional_runs',[]) for system in run.get('platforms',[])} if proofs else set()
    combos=[{'runtime':recipe['backend'],'runtime_version':archive['commit'][:12] if recipe['backend']=='pythonrobotics' else '0.19.4' if recipe['backend']=='ruckig' else '3.2.7',
        'robot':'synthetic-seven-axis-or-procedural-scene' if recipe['backend']=='pybullet' else 'independent-axes' if recipe['backend']=='ruckig' else 'mathematical-model',
        'controller':'json-contract-v1','observation':'explicit-json-input','os':system,'architecture':'x86_64','python':'3.10',
        'status':'hub_verified' if system in tested else 'source_reviewed'} for system in systems]
    level='task_complete' if proofs else 'source_reviewed'
    return {'schema_version':'1','id':ident,'name':recipe['name'],'summary':recipe['name']+'. Parameterized bounded JSON adapter; '+('synthetic DIRECT simulation, no physical robot.' if recipe['backend']=='pybullet' else 'numerical operation, no hardware execution.'),
        'capabilities':[recipe['interface']['kind'],recipe['operation'].replace('_','-'),'executable-json','source-adaptation'],
        'aliases':[recipe['operation'].replace('_',' '),recipe['name']]+(['rapidly exploring random tree'] if recipe['operation'] in ['rrt','rrt_star'] else [])+(['rrtstar'] if recipe['operation']=='rrt_star' else []),
        'source':{'repository':archive['repository'],'commit':archive['commit'],'paths':list(recipe['source_hashes']),
            'archive_url':archive['archive_url'],'archive_sha256':archive['archive_sha256'],'archive_bytes':archive['archive_bytes'],'authors':archive['authors']},
        'license':archive['license'],'compatibility':combos,
        'observation':{'required':['explicit_json_task_input'],'privileged_state':recipe['backend']=='pybullet','description':'All inputs and outputs follow interface v1. Simulation adapters query exact synthetic simulator state; no perception or physical sensor compatibility.'},
        'requirements':{'python':'>=3.10,<3.11','packages':archive['packages'],'hardware':['x86_64 CPU; no GPU or robot required'],
            'rendering':'No display. Matplotlib Agg for numerical imports; PyBullet DIRECT for simulation.','api_keys':[],
            'network':['Pinned source archive once during preparation','PyPI for declared dependency installation'],
            'dependency_lock':'Runtime dependency versions are pinned for the supported Python 3.10 x86_64 CPU environments and checked against execution receipts. Platform-specific wheel hashes are not represented as a universal artifact lock; prepare captures pip freeze.'},
        'invocation':{'entrypoint':'python run.py','argv':['{python}','{recipe_dir}/run.py','--source-dir','{source_dir}','--example'],
            'inputs':recipe['example'],'outputs':{'format':'single JSON object on stdout','payload_selector':'outputs','schema':interface['output_schema']},
            'example':'After prepare, replace --example in next_command with --input /absolute/path/task.json; use --describe for the exact contract without execution.'},
        'interface':interface,
        'completion':{'success_condition':'Exit 0, status=task_complete, success=true, finite outputs satisfying interface.output_schema and all declared numerical/model checks. This is not a physical robot or general task-success claim.',
            'timeout_seconds':30,'failure_modes':['Invalid or oversized JSON','Source checksum mismatch','Unavailable pinned dependency','No valid path or postcondition failure','Execution exceeding the declared bounded algorithm budget'],
            'stop_condition':'Caller must terminate the separate adapter process after 30 seconds; adapters bound iterations/scene steps and close simulation clients.'},
        'preparation':{'recipe_path':'recipes/'+ident,'requirements_file':'recipes/'+ident+'/requirements.txt','source_selection':'declared_paths',
            'install_argv':['{python}','-m','pip','install','--only-binary=:all:','-r','{recipe_dir}/requirements.txt'],'execution_separate':True},
        'evidence':{'level':level,'verified_by':'Hub maintainer runtime harness' if proofs else 'Hub source review','date':'2026-10-19','environment':{'scope':interface['execution_domain'],'platforms':sorted(tested),'physical_robot':False},
            'commands':['python tools/verify_executable_recipes.py --source-cache SOURCE_CACHE --output OUTPUT --backend '+recipe['backend']],
            'result':'Three frozen positive cases passed against this exact adapter; see per-case receipts. This does not estimate general accuracy.' if proofs else 'Source and interface reviewed; runtime cases have not been recorded.',
            'artifacts':proofs,'runtime_verification':level if proofs else 'not_run','contributor_reported':None,
            'hub_verification':{'scope':interface['execution_domain'],'case_count':len(recipe['cases']) if proofs else 0,'source_unchanged':True}},
        'maintenance':{'record_version':version,'last_checked':'2026-10-19','upstream_status':'immutable_source_and_explicit_dependency_versions'},
        'contribution':{'allowed_paths':['catalog/records/'+ident+'.json','docs/recipes/'+ident+'.md','recipes/'+ident+'/run.py','recipes/'+ident+'/requirements.txt'],
            'instructions':'Preserve upstream origin/license and interface semantics. Edit the finite manifest/templates and regenerate; record new exact-byte evidence for behavior changes.'}}


def generate(check=False,adapters_only=False):
    manifest=json.loads(MANIFEST.read_text(encoding='utf-8'))
    guide=(ROOT/'docs/executable-skills.md').read_text(encoding='utf-8')
    write(ROOT/'skills/find-robot-skills/references/executable-skills.md',guide,check)
    dependencies=sorted({package for source in manifest['sources'].values() for package in source['packages']})
    write(ROOT/'tools/recipe_adapters/requirements-cpu.txt','\n'.join(dependencies)+'\n',check)
    ids=set()
    for recipe in manifest['recipes']:
        ident=recipe['id']
        if ident in ids:raise ValueError('Duplicate recipe')
        ids.add(ident)
        archive=manifest['sources'][recipe['backend']]
        adapter=render_adapter(recipe);requirements='\n'.join(archive['packages'])+'\n'
        if adapters_only:
            write(ROOT/'recipes'/ident/'run.py',adapter,check)
            write(ROOT/'recipes'/ident/'requirements.txt',requirements,check)
            continue
        record=build_record(recipe,archive,adapter,requirements)
        note='# '+recipe['name']+'\n\nParameterized adaptation of `'+recipe['source_path']+'` from '+archive['repository']+' at `'+archive['commit']+'`. Original authors: '+', '.join(archive['authors'])+'. Upstream license: '+archive['license']['spdx']+'. Source license and all notices remain in the prepared checkout; the Hub adapter is MIT.\n\nUse the record interface for input/output schemas, units, frames, prerequisites and failures. `--describe` reads the contract; `--example` runs the declared case. Replace `--example` with `--input TASK.json` for a different input. This adapter does not command physical hardware.\n'
        for path,body in [(ROOT/'recipes'/ident/'run.py',adapter),(ROOT/'recipes'/ident/'requirements.txt',requirements),(ROOT/'docs/recipes'/f'{ident}.md',note),(ROOT/'catalog/records'/f'{ident}.json',json.dumps(record,indent=2,ensure_ascii=False)+'\n')]:write(path,body,check)
    print(('Checked' if check else 'Generated')+' '+str(len(ids))+' executable source adaptations')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--check',action='store_true')
    p.add_argument('--adapters-only',action='store_true',help='Refresh adapter bytes before rerunning stale evidence; metadata is regenerated only after verification')
    args=p.parse_args();generate(args.check,args.adapters_only)
