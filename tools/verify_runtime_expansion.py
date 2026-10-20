"""Run fixed simulation cases in bounded subprocesses and retain exact receipts."""
import argparse,concurrent.futures,datetime,hashlib,importlib.metadata,json,pathlib,platform,subprocess,sys,tempfile,time
from runtime_expansion import encoded,sha
ROOT=pathlib.Path(__file__).resolve().parents[1]

def execute(recipe,source,cache,output,hub_commit):
    adapter=ROOT/'recipes'/recipe['id']/'run.py';source_dir=cache/('source-'+recipe['source_id'])
    timeout=1200 if recipe['backend']=='lerobot' else 180
    def run(data,root=source_dir):
        started=time.monotonic()
        try:
            result=subprocess.run([sys.executable,str(adapter),'--source-dir',str(root),'--input-json',json.dumps(data)],capture_output=True,text=True,timeout=timeout)
            try:body=json.loads(result.stdout)
            except ValueError:body={'protocol_error':'No single JSON response'}
            return {'exit_code':result.returncode,'result':body,'elapsed_seconds':round(time.monotonic()-started,3),'stderr_tail':result.stderr[-1800:]}
        except subprocess.TimeoutExpired:return {'exit_code':124,'result':{'timed_out':True},'elapsed_seconds':timeout}
    cases=[]
    for data in recipe['cases']:
        result=run(data);body=result['result']
        result.update(input=data,passed=result['exit_code']==0 and body.get('success') is True and bool(body.get('checks')) and all(v is True for v in body['checks'].values()))
        cases.append(result)
    rejection=run({**recipe['cases'][0],'unexpected_input':True})
    unknown=rejection['exit_code']==2 and rejection['result'].get('reason_code')=='invalid_input_or_environment' and 'unknown field' in rejection['result'].get('message','')
    with tempfile.TemporaryDirectory(prefix='rsh-drift-') as temporary:
        root=pathlib.Path(temporary);first=next(iter(recipe['source_hashes']));path=root/first;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('tampered source')
        rejection=run(recipe['cases'][0],root)
    drift=rejection['exit_code']==2 and 'checksum changed' in rejection['result'].get('message','')
    packages={}
    for pin in source['packages']:
        name=pin.split('==')[0]
        try:packages[name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:packages[name]='not_installed'
    observed={'os':platform.system().lower(),'architecture':platform.machine(),'python':'.'.join(platform.python_version_tuple()[:2])}
    assert all(observed[k]==recipe['environment'][k] for k in observed),observed
    proof={'schema_version':'1','skill_id':recipe['id'],'recorded_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'hub_commit':hub_commit,'adapter_sha256':sha(adapter.read_bytes()),'source_commit':source['commit'],
        'archive_sha256':source['archive_sha256'],'case_plan_sha256':sha(encoded(recipe['cases'])),
        'source_guards_sha256':sha(encoded(recipe['source_hashes'])),'environment':recipe['environment'],
        'packages':packages,'cases':cases,'passed':sum(c['passed'] for c in cases),'failed':sum(not c['passed'] for c in cases),
        'negative_unknown_field_rejected':unknown,'negative_source_drift_rejected':drift,'hardware_execution':False,
        'scope':'Authored bounded simulation cases; not general accuracy or physical compatibility.'}
    output.mkdir(parents=True,exist_ok=True);(output/(recipe['id']+'.json')).write_text(json.dumps(proof,indent=2)+'\n')
    print(json.dumps({'id':recipe['id'],'passed':proof['passed'],'failed':proof['failed'],'negative_checks':unknown and drift}),flush=True)
    return proof

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--backend',default='all',choices=['all','menagerie','robosuite','gymrobotics','lerobot','pandagym','dmcontrol']);parser.add_argument('--source-cache',type=pathlib.Path,required=True);parser.add_argument('--output',type=pathlib.Path,required=True);parser.add_argument('--hub-commit',required=True);parser.add_argument('--workers',type=int,default=4);parser.add_argument('--skill-id',action='append',default=[])
    args=parser.parse_args();assert 1<=args.workers<=8 and len(args.hub_commit)==40
    manifest=json.loads((ROOT/'catalog/runtime-expansion.json').read_text());recipes=[r for r in manifest['recipes'] if (args.backend=='all' or r['backend']==args.backend) and (not args.skill_id or r['id'] in args.skill_id)]
    if not recipes or (args.skill_id and set(args.skill_id)!={r['id'] for r in recipes}):raise ValueError('Unknown recipe selection')
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        results=list(pool.map(lambda r:execute(r,manifest['sources'][r['source_id']],args.source_cache,args.output,args.hub_commit),recipes))
    freeze=subprocess.run([sys.executable,'-m','pip','freeze'],capture_output=True,text=True,check=True).stdout
    (args.output/'environment-freeze.txt').write_text(freeze)
    (args.output/'batch-summary.json').write_text(json.dumps({'hub_commit':args.hub_commit,'backend':args.backend,'recipes':len(results),'passed':sum(p['passed'] for p in results),'failed':sum(p['failed'] for p in results)},indent=2)+'\n')
    return 0 if all(r['failed']==0 and r['negative_unknown_field_rejected'] and r['negative_source_drift_rejected'] for r in results) else 1
if __name__=='__main__':raise SystemExit(main())
