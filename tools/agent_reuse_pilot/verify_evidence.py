"""Cross-check published summaries against every trace and execution receipt."""
import argparse,hashlib,json,pathlib,zipfile
from summarize import aggregate
def main():
    p=argparse.ArgumentParser();p.add_argument('--evidence',type=pathlib.Path,required=True);args=p.parse_args()
    total=0
    cohorts=sorted(p.name for p in args.evidence.iterdir() if p.is_dir() and (p/'plan.json').is_file())
    assert cohorts,'No cohorts found'
    for cohort in cohorts:
        root=args.evidence/cohort
        plan=json.loads((root/'plan.json').read_text());summary=json.loads((root/'summary.json').read_text());rows=json.loads((root/'results.json').read_text())
        assert len(rows)==plan['planned_trial_count']
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
                prices=dict(plan['pricing_usd_per_million_tokens']);expected_cost=0
                correction=root/'pricing-correction.json'
                if correction.exists():prices['cache_write']=json.loads(correction.read_text())['effective_cache_write_usd_per_million']
                for turn in trace:
                    u=turn['usage'];details=u.get('input_tokens_details',{});cached=details.get('cached_tokens',0);written=details.get('cache_write_tokens',0)
                    expected_cost+=((u['input_tokens']-cached)*prices['input']+cached*prices['cached_input']+u['output_tokens']*prices['output']+written*(prices.get('cache_write',prices['input'])-prices['input']))/1e6
                assert abs(expected_cost-r['estimated_model_usd'])<1e-12,'Cost does not match provider usage'
                held=json.loads(z.read(r['id']+'/held-out.json'))
                passed=sum(x['grade']['passed'] for x in held['runs']) if held else 0
                assert passed==r['held_out_passed']
                assert r['success']==(passed==r['held_out_total'])
                assert all(t['model']==plan['model'] for t in trace),'Unexpected model substitution'
                assert not r['infrastructure_error']
                if plan.get('forced_reuse') and r['arm']=='hub' and r['success']:
                    skill=next(t['skill_id'] for t in plan['tasks'] if t['id']==r['task'])
                    assert all(skill in x.get('recipe_calls',[]) for x in held['runs'])
            for arm in ('baseline','hub'):
                assert summary['all_trials'][arm]==aggregate([r for r in rows if r['arm']==arm])
        total+=len(rows)
    print(json.dumps({'verified_trials':total,'cohorts':len(cohorts),'trace_usage_matches':True,'judgments_match':True,'archive_hashes_match':True}))
if __name__=='__main__':main()
