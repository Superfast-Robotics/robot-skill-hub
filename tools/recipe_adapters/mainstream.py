"""MIT: bounded simulation controllers; no physical I/O or model training."""

def mainstream_backend(root, data, spec):
    import importlib.metadata
    import numpy as np
    for package in spec['packages']:
        name,version=package.split('==',1)
        if importlib.metadata.version(name).split('+')[0]!=version:raise ContractError('Pinned package version differs: '+name)
    os.environ.setdefault('MUJOCO_GL','egl')
    os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
    os.environ['WANDB_MODE']='disabled'
    backend=spec['backend'];seed=data['seed']
    np.random.seed(seed)
    if backend=='menagerie':
        import mujoco
        model=mujoco.MjModel.from_xml_path(str(root/spec['model_path']))
        state=mujoco.MjData(model)
        if model.nkey:mujoco.mj_resetDataKeyframe(model,state,0)
        mujoco.mj_forward(model,state)
        indices=[model.actuator(name).id for name in spec['actuator_names']]
        joints=[int(model.actuator_trnid[a,0]) for a in indices]
        qaddrs=[int(model.jnt_qposadr[j]) for j in joints]
        for a,q in zip(indices,qaddrs):state.ctrl[a]=state.qpos[q]
        for _ in range(500):mujoco.mj_step(model,state)
        start=state.qpos[qaddrs].copy();target=start+data['joint_offset_rad']
        for k,(a,j) in enumerate(zip(indices,joints)):
            if model.jnt_limited[j]:target[k]=np.clip(target[k],model.jnt_range[j,0]+.02,model.jnt_range[j,1]-.02)
            if model.actuator_ctrllimited[a]:target[k]=np.clip(target[k],*model.actuator_ctrlrange[a])
            state.ctrl[a]=target[k]
        for _ in range(2500):mujoco.mj_step(model,state)
        final=state.qpos[qaddrs];error=float(np.max(np.abs(final-target)))
        moved=float(np.max(np.abs(final-start)));demand=float(np.max(np.abs(target-start)))
        return {'joint_positions_rad':final.tolist(),'target_joint_positions_rad':target.tolist(),'max_error_rad':error,'movement_rad':moved}, {
            'nontrivial_target':demand>=.03,'joint_goal_reached':error<.035,
            'actual_motion':moved>=.02,'finite_state':bool(np.isfinite(state.qpos).all() and np.isfinite(state.qvel).all())}
    if backend=='robosuite':
        sys.path.insert(0,str(root))
        import robosuite as suite
        env=suite.make('Lift',robots=spec['robot'],has_renderer=False,has_offscreen_renderer=False,use_camera_obs=False,
                       control_freq=20,horizon=500,ignore_done=True,initialization_noise=None)
        try:
            obs=env.reset();start=obs['robot0_eef_pos'].copy();initial_cube=obs['cube_pos'].copy()
            def drive(target,grip,steps):
                nonlocal obs
                for _ in range(steps):
                    action=np.zeros(env.action_dim);action[:3]=np.clip((target-obs['robot0_eef_pos'])*10,-1,1);action[-1]=grip
                    obs,_,_,_=env.step(action)
            if spec['operation']=='reach':
                target=start+np.asarray(data['offset_xyz_m']);drive(target,-1,150)
                error=float(np.linalg.norm(obs['robot0_eef_pos']-target))
                return {'final_xyz_m':obs['robot0_eef_pos'].tolist(),'target_xyz_m':target.tolist(),'error_m':error}, {
                    'nontrivial_target':bool(np.linalg.norm(target-start)>.025),'target_reached':error<.015,
                    'actual_motion':bool(np.linalg.norm(obs['robot0_eef_pos']-start)>.02),'finite_state':bool(np.isfinite(env.sim.data.qpos).all())}
            drive(initial_cube+np.array([0,0,.12]),-1,80)
            drive(initial_cube+np.array([0,0,.005]),-1,100)
            drive(initial_cube+np.array([0,0,.005]),1,50)
            drive(initial_cube+np.array([0,0,data['lift_height_m']]),1,120)
            height=float(obs['cube_pos'][2]-initial_cube[2]);success=bool(env._check_success())
            return {'cube_lift_m':height,'cube_xyz_m':obs['cube_pos'].tolist(),'environment_success':success}, {
                'environment_goal':success,'object_lifted':height>.07,'finite_state':bool(np.isfinite(env.sim.data.qpos).all())}
        finally:env.close()
    if backend=='gymrobotics':
        sys.path.insert(0,str(root))
        import gymnasium as gym,gymnasium_robotics
        gym.register_envs(gymnasium_robotics)
        env=gym.make(spec['env_id'],max_episode_steps=1000)
        try:
            obs,info=env.reset(seed=seed);steps=0
            def move(target,grip,limit):
                nonlocal obs,info,steps
                for _ in range(limit):
                    action=np.r_[np.clip((target-obs['observation'][:3])*6,-1,1),grip]
                    obs,_,_,_,info=env.step(action);steps+=1
            if spec['operation']=='reach':move(obs['desired_goal'],0,100)
            elif spec['operation']=='pick_place':
                obj=obs['observation'][3:6].copy();goal=obs['desired_goal'].copy()
                move(obj+np.array([0,0,.12]),1,35);move(obj+np.array([0,0,.005]),1,30)
                move(obj+np.array([0,0,.005]),-1,30);move(obj+np.array([0,0,.2]),-1,35)
                move(goal+np.array([0,0,.08]),-1,40);move(goal,-1,35);move(goal,1,30)
            elif spec['operation']=='push':
                obj=obs['observation'][3:6].copy();goal=obs['desired_goal'].copy()
                direction=goal[:2]-obj[:2];direction/=max(np.linalg.norm(direction),1e-6)
                behind=obj-np.r_[direction*.08,0]
                move(behind+np.array([0,0,.12]),1,35);move(behind,1,35)
                for _ in range(160):
                    obj=obs['observation'][3:6].copy();delta=goal[:2]-obj[:2]
                    if np.linalg.norm(delta)<.025:break
                    aim=goal.copy();aim[2]=obj[2];move(aim,1,1)
            else:
                from collections import deque
                maze=env.unwrapped.maze;grid=maze.maze_map
                begin=tuple(maze.cell_xy_to_rowcol(obs['achieved_goal']));goalcell=tuple(maze.cell_xy_to_rowcol(obs['desired_goal']))
                queue=deque([begin]);parents={begin:None}
                while queue:
                    cell=queue.popleft()
                    if cell==goalcell:break
                    for dx,dy in [(0,1),(0,-1),(1,0),(-1,0)]:
                        nxt=(cell[0]+dx,cell[1]+dy)
                        if 0<=nxt[0]<len(grid) and 0<=nxt[1]<len(grid[0]) and grid[nxt[0]][nxt[1]]!=1 and nxt not in parents:
                            parents[nxt]=cell;queue.append(nxt)
                if goalcell not in parents:raise ContractError('Goal unreachable in declared maze')
                route=[];cell=goalcell
                while cell!=begin:route.append(cell);cell=parents[cell]
                targets=[maze.cell_rowcol_to_xy(c) for c in reversed(route)]+[obs['desired_goal'].copy()]
                for target in targets:
                    for _ in range(160):
                        error=target-obs['achieved_goal']
                        if np.linalg.norm(error)<.12:break
                        velocity=obs['observation'][2:4]
                        action=np.clip(error*10-velocity*3,-1,1)
                        obs,_,_,_,info=env.step(action);steps+=1
                        if steps>=950:break
                    if steps>=950:break
            error=float(np.linalg.norm(obs['achieved_goal']-obs['desired_goal']))
            success=bool(info.get('is_success',info.get('success',False)))
            return {'achieved_goal':obs['achieved_goal'].tolist(),'desired_goal':obs['desired_goal'].tolist(),'error_m':error,'steps':steps,'environment_success':success}, {
                'environment_goal':success,'finite_state':bool(np.isfinite(obs['observation']).all()),'bounded_steps':steps<=950}
        finally:env.close()
    if backend=='lerobot':
        sys.path.insert(0,str(root/'src'))
        os.environ['SDL_VIDEODRIVER']='dummy'
        import torch,gymnasium as gym,gym_pusht
        from huggingface_hub import snapshot_download
        from lerobot.policies.diffusion.modeling_diffusion import DiffusionPolicy
        torch.manual_seed(seed);torch.cuda.manual_seed_all(seed);torch.set_num_threads(2)
        if not torch.cuda.is_available():raise ContractError('This validated policy environment requires CUDA')
        folder=snapshot_download(spec['policy_repo'],revision=spec['policy_revision'],allow_patterns=['config.json','model.safetensors','README.md'])
        for name,expected in spec['policy_hashes'].items():
            if hashlib.sha256((Path(folder)/name).read_bytes()).hexdigest()!=expected:raise ContractError('Policy artifact checksum changed')
        policy=DiffusionPolicy.from_pretrained(folder).to('cuda').eval();policy.reset()
        env=gym.make('gym_pusht/PushT-v0',obs_type='pixels_agent_pos',render_mode='rgb_array',max_episode_steps=300)
        try:
            obs,info=env.reset(seed=seed);maximum=0.;success=False
            for step in range(300):
                batch={'observation.image':torch.from_numpy(obs['pixels']).permute(2,0,1).float().div(255).unsqueeze(0).to('cuda'),
                       'observation.state':torch.from_numpy(obs['agent_pos']).float().unsqueeze(0).to('cuda')}
                with torch.inference_mode():action=policy.select_action(batch)[0].cpu().numpy()
                obs,reward,terminated,truncated,info=env.step(action);maximum=max(maximum,float(info['coverage']))
                success=success or bool(info.get('is_success',False)) or terminated
                if terminated or truncated:break
            return {'maximum_coverage':maximum,'steps':step+1,'environment_success':success,'cuda_inference':True}, {
                'environment_goal':success,'coverage_threshold':maximum>=.95,'cuda_inference':True}
        finally:env.close()
    raise ContractError('Unsupported pinned simulation backend')
