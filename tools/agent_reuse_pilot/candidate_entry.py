"""Container entry point. Candidate cannot see hidden cases or the judge."""
import contextlib,importlib.util,io,json,sys,traceback
item=json.load(sys.stdin)
recipe_calls=[]
def profile(frame,event,arg):
    if event=='call' and frame.f_code.co_filename=='/hub/hub_runtime.py' and frame.f_code.co_name=='run_recipe':
        recipe_calls.append(frame.f_locals.get('skill_id'))
try:
    sys.setprofile(profile)
    with contextlib.redirect_stdout(sys.stderr):
        spec=importlib.util.spec_from_file_location('solution','/candidate/solution.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        output=module.solve(item)
    sys.setprofile(None)
    print('RSH_REUSE='+json.dumps(recipe_calls))
    print('RSH_RESULT='+json.dumps(output,allow_nan=False))
except Exception:
    traceback.print_exc();sys.exit(1)
