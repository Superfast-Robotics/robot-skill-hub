"""MIT: finite simulation starting policies; simulator state is privileged input."""

def seed_backend(root, data, spec):
    import importlib.metadata
    import numpy as np
    for pin in spec['packages']:
        name,version=pin.split('==')
        if importlib.metadata.version(name).split('+')[0]!=version:raise ContractError('Pinned package version differs: '+name)
    os.environ.setdefault('MUJOCO_GL','egl')
    sys.path.insert(0,str(root))
    if spec['backend']=='robosuite':
        import robosuite as suite
        env=suite.make('Stack' if spec['operation']=='stack' else 'PickPlaceCan',robots=spec['robot'],has_renderer=False,has_offscreen_renderer=False,use_camera_obs=False,control_freq=20,horizon=800,ignore_done=True,initialization_noise=None)
        try:
            np.random.seed(data['seed']);obs=env.reset();steps=0
            def drive(target,grip,limit):
                nonlocal obs,steps
                for _ in range(limit):
                    a=np.zeros(env.action_dim);a[:3]=np.clip((target-obs['robot0_eef_pos'])*10,-1,1);a[-1]=grip
                    obs,_,_,_=env.step(a);steps+=1
            if spec['operation']=='stack':
                object_key='cubeA_pos';target=obs['cubeB_pos'].copy()+np.array([0,0,.045])
            else:
                object_key='Can_pos';target=np.asarray(env.target_bin_placements[3]).copy()+np.array([0,0,.06])
            initial=obs[object_key].copy()
            drive(initial+np.array([0,0,.15]),-1,80);drive(initial+np.array([0,0,.005]),-1,100)
            drive(initial+np.array([0,0,.005]),1,50);drive(initial+np.array([0,0,.22]),1,90)
            drive(target+np.array([0,0,.17]),1,100);drive(target,1,90)
            drive(target,-1,50);drive(target+np.array([0,0,.18]),-1,70)
            final=obs[object_key].copy();error=float(np.linalg.norm(final-target));success=bool(env._check_success())
            return {'object_xyz_m':final.tolist(),'target_xyz_m':target.tolist(),'error_m':error,'steps':steps,'environment_success':success}, {
                'native_environment_goal':success,'target_proximity':error<.08,'object_moved':bool(np.linalg.norm(final-initial)>.025),'finite_state':bool(np.isfinite(env.sim.data.qpos).all())}
        finally:env.close()
    if spec['backend']=='pandagym':
        import gymnasium as gym,panda_gym
        env=gym.make(spec['env_id'],render_mode=None,max_episode_steps=1500)
        try:
            obs,info=env.reset(seed=data['seed']);steps=0
            def move(target,grip,limit):
                nonlocal obs,info,steps
                for _ in range(limit):
                    action=np.clip((target-obs['observation'][:3])*12,-1,1)
                    if env.action_space.shape[0]==4:action=np.r_[action,grip]
                    obs,_,_,_,info=env.step(action);steps+=1
            def transfer(body,target,release=True):
                obj=np.asarray(env.unwrapped.sim.get_base_position(body)).copy()
                move(obj+np.array([0,0,.13]),1,35);move(obj+np.array([0,0,.003]),1,35)
                move(obj+np.array([0,0,.003]),-1,25);move(obj+np.array([0,0,.18]),-1,40)
                move(target+np.array([0,0,.16]),-1,45);move(target,-1,45)
                if release:
                    move(target,1,25);move(target+np.array([0,0,.15]),1,30)
                else:move(target,-1,40)
            goal=obs['desired_goal'].copy()
            if spec['operation']=='reach':move(goal,0,120)
            elif spec['operation']=='pick_place':transfer('object',goal,release=goal[2]<.06)
            elif spec['operation']=='stack':
                transfer('object1',goal[:3]);transfer('object2',goal[3:])
            else:
                obj=np.asarray(env.unwrapped.sim.get_base_position('object')).copy()
                direction=goal[:2]-obj[:2];direction/=max(np.linalg.norm(direction),1e-8)
                behind=obj-np.r_[direction*.08,0]
                move(behind+np.array([0,0,.12]),1,35);move(behind,1,35)
                for _ in range(220):
                    obj=np.asarray(env.unwrapped.sim.get_base_position('object'))
                    if np.linalg.norm(goal[:2]-obj[:2])<.025:break
                    target=goal.copy();target[2]=obj[2];move(target,1,1)
                move(obs['observation'][:3]+np.array([0,0,.12]),1,30)
            error=float(np.linalg.norm(obs['achieved_goal']-goal))
            success=bool(info['is_success']);tolerance=.04 if spec['operation']!='stack' else .06
            return {'achieved_goal':obs['achieved_goal'].tolist(),'desired_goal':goal.tolist(),'error_m':error,'steps':steps,'environment_success':success}, {
                'native_environment_goal':success,'strict_goal_error':error<tolerance,'finite_state':bool(np.isfinite(obs['observation']).all())}
        finally:env.close()
    if spec['backend']=='dmcontrol':
        from dm_control import suite
        from scipy.linalg import solve_discrete_are
        env=suite.load(spec['domain'],spec['task'],task_kwargs={'random':data['seed']})
        try:
            env.reset();p=env.physics;domain=spec['domain'];target=None;gain=None
            if domain=='reacher':
                # Solve kinematics in a separate physics copy; active state is never set.
                from scipy.optimize import least_squares
                probe=p.copy(share_model=True)
                def residual(q):
                    with probe.reset_context():probe.data.qpos[:]=q
                    return probe.finger_to_target()
                solutions=[least_squares(residual,q,max_nfev=150) for q in [p.data.qpos.copy(),np.zeros(2),np.array([1.,-2.]),np.array([-1.,2.])]]
                target=min(solutions,key=lambda s:np.linalg.norm(s.fun)).x
            elif domain=='cartpole':
                import mujoco
                probe=p.copy(share_model=True)
                with probe.reset_context():probe.data.qpos[:]=0;probe.data.qvel[:]=0
                n=2*probe.model.nv;A=np.zeros((n,n));B=np.zeros((n,probe.model.nu))
                mujoco.mjd_transitionFD(probe.model.ptr,probe.data.ptr,1e-6,True,A,B,None,None)
                Q=np.diag([2.,25.,1.,2.]);R=np.eye(1)*.01
                P=solve_discrete_are(A,B,Q,R);gain=np.linalg.solve(R+B.T@P@B,B.T@P@A)
            rewards=[];actions=[]
            for step in range(1000):
                if domain=='reacher':
                    error=(target-p.data.qpos+np.pi)%(2*np.pi)-np.pi
                    action=error*8-p.data.qvel*1.5
                elif domain=='point_mass':
                    error=p.named.data.geom_xpos['target',:2]-p.named.data.geom_xpos['pointmass',:2]
                    force=error*20-p.data.qvel*5
                    # Hard task randomizes the actuator directions. Invert the declared gears.
                    gear=np.asarray(p.model.actuator_gear)[:,:2].T
                    action=np.linalg.pinv(gear)@force
                elif domain=='cartpole':
                    q=p.data.qpos.copy();q[1]=(q[1]+np.pi)%(2*np.pi)-np.pi
                    action=-(gain@np.r_[q,p.data.qvel])
                elif domain=='pendulum':
                    theta=float(p.data.qpos[0]);velocity=float(p.data.qvel[0]);upright=np.cos(theta)
                    if upright>.8:action=np.array([-4*((theta+np.pi)%(2*np.pi)-np.pi)-.8*velocity])
                    else:
                        energy=.5*.025*velocity**2+.981*np.cos(theta)
                        direction=velocity if abs(velocity)>.05 else 1.
                        action=np.array([2.5*(.981-energy)*np.sign(direction)])
                elif domain=='finger':action=np.ones(env.action_spec().shape)*.8
                else:
                    # Cup tracks ball horizontally and damps its own velocity.
                    observation=env.task.get_observation(p);position=observation['position'];velocity=observation['velocity']
                    action=np.array([(position[2]-position[0])*20-velocity[0]*4, -velocity[1]*4])
                action=np.clip(action,env.action_spec().minimum,env.action_spec().maximum)
                ts=env.step(action);rewards.append(float(ts.reward));actions.append(float(np.linalg.norm(action)))
                if ts.last():break
            window=rewards[-100:];mean=float(np.mean(window));threshold=.6 if domain=='finger' else .9
            return {'final_window_mean_reward':mean,'final_reward':rewards[-1],'minimum_window_reward':min(window),'reward_window':window,'steps':len(rewards),'control_effort':float(np.sum(actions))}, {
                'sustained_native_reward':mean>=threshold,'nonzero_control':max(actions)>1e-5,
                'finite_state':bool(np.isfinite(p.data.qpos).all() and np.isfinite(p.data.qvel).all())}
        finally:env.close()
    raise ContractError('Unknown simulation backend')

def mainstream_backend(root,data,spec):
    # Bullet emits native diagnostics through fd 1, beyond Python redirect_stdout.
    # Preserve the single-object stdout protocol for ordinary callers as well.
    import ctypes
    saved=os.dup(1)
    try:
        os.dup2(2,1)
        return seed_backend(root,data,spec)
    finally:
        ctypes.CDLL(None).fflush(None)
        os.dup2(saved,1);os.close(saved)
