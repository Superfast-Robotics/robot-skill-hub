"""Generate source-pinned diverse simulation recipes; never download or run code."""
import argparse,copy,json
from pathlib import Path
from runtime_expansion import bound_receipt
ROOT=Path(__file__).resolve().parents[1]

def render(recipe, source):
    spec={k:copy.deepcopy(v) for k,v in recipe.items() if k not in ['cases','source_id','environment','source_paths','origin_reference_ids','license','abstraction_level','capabilities']}
    spec['source_commit']=source['commit'];spec['packages']=source['packages']
    template=recipe.get('adapter_template','mainstream')
    if template not in ['mainstream','mujoco_extra','seed_tasks','joint_feedback','panda_stack','metaworld_policy','mink_servo','genesis_servo']:raise ValueError('Unknown adapter template')
    text=(ROOT/'tools/recipe_adapters/core.py').read_text()+'\n\n'+(ROOT/('tools/recipe_adapters/'+template+'.py')).read_text()
    return ('# Hub-authored adapter: MIT. Upstream source/models retain their original licenses.\n'+text+'\nSPEC = json.loads('+repr(json.dumps(spec,separators=(',',':')))+')\n\nif __name__ == "__main__":\n    raise SystemExit(adapter_main(SPEC, mainstream_backend))\n').encode()

def record(recipe,source,adapter):
    ident=recipe['id'];proof=bound_receipt(ROOT,recipe,source,adapter)
    complete=bool(proof) and proof['failed']==0
    executed=bool(proof) and any(c.get('result',{}).get('outputs') for c in proof['cases'])
    evidence_path='evidence/runtime/diverse-sim-v1/'+ident+'.json'
    level='task_complete' if complete else 'import_verified' if executed else 'source_reviewed'
    environment=copy.deepcopy(recipe['environment']);environment['status']='hub_verified' if complete else 'source_reviewed'
    interface=copy.deepcopy(recipe['interface'])
    if recipe['origin_reference_ids']:
        interface.update(origin_reference_ids=recipe['origin_reference_ids'],origin_relationship='prepared_from_the_same_pinned_model; inspect the declared controller and goal; no physical compatibility is inferred')
    license=recipe['license']
    invocation=['{python}','{recipe_dir}/run.py','--source-dir','{source_dir}','--example']
    install=['{python}','-m','pip','install']+([] if recipe['backend'] in ['robosuite','lerobot'] else ['--only-binary=:all:'])+['-r','{recipe_dir}/requirements.txt']
    evidence={'level':level,'verified_by':'Hub finite-case Lambda execution harness' if proof else 'Hub source review','date':'2026-10-20',
        'environment':{'scope':'simulation','physical_robot':False,'platforms':['linux'] if executed else []},
        'commands':['python tools/verify_runtime_expansion.py --backend '+recipe['backend']+' --source-cache SOURCE_CACHE --output OUTPUT'],
        'result':('All '+str(proof['passed'])+' frozen cases completed against this exact adapter and source.' if complete else
                  str(proof['passed'])+'/'+str(len(proof['cases']))+' frozen cases completed; retained failures are not promoted.' if proof else 'Execution not yet recorded.'),
        'artifacts':[evidence_path] if proof else [],'runtime_verification':'task_complete' if complete else 'import_verified' if executed else 'not_run',
        'contributor_reported':None,'hub_verification':{'runtime':'task_complete' if complete else 'import_verified' if executed else 'not_run','scope':'simulation',
             'adapter_sha256':__import__('hashlib').sha256(adapter).hexdigest(),'source_commit':source['commit'],'record_version':'1.0.0',
             'case_count':len(proof['cases']) if proof else 0,'retained_failed_cases':proof['failed'] if proof else 0}}
    return {'schema_version':'1','id':ident,'name':recipe['name'],'summary':recipe['summary'],
        'capabilities':recipe['capabilities'],'aliases':[recipe['environment']['robot'],recipe['backend'],recipe['operation']],
        'source':{k:source[k] for k in ['repository','commit','archive_url','archive_sha256','archive_bytes','authors']}|{'paths':recipe['source_paths']},
        'license':license,'compatibility':[environment],
        'observation':{'required':['simulator_state' if recipe['backend']!='lerobot' else 'RGB_pixels_and_pusher_position'],
                       'privileged_state':recipe['backend']!='lerobot','description':recipe['observation_description']},
            'requirements':{'python':'>='+environment['python']+',<'+environment['python'].split('.')[0]+'.'+str(int(environment['python'].split('.')[1])+1),'packages':source['packages'],'hardware':['Linux x86_64; '+('CUDA GPU, tested on A100 40GB' if recipe['backend']=='lerobot' else 'CUDA GPU; see retained receipt for the exact host environment' if recipe['backend']=='genesis' else 'CPU simulation; see retained receipt for the exact host environment')],
            'rendering':'Headless. EGL libraries are required for MuJoCo imports; PushT uses SDL dummy video. No interactive display.',
            'api_keys':[],'network':['Pinned source archive during preparation','PyPI dependencies during explicit installation']+(['Pinned public Hugging Face checkpoint on first execution'] if recipe['backend']=='lerobot' else []),
            'dependency_lock':'Direct runtime versions are pinned and measured. The receipt retains the complete environment freeze; prepare records the installed environment. System drivers are separate host requirements.'+(' Linux device dependencies may build evdev from source; an available C compiler and explicit dependency-install permission are required.' if recipe['backend'] in ['robosuite','lerobot'] else '')},
        'invocation':{'entrypoint':'python run.py','argv':invocation,'inputs':recipe['example'],
            'outputs':{'format':'single JSON object','payload_selector':'outputs','schema':recipe['interface']['output_schema']},
            'example':'Prepare explicitly; run --example or replace it with --input TASK.json. --describe reads the bounded contract without running simulation.'},
        'interface':interface,
        'completion':{'success_condition':'All declared goal and finite-state checks pass; exit 0 with task_complete. '+recipe['goal_scope'],
            'timeout_seconds':recipe.get('timeout_seconds',1200 if recipe['backend']=='lerobot' else 180),
            'failure_modes':['Invalid input or source checksum','Different pinned package version','Unavailable runtime/driver','Goal not reached within bounded steps'],
            'stop_condition':'Terminate the adapter at the recorded timeout. No physical hardware is opened.'},
        'preparation':{'recipe_path':'recipes/'+ident,'requirements_file':'recipes/'+ident+'/requirements.txt',
            'source_selection':'declared_paths' if recipe['backend'] in ['menagerie','lerobot','dmcontrol','pandagym'] else None,
            'install_argv':install,'execution_separate':True},
        'evidence':evidence,'maintenance':{'record_version':'1.0.0','last_checked':'2026-10-20','upstream_status':'immutable_source_and_explicit_dependencies'},
        'contribution':{'allowed_paths':['catalog/records/'+ident+'.json','recipes/'+ident+'/run.py','recipes/'+ident+'/requirements.txt','docs/recipes/'+ident+'.md'],
             'instructions':'Change the runtime expansion manifest/template, regenerate, and rerun all frozen cases. Preserve source/model/checkpoint licenses and distinguish simulation from hardware.'}}

