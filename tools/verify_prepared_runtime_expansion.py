"""Exercise normal prepare/install/returned-command flow on explicit cloud hosts."""
import argparse,hashlib,json,os,pathlib,subprocess,sys,time
import build_catalog as builder
ROOT=pathlib.Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--skill-id',action='append',required=True);parser.add_argument('--source-cache',type=pathlib.Path,required=True);parser.add_argument('--project-root',type=pathlib.Path,required=True);parser.add_argument('--output',type=pathlib.Path,required=True)
    args=parser.parse_args();plan=json.loads((ROOT/'catalog/runtime-expansion.json').read_text());recipes={r['id']:r for r in plan['recipes']};records={r['id']:r for r in builder.load_records()}
    args.output.mkdir(parents=True,exist_ok=True)
    environment={**os.environ,'RSH_TELEMETRY':'off','MUJOCO_GL':'egl','SDL_VIDEODRIVER':'dummy','HF_HUB_DISABLE_TELEMETRY':'1','WANDB_MODE':'disabled','PIP_DISABLE_PIP_VERSION_CHECK':'1'}
    for ident in args.skill_id:
        recipe=recipes[ident];record=records[ident];project=args.project_root/ident;project.mkdir(parents=True,exist_ok=True)
        catalog=project/'catalog.json';catalog.write_text(json.dumps({'schema_version':'1','hub_commit':'0'*40,'records':[record]}))
        selected_environment=project/'environment.json';selected_environment.write_text(json.dumps(recipe['environment']))
        cmd=[sys.executable,str(ROOT/'skills/find-robot-skills/scripts/rsh.py'),'--catalog',str(catalog),'--offline','prepare',ident,'--project',str(project),'--source-archive',str(args.source_cache/(recipe['source_id']+'.tar.gz')),'--environment',str(selected_environment),'--install-deps','--json']
        start=time.monotonic();prepared=subprocess.run(cmd,capture_output=True,text=True,env=environment,timeout=1800)
        (project/'prepare-stdout.txt').write_text(prepared.stdout);(project/'prepare-stderr.txt').write_text(prepared.stderr)
        if prepared.returncode:raise RuntimeError(ident+': preparation failed; inspect retained project logs')
        result=json.loads(prepared.stdout);folder=pathlib.Path(result['recipe_dir'])
        assert (folder/'run.py').read_bytes()==(ROOT/'recipes'/ident/'run.py').read_bytes()
        assert (folder/'LICENSE').read_bytes()==(ROOT/'recipes/LICENSE').read_bytes()
        assert (folder/'LICENSE_SCOPE.md').read_bytes()==(ROOT/'recipes/LICENSE_SCOPE.md').read_bytes()
        executed=subprocess.run(result['next_command'],cwd=result['next_command_cwd'],capture_output=True,text=True,env=environment,timeout=1200)
        (project/'task-stdout.txt').write_text(executed.stdout);(project/'task-stderr.txt').write_text(executed.stderr)
        body=json.loads(executed.stdout)
        proof={'schema_version':'1','skill_id':ident,'source_commit':record['source']['commit'],'adapter_sha256':hashlib.sha256((folder/'run.py').read_bytes()).hexdigest(),'harness_sha256':hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),
               'preparation_exit_code':prepared.returncode,'task_exit_code':executed.returncode,'result':body,'adapter_bytes_preserved':True,'mit_license_and_scope_preserved':True,
               'source_archive_sha256':record['source']['archive_sha256'],'elapsed_seconds':round(time.monotonic()-start,3),'hardware_execution':False}
        (args.output/(ident+'.json')).write_text(json.dumps(proof,indent=2)+'\n')
        print(json.dumps({'id':ident,'prepared':True,'task_success':body.get('success'),'exit_code':executed.returncode}),flush=True)
        if executed.returncode or body.get('success') is not True:raise RuntimeError(ident+': prepared command did not complete its frozen example')
if __name__=='__main__':main()
