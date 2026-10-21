"""Execution-only infrastructure/judge checks, excluded from model trials."""
import argparse,json,pathlib
from run import execute
def main():
    p=argparse.ArgumentParser();p.add_argument('--work',type=pathlib.Path,required=True);p.add_argument('--endpoint',default='http://127.0.0.1:18769');args=p.parse_args()
    plan=json.loads((args.work/'plan.json').read_text());rows=[]
    for task in plan['tasks']:
        code='from hub_runtime import run_recipe\ndef solve(task):\n    return run_recipe('+repr(task['skill_id'])+',task)\n'
        result=execute(args.endpoint,task,'hub',code,[task['development']]+task['held_out'],task['skill_id'] if plan.get('forced_reuse') else None)
        good=[x['grade'] for x in result['runs']]
        assert all(x['passed'] for x in good),(task['id'],good)
        # Prove that success claims, zero arrays and a fabricated result are rejected.
        bad=execute(args.endpoint,task,'baseline',"def solve(task):\n    return {'success':True}\n",[task['development']])
        assert not bad['runs'][0]['grade']['passed']
        enforced=None
        if plan.get('forced_reuse'):
            copied='def solve(task):\n    return '+repr(result['runs'][0]['result'])+'\n'
            bypass=execute(args.endpoint,task,'hub',copied,[task['development']],task['skill_id'])
            grade=bypass['runs'][0]['grade']
            assert not grade['passed'] and grade['numerical_grade']['passed']
            enforced=True
        rows.append({'task':task['id'],'valid_cases_passed':len(good),'fabricated_success_rejected':True,'numerically_correct_nonreuse_rejected':enforced})
    receipt={'type':'maintainer_infrastructure_preflight','model_calls':0,'rows':rows}
    (args.work/'executor-preflight.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt))
if __name__=='__main__':main()
