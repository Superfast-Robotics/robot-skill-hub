"""Cross-check published summaries against every trace and execution receipt."""
import argparse,hashlib,json,pathlib,zipfile
from summarize import aggregate
def main():
    p=argparse.ArgumentParser();p.add_argument('--evidence',type=pathlib.Path,required=True);args=p.parse_args()
    total=0
    for cohort in ('optional41','guided41','guided54'):
        root=args.evidence/cohort
        plan=json.loads((root/'plan.json').read_text());summary=json.loads((root/'summary.json').read_text());rows=json.loads((root/'results.json').read_text())
        assert len(rows)==plan['planned_trial_count']==18
        assert hashlib.sha256((root/'plan.json').read_bytes()).hexdigest()==summary['plan_sha256']==(root/'plan.sha256').read_text().strip()
        manifest=json.loads((root/'trace-manifest.json').read_text())
        assert hashlib.sha256((root/'traces.zip').read_bytes()).hexdigest()==manifest['archive_sha256']
        with zipfile.ZipFile(root/'traces.zip') as z:
            for f in manifest['files']:assert hashlib.sha256(z.read(f['path'])).hexdigest()==f['sha256']
            for r in rows:
                trace=json.loads(z.read(r['id']+'/trace.json'))
                for key in ('input_tokens','output_tokens','total_tokens'):
                    assert sum(t['usage'][key] for t in trace)==r['usage'][key],(r['id'],key)
                assert len(trace)==r['model_calls']
                assert sum(t['usage'].get('input_tokens_details',{}).get('cached_tokens',0) for t in trace)==r['usage']['cached_input_tokens']
                held=json.loads(z.read(r['id']+'/held-out.json'))
                passed=sum(x['grade']['passed'] for x in held['runs']) if held else 0
                assert passed==r['held_out_passed']
                assert r['success']==(passed==3)
                assert not r['infrastructure_error']
            for arm in ('baseline','hub'):
                assert summary['all_trials'][arm]==aggregate([r for r in rows if r['arm']==arm])
        total+=len(rows)
    print(json.dumps({'verified_trials':total,'cohorts':3,'trace_usage_matches':True,'judgments_match':True,'archive_hashes_match':True}))
if __name__=='__main__':main()
