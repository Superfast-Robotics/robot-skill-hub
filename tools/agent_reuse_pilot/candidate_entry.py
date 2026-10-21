"""Container entry point. Candidate cannot see hidden cases or the judge."""
import contextlib,importlib.util,io,json,sys,traceback
item=json.load(sys.stdin)
try:
    with contextlib.redirect_stdout(sys.stderr):
        spec=importlib.util.spec_from_file_location('solution','/candidate/solution.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        output=module.solve(item)
    print('RSH_RESULT='+json.dumps(output,allow_nan=False))
except Exception:
    traceback.print_exc();sys.exit(1)
