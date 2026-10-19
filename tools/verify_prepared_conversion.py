"""Explicit end-to-end local preparation and execution of one reviewed adapter."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from build_catalog import load_records


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skill-id',required=True)
    parser.add_argument('--source-cache',type=Path,required=True)
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    plan=json.loads((ROOT/'catalog/executable-conversions.json').read_text())
    recipe=next(r for r in plan['recipes'] if r['id']==args.skill_id)
    if args.project.exists() or args.output.exists():raise ValueError('Use fresh project and receipt paths')
    args.project.parent.mkdir(parents=True,exist_ok=True);args.output.parent.mkdir(parents=True,exist_ok=True)
    record=next(r for r in load_records() if r['id']==args.skill_id)
    head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    with tempfile.TemporaryDirectory(dir=args.project.parent) as work:
        catalog=Path(work)/'local-candidate.json'
        catalog.write_text(json.dumps({'schema_version':'1','hub_commit':head,'records':[record]})+'\n')
        command=[sys.executable,str(ROOT/'skills/find-robot-skills/scripts/rsh.py'),'--catalog',str(catalog),'--offline','prepare',args.skill_id,
            '--project',str(args.project.resolve()),'--source-archive',str(args.source_cache.resolve()/(recipe['backend']+'.tar.gz')),'--install-deps','--json']
        prepared=subprocess.run(command,capture_output=True,timeout=240)
        (args.output.parent/(args.skill_id+'-prepare.stdout')).write_bytes(prepared.stdout)
        (args.output.parent/(args.skill_id+'-prepare.stderr')).write_bytes(prepared.stderr)
        if prepared.returncode:raise RuntimeError('Preparation failed; see retained stderr')
        body=json.loads(prepared.stdout)
    executed=subprocess.run(body['next_command'],cwd=body['next_command_cwd'],capture_output=True,timeout=30)
    (args.output.parent/(args.skill_id+'-execute.stdout')).write_bytes(executed.stdout)
    (args.output.parent/(args.skill_id+'-execute.stderr')).write_bytes(executed.stderr)
    result=json.loads(executed.stdout)
    if executed.returncode or result.get('success') is not True:raise RuntimeError('Prepared execution failed; see retained response')
    lock=json.loads(Path(body['lock_path']).read_text())
    if set(lock['source_files'])!=set(record['source']['paths']):raise ValueError('Declared source selection was not preserved')
    for name, content in record['preparation']['files'].items():
        if Path(body['recipe_dir'],name).read_bytes()!=content.encode('utf-8'):
            raise ValueError('Prepared adapter bytes differ from the verified catalog')
    receipt={'schema_version':'1','skill_id':args.skill_id,'catalog_scope':'local_candidate_from_exact_git_head','hub_commit':head,'source_commit':record['source']['commit'],
        'prepared':True,'dependencies_installed':lock['dependencies_installed'],'source_files':len(lock['source_files']),
        'adapter_sha256':hashlib.sha256(Path(body['recipe_dir'],'run.py').read_bytes()).hexdigest(),
        'execution_exit_code':executed.returncode,'execution_stdout_sha256':hashlib.sha256(executed.stdout).hexdigest(),'checks':result['checks'],
        'execution_domain':result['execution_domain'],'physical_robot':False,'gpu':False}
    args.output.write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))


if __name__=='__main__':main()
