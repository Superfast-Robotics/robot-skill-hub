"""Loopback-only disposable-host executor. No API keys or shell input."""
import hashlib,json,os,pathlib,subprocess,tempfile,time,uuid
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
ROOT=pathlib.Path(__file__).resolve().parent
IMAGE='rsh-reuse-pilot:v1'

def container(code,task,arm,judge=False):
    name='rsh-pilot-'+uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix='rsh-pilot-') as temp:
        work=pathlib.Path(temp);work.chmod(0o755)
        if not judge:
            (work/'solution.py').write_text(code);(work/'solution.py').chmod(0o644)
        cmd=['docker','run','--rm','--name',name,'--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges',
             '--cpus','1','--memory','1g','--pids-limit','64','--tmpfs','/tmp:rw,nosuid,size=128m','-i']
        shared=ROOT/'public'
        cmd+=['-v',str(shared)+':/public:ro','-e','PYTHONPATH=/public'+(':/hub' if arm=='hub' and not judge else '')]
        if judge:
            cmd+=['-v',str(ROOT/'judge.py')+':/judge.py:ro']
        else:
            cmd+=['-v',str(work)+':/candidate:ro','-v',str(ROOT/'sources')+':/sources:ro','-v',str(ROOT/'candidate_entry.py')+':/entry.py:ro']
            if arm=='hub':cmd+=['-v',str(ROOT/'hub')+':/hub:ro']
        cmd += [IMAGE,'python','/judge.py' if judge else '/entry.py']
        start=time.perf_counter()
        try:
            proc=subprocess.run(cmd,input=json.dumps(task),capture_output=True,text=True,timeout=35)
            result=None;recipe_calls=[]
            for line in proc.stdout.splitlines():
                if line.startswith('RSH_RESULT='):result=json.loads(line[len('RSH_RESULT='):])
                if line.startswith('RSH_REUSE='):recipe_calls=json.loads(line[len('RSH_REUSE='):])
            return {'exit_code':proc.returncode,'result':result,'recipe_calls':recipe_calls,'stderr':proc.stderr[-3000:],'elapsed_s':time.perf_counter()-start}
        except subprocess.TimeoutExpired:return {'exit_code':124,'result':None,'stderr':'Execution timeout','elapsed_s':time.perf_counter()-start}
        finally:subprocess.run(['docker','rm','-f',name],capture_output=True,timeout=10)

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_POST(self):
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<250000:raise ValueError('request size')
            req=json.loads(self.rfile.read(length));assert req['arm'] in ('baseline','hub')
            assert isinstance(req['code'],str) and len(req['code'])<60000
            rows=[]
            for task in req['cases']:
                run=container(req['code'],task,req['arm'])
                if run['exit_code']==0 and run['result'] is not None:
                    verdict=container('',{'kind':req['kind'],'task':task,'output':run['result']},'baseline',True)
                    run['grade']=verdict['result'] or {'passed':False,'error':'Judge process failed: '+verdict['stderr']}
                else:run['grade']={'passed':False,'error':run['stderr']}
                if req.get('require_recipe') and req['require_recipe'] not in run.get('recipe_calls',[]):
                    run['grade']={'passed':False,'error':'This condition requires calling the provided Hub adapter, not reimplementing it.','numerical_grade':run['grade']}
                rows.append(run)
            body=json.dumps({'runs':rows}).encode();self.send_response(200)
        except Exception as exc:body=json.dumps({'error':type(exc).__name__+': '+str(exc)[:300]}).encode();self.send_response(400)
        self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)

if __name__=='__main__':ThreadingHTTPServer(('127.0.0.1',int(os.environ.get('RSH_EXECUTOR_PORT','8769'))),Handler).serve_forever()
