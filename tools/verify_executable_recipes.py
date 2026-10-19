"""Execute the frozen, reviewed finite cohort in separate CPU processes.

This is an explicit runtime test, not part of catalog building or public reads.
No credentials, model services, GPU resources or physical robots are used.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from generate_executable_recipes import render_adapter,encoded,digest


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-cache',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--backend',choices=['pythonrobotics','ruckig','pybullet','all'],default='all')
    p.add_argument('--publish-evidence',action='store_true',help='Write passing exact-byte receipts under evidence/runtime')
    args=p.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    manifest_path=ROOT/'catalog/executable-conversions.json'
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    (args.output/'plan.json').write_bytes(manifest_path.read_bytes())
    environment={k:v for k,v in os.environ.items() if k.upper() in ['PATH','SYSTEMROOT','WINDIR','TEMP','TMP','PATHEXT','PROCESSOR_ARCHITECTURE','PROCESSOR_ARCHITEW6432']}
    environment.update(PYTHONHASHSEED='0',MPLBACKEND='Agg',RSH_TELEMETRY='off',OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1',PYTHONNOUSERSITE='1')
    environment['MPLCONFIGDIR']=str((args.output/'matplotlib-cache').resolve())
    freeze=subprocess.run([sys.executable,'-m','pip','freeze'],capture_output=True,text=True,check=True).stdout
    reports=[]
    for recipe in manifest['recipes']:
        if args.backend!='all' and recipe['backend']!=args.backend:continue
        adapter=ROOT/'recipes'/recipe['id']/'run.py'
        assert adapter.read_bytes()==render_adapter(recipe).encode(), 'Regenerate before executing'
        results=[]
        for i,case in enumerate(recipe['cases']):
            start=time.monotonic()
            try:
                run=subprocess.run([sys.executable,str(adapter),'--source-dir',str(args.source_cache.resolve()/recipe['backend']),
                    '--input-json',json.dumps(case,separators=(',',':'))],cwd=args.output,env=environment,
                    capture_output=True,timeout=30,check=False)
                (args.output/(recipe['id']+'-'+str(i)+'.stdout')).write_bytes(run.stdout)
                (args.output/(recipe['id']+'-'+str(i)+'.stderr')).write_bytes(run.stderr)
                body=json.loads(run.stdout)
                ok=run.returncode==0 and body.get('success') is True and body.get('status')=='task_complete' and body.get('checks') and all(body['checks'].values())
                result={'case':i,'input':case,'passed':bool(ok),'exit_code':run.returncode,'stdout_sha256':digest(run.stdout),
                    'checks':body.get('checks',{}),'status':body.get('status'),'reason_code':body.get('reason_code'),
                    'message':body.get('message'),'elapsed_seconds':round(time.monotonic()-start,4)}
            except (subprocess.TimeoutExpired,json.JSONDecodeError) as error:
                result={'case':i,'input':case,'passed':False,'error':type(error).__name__,'elapsed_seconds':round(time.monotonic()-start,4)}
            results.append(result)
        bad={**recipe['example'],'unexpected_private_field':True}
        invalid=subprocess.run([sys.executable,str(adapter),'--input-json',json.dumps(bad)],env=environment,capture_output=True,timeout=5)
        try: rejected=invalid.returncode==2 and json.loads(invalid.stdout)['reason_code']=='invalid_input_or_environment'
        except (ValueError,KeyError):rejected=False
        report={'schema_version':'1','skill_id':recipe['id'],'source_commit':recipe['source_commit'],
            'adapter_sha256':digest(adapter.read_bytes()),'source_guards_sha256':digest(encoded(recipe['source_hashes'])),
            'case_plan_sha256':digest(encoded(recipe['cases'])),'passed':sum(r['passed'] for r in results),'failed':sum(not r['passed'] for r in results),
            'negative_unknown_field_rejected':rejected,'platforms':[{'Windows':'windows','Linux':'linux'}.get(platform.system(),platform.system().lower())],
            'python':platform.python_version(),'architecture':platform.machine().lower(),'packages':freeze.splitlines(),
            'execution_domain':recipe['interface']['execution_domain'],'physical_robot':False,'gpu':False,
            'observed_at':datetime.now(timezone.utc).isoformat(),'scope':'Three authored positive regression cases and one invalid input. Not general accuracy, LLM selection, real hardware, collision certification or real-time performance.',
            'cases':results}
        (args.output/(recipe['id']+'.json')).write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
        reports.append(report)
        print(json.dumps({'skill_id':recipe['id'],'passed':report['passed'],'failed':report['failed'],'negative_input_rejected':rejected}),flush=True)
    good=bool(reports) and all(r['failed']==0 and r['negative_unknown_field_rejected'] for r in reports)
    summary={'schema_version':'1','backend':args.backend,'adapters':len(reports),'positive_cases':sum(r['passed']+r['failed'] for r in reports),
        'passed':sum(r['passed'] for r in reports),'failed':sum(r['failed'] for r in reports),'invalid_input_rejections':sum(r['negative_unknown_field_rejected'] for r in reports),
        'all_passed':good,'plan_sha256':digest(manifest_path.read_bytes()),'physical_robot':False,'gpu':False}
    (args.output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    if args.publish_evidence:
        if not good: raise SystemExit('Evidence publication refused: keep all failed receipts and fix the adapter, not the frozen cases.')
        dest=ROOT/'evidence/runtime/executable-conversions-v1';dest.mkdir(parents=True,exist_ok=True)
        for report in reports:(dest/(report['skill_id']+'.json')).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(summary))
    return 0 if good else 1


if __name__=='__main__':raise SystemExit(main())
