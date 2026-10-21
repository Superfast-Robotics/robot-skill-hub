"""Freeze the pilot plan, acquire hash-checked public inputs, stage executor."""
import argparse,concurrent.futures,hashlib,json,pathlib,shutil,subprocess,tarfile,urllib.request
ROOT=pathlib.Path(__file__).resolve().parents[2]
HERE=pathlib.Path(__file__).resolve().parent
IDS={'astar':'pythonrobotics-astar-planner','trajectory':'ruckig-offline-trajectory','bullet_ik':'pybullet-ik-skill'}
def sha(raw):return hashlib.sha256(raw).hexdigest()
def download(url):
    req=urllib.request.Request(url,headers={'DNT':'1','X-RSH-Telemetry':'off','User-Agent':'robot-skill-hub/maintainer-reuse-pilot'})
    with urllib.request.urlopen(req,timeout=45) as r:return r.read()

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=pathlib.Path,required=True);args=p.parse_args()
    out=args.output;out.mkdir(exist_ok=True,parents=True);stage=out/'executor';stage.mkdir(exist_ok=True)
    for name in ['Dockerfile','executor.py','candidate_entry.py','judge.py']:shutil.copy2(HERE/name,stage/name)
    (stage/'public').mkdir(exist_ok=True);shutil.copy2(HERE/'scene.py',stage/'public/scene.py')
    (stage/'hub').mkdir(exist_ok=True);shutil.copy2(HERE/'hub_runtime.py',stage/'hub/hub_runtime.py')
    manifest=json.loads((ROOT/'catalog/executable-conversions.json').read_text())
    records={r['id']:r for r in manifest['recipes']};sources=manifest['sources']
    jobs=[];source_receipts=[]
    for kind,ident in IDS.items():
        r=records[ident];src=sources[r['backend']]
        folder=stage/'hub'/ident;folder.mkdir(exist_ok=True)
        shutil.copy2(ROOT/'recipes'/ident/'run.py',folder/'run.py')
        shutil.copy2(ROOT/'recipes'/ident/'LICENSE',folder/'LICENSE') if (ROOT/'recipes'/ident/'LICENSE').exists() else None
        for name,digest in r['source_hashes'].items():
            url=src['repository'].replace('https://github.com/','https://raw.githubusercontent.com/')+'/'+src['commit']+'/'+name
            target=stage/'sources'/r['backend']/name
            jobs.append((url,target,digest))
        source_receipts.append({'skill_id':ident,'upstream':src['repository'],'commit':src['commit'],'adapter_sha256':sha((folder/'run.py').read_bytes())})
    def fetch(job):
        url,path,digest=job
        if path.exists() and sha(path.read_bytes())==digest:return
        raw=b'' if digest==sha(b'') else download(url)
        assert sha(raw)==digest,url
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:list(pool.map(fetch,jobs))
    def grid(start,goal,wall,limit):return {'start':start,'goal':goal,'bounds':[0,20],'obstacles':[[wall,y] for y in range(1,limit+1)],'robot_radius':.3}
    def trajectory(target,velocity=None):
        n=len(target)
        return {'current_position':[0.]*n,'current_velocity':[0.]*n,'current_acceleration':[0.]*n,'target_position':target,
          'target_velocity':velocity or [0.]*n,'target_acceleration':[0.]*n,'max_velocity':[1.]*n,'max_acceleration':[2.]*n,
          'max_jerk':[4.]*n,'dt':.02,'coordinate_type':'revolute_rad'}
    def bullet(xyz):return {'joint_angles':[.1,-.3,.4,.2,-.2,.1,.1],'target_xyz':xyz}
    cases={
      'astar':[grid([3,3],[17,16],9,11),grid([17,3],[3,17],11,12),grid([4,5],[16,9],10,13),grid([3,16],[17,3],8,10)],
      'trajectory':[trajectory([.8,-.6,.35]),trajectory([-.7,.4]),trajectory([1.1,-.3,.6],[.1,-.1,0]),trajectory([-.25])],
      'bullet_ik':[bullet([.32,.15,1.08]),bullet([.28,-.16,1.03]),bullet([.38,.12,.98]),bullet([-.25,.2,1.05])]}
    text={
      'astar':'Write a reusable solve(task) returning path_xy and length_m for a circular robot in a 2D map (metres). Path must run start to goal, remain strictly inside bounds, and every continuous segment must clear all point obstacles and the integer-sampled boundary by robot_radius. No shortest-path optimality claim is required. Use available pinned upstream code or implement the solver. Avoid plots.',
      'trajectory':'Write solve(task) returning time_s, position, velocity, acceleration, coordinate_type, duration_s. Generate an offline jerk-limited trajectory for independent joint axes using the supplied boundary states and limits. Include t=0 and exact completion time, sample spacing <= dt, all position/velocity/acceleration endpoints within 1e-6, and respect velocity, acceleration and sampled jerk bounds. Derivatives must be numerically consistent. Duration <=30 s, at most 3000 samples. Ruckig is available. No physical robot.',
      'bullet_ik':'Write solve(task) for headless PyBullet inverse kinematics on the provided synthetic seven-axis arm. Use scene.create_arm(pybullet) from /public/scene.py to construct it in DIRECT mode; initialize all seven joints from task. Solve link index 6 position for target_xyz (metres, world frame). Return joint_angles_rad, end_effector_xyz_m and position_error_m. A separate fresh simulator reconstructs the arm from your joint angles; target error must be <0.002 m. Do not use a different robot model. No orientation, collision-avoidance or physical-robot claim.'}
    tasklist=[]
    for kind,ident in IDS.items():
        r=records[ident]
        tasklist.append({'id':kind,'skill_id':ident,'request':text[kind],'source_path':'/sources/'+r['backend']+'/'+r['source_path'],
          'input_schema':r['interface']['input_schema'],'output_schema':r['interface']['output_schema'],
          'development':cases[kind][0],'held_out':cases[kind][1:]})
    plan={'version':'1','model':'gpt-4.1-mini-2025-04-14','temperature':.2,'repetitions':3,'arms':['baseline','hub'],'order_seed':20261021,
      'max_turns':8,'max_execution_attempts':5,'max_output_tokens':3500,'max_input_tokens_per_request':60000,'wall_clock_limit_s':600,
      'source_hub_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
      'primary':'All three held-out cases pass using the first development-passing candidate; missing or timed-out candidates fail.',
      'aggregation':'All trials and paired jointly successful trials; raw task-family rows; no significance/generalization claim.',
      'tasks':tasklist,'sources':source_receipts,'scope':'Warm preinstalled numerical robotics programming, including synthetic PyBullet IK. No installation/discovery/physical task benchmark.',
      'pricing_usd_per_million_tokens':{'input':.4,'cached_input':.1,'output':1.6},'pricing_source':'https://developers.openai.com/api/docs/models/gpt-4.1-mini',
      'planned_trial_count':18,'test_traffic_opt_out':True}
    target=out/'plan.json'
    if target.exists():assert json.loads(target.read_text())==plan,'Never overwrite a different frozen plan'
    else:target.write_text(json.dumps(plan,indent=2)+'\n',encoding='utf-8')
    (out/'plan.sha256').write_text(sha(target.read_bytes())+'\n')
    (out/'source-receipts.json').write_text(json.dumps(source_receipts,indent=2)+'\n')
    with tarfile.open(out/'executor.tar.gz','w:gz') as archive:archive.add(stage,arcname='.')
    print(json.dumps({'plan_sha256':sha(target.read_bytes()),'source_files':len(jobs),'planned_trials':18,'archive_bytes':(out/'executor.tar.gz').stat().st_size}))
if __name__=='__main__':main()