def generate(check=False, adapters_only=False):
    manifest=json.loads((ROOT/'catalog/runtime-expansion.json').read_text())
    for recipe in manifest['recipes']:
        source=manifest['sources'][recipe['source_id']];adapter=render(recipe,source)
        files={Path('recipes')/recipe['id']/'run.py':adapter,Path('recipes')/recipe['id']/'requirements.txt':('\n'.join(source['packages'])+'\n').encode()}
        if not adapters_only:
            value=record(recipe,source,adapter)
            if value['preparation']['source_selection'] is None:del value['preparation']['source_selection']
            files[Path('catalog/records')/(recipe['id']+'.json')]=(json.dumps(value,indent=2)+'\n').encode()
            files[Path('docs/recipes')/(recipe['id']+'.md')]=('# '+recipe['name']+'\n\n'+recipe['summary']+'\n\n'+recipe['goal_scope']+'\n\nSource and model terms: '+recipe['license']['spdx']+'. The Hub wrapper is MIT. See the record for input JSON, exact environment, frozen execution receipts and preparation requirements.\n').encode()
        for relative,raw in files.items():
            path=ROOT/relative
            if check:
                if not path.exists() or path.read_bytes()!=raw:raise ValueError('Generated file differs: '+str(relative))
            else:path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
    print(('Checked' if check else 'Generated')+' '+str(len(manifest['recipes']))+' diverse simulation adapters')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--check',action='store_true');parser.add_argument('--adapters-only',action='store_true')
    args=parser.parse_args();generate(args.check,args.adapters_only)
