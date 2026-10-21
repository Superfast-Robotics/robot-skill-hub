"""Deterministic all-trial aggregation; publish CSV, JSON and a standalone plot."""
import argparse,csv,hashlib,json,pathlib,statistics

def aggregate(rows):
    return {'trials':len(rows),'successful_trials':sum(r['success'] for r in rows),
      'held_out_passed':sum(r['held_out_passed'] for r in rows),'held_out_total':sum(r['held_out_total'] for r in rows),
      'input_tokens':sum(r['usage']['input_tokens'] for r in rows),'output_tokens':sum(r['usage']['output_tokens'] for r in rows),
      'cached_input_tokens':sum(r['usage']['cached_input_tokens'] for r in rows),'total_tokens':sum(r['usage']['total_tokens'] for r in rows),
      'model_calls':sum(r['model_calls'] for r in rows),'tool_calls':sum(r['tool_calls'] for r in rows),
      'hub_calls':sum(r['hub_calls'] for r in rows),'execution_attempts':sum(r['execution_attempts'] for r in rows),
      'development_failures':sum(r['development_failures'] for r in rows),
      'agent_elapsed_s':sum(r['agent_elapsed_s'] for r in rows),'median_agent_elapsed_s':statistics.median(r['agent_elapsed_s'] for r in rows) if rows else None,
      'estimated_model_usd':sum(r['estimated_model_usd'] for r in rows)}

def compare(base,hub):
    result={}
    for key in ['total_tokens','input_tokens','output_tokens','model_calls','tool_calls','agent_elapsed_s','estimated_model_usd']:
        result[key+'_reduction_percent']=100*(1-hub[key]/base[key]) if base[key] else None
    return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--work',type=pathlib.Path,required=True);p.add_argument('--output',type=pathlib.Path,required=True);args=p.parse_args()
    plan=json.loads((args.work/'plan.json').read_text());rows=json.loads((args.work/'results.json').read_text())
    assert len(rows)==plan['planned_trial_count'],'Never silently publish an incomplete planned cohort'
    assert len({r['id'] for r in rows})==len(rows)
    assert all(not r['infrastructure_error'] for r in rows),'Infrastructure failures must be resolved and disclosed'
    groups={arm:aggregate([r for r in rows if r['arm']==arm]) for arm in plan['arms']}
    pairs={}
    for r in rows:pairs.setdefault((r['task'],r['repeat']),{})[r['arm']]=r
    assert all(set(x)==set(plan['arms']) for x in pairs.values())
    joint=[r for pair in pairs.values() if all(x['success'] for x in pair.values()) for r in pair.values()]
    joint_groups={arm:aggregate([r for r in joint if r['arm']==arm]) for arm in plan['arms']}
    tasks={t['id']:{a:aggregate([r for r in rows if r['task']==t['id'] and r['arm']==a]) for a in plan['arms']} for t in plan['tasks']}
    summary={'plan_sha256':hashlib.sha256((args.work/'plan.json').read_bytes()).hexdigest(),'model':plan['model'],
      'planned_trials':plan['planned_trial_count'],'completed_trials':len(rows),'task_families':len(tasks),'all_trials':groups,
      'all_trial_comparison':compare(groups['baseline'],groups['hub']),'joint_success_pairs':len(joint)//2,'joint_success_trials':joint_groups,
      'joint_success_comparison':compare(joint_groups['baseline'],joint_groups['hub']),'by_task':tasks,
      'interpretation':'Small maintainer-authored warm-environment pilot. Repeated trials share task families and are not independent robotics tasks. No general accuracy, discovery, cold-setup or hardware claim.'}
    out=args.output;out.mkdir(parents=True,exist_ok=True)
    (out/'summary.json').write_bytes((json.dumps(summary,indent=2)+'\n').encode())
    with (out/'trials.csv').open('w',newline='',encoding='utf-8') as f:
        keys=['id','task','arm','repeat','success','held_out_passed','held_out_total','model_calls','tool_calls','hub_calls','execution_attempts','development_failures','agent_elapsed_s','estimated_model_usd','input_tokens','cached_input_tokens','output_tokens','total_tokens']
        writer=csv.DictWriter(f,fieldnames=keys);writer.writeheader()
        for r in rows:writer.writerow({k:({**r,**r['usage']})[k] for k in keys})
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    names={'astar':'A* path planning','trajectory':'Jerk-limited trajectory','bullet_ik':'PyBullet arm IK'}
    fig,axes=plt.subplots(1,3,figsize=(13.5,4.3))
    colors=['#8b95a5','#165dce']
    for ax,metric,title,scale in zip(axes,['total_tokens','agent_elapsed_s','successful_trials'],['API tokens per trial (thousands)','Time per trial (seconds)','Held-out success (trials)'],[1000,1,1]):
        for i,(task,values) in enumerate(tasks.items()):
            for j,arm in enumerate(plan['arms']):
                total=values[arm][metric];value=total/scale/(values[arm]['trials'] if metric!='successful_trials' else 1)
                ax.bar(i+(j-.5)*.32,value,width=.3,color=colors[j],label='Direct upstream' if j==0 and i==0 else ('Hub available' if i==0 else None))
                ax.text(i+(j-.5)*.32,value,str(round(value,1)) if metric!='successful_trials' else str(int(value)),ha='center',va='bottom',fontsize=9)
        ax.set_xticks(range(len(tasks)),[names[t].replace(' ','\n',1) for t in tasks],fontsize=9)
        ax.set_title(title,fontsize=11);ax.spines[['right','top']].set_visible(False);ax.margins(y=.18)
        if metric=='successful_trials':ax.set_ylim(0,3.8);ax.set_yticks([0,1,2,3])
    axes[0].legend(frameon=False,fontsize=9)
    fig.suptitle('Robot Skill Hub: paired agent reuse pilot',fontsize=15)
    fig.text(.5,.015,'3 task families × 3 repetitions × 2 conditions | GPT-4.1 mini (2025-04-14) | preinstalled environment | all trials retained',ha='center',fontsize=9)
    fig.tight_layout(rect=[0,.08,1,.93]);fig.savefig(out/'pilot-results.png',dpi=160);fig.savefig(out/'pilot-results.svg');plt.close(fig)
    print(json.dumps(summary))
if __name__=='__main__':main()
