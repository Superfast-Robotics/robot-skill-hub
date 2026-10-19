"""Bounded adapters calling original pinned PythonRobotics functions (MIT).
Upstream algorithms remain in their own immutable checkout; no main/GUI runs.
"""


def segment_distance(point, a, b):
    dx, dy = b[0]-a[0], b[1]-a[1]
    t = max(0., min(1., ((point[0]-a[0])*dx+(point[1]-a[1])*dy)/(dx*dx+dy*dy))) if dx or dy else 0.
    return math.hypot(point[0]-a[0]-t*dx, point[1]-a[1]-t*dy)


def path_length(path):
    return sum(math.dist(a,b) for a,b in zip(path,path[1:]))


def path_checks(path, start, goal, obstacles=(), radius=0., tolerance=1e-6):
    return {'nonempty':len(path)>1,
        'start_reached':bool(path) and math.dist(path[0][:2],start[:2])<=tolerance,
        'goal_reached':bool(path) and math.dist(path[-1][:2],goal[:2])<=tolerance,
        'collision_free_segments':all(segment_distance(o,a,b)+1e-8 >= radius+(o[2] if len(o)>2 else 0.)
            for a,b in zip(path,path[1:]) for o in obstacles)}


def pythonrobotics_backend(root, d, spec):
    import numpy as np
    np.random.seed(d.get('seed',0))
    m=load_upstream(root,spec['source_path'])
    op=spec['operation']
    if op=='grid':
        lo,hi=d['bounds']
        if lo>=hi or hi-lo>40: raise ContractError('bounds must increase and span at most 40 m')
        boundary=[[x,y] for x in range(lo,hi+1) for y in (lo,hi)] + [[x,y] for y in range(lo,hi+1) for x in (lo,hi)]
        obs=boundary+d['obstacles']
        if any(not lo<v<hi for p in (d['start'],d['goal']) for v in p): raise ContractError('Start/goal outside open bounds')
        if any(math.dist(p,o)<=d['robot_radius'] for p in (d['start'],d['goal']) for o in obs): raise ContractError('Start/goal in collision')
        planner=getattr(m,spec['class'])([p[0] for p in obs],[p[1] for p in obs],1.,d['robot_radius'])
        x,y=planner.planning(*d['start'],*d['goal'])
        path=list(map(list,zip(x,y)))
        if path and math.dist(path[-1],d['start'])<math.dist(path[0],d['start']): path.reverse()
        return {'path_xy':path,'length_m':path_length(path)},path_checks(path,d['start'],d['goal'],obs,d['robot_radius'])
    if op in ('rrt','rrt_star','rrt_sobol'):
        if d['bounds'][0]>=d['bounds'][1]: raise ContractError('Bounds must increase')
        if any(o[2]<=0 for o in d['obstacles']): raise ContractError('Obstacle radii must be positive')
        cls=getattr(m,{'rrt':'RRT','rrt_star':'RRTStar','rrt_sobol':'RRTSobol'}[op])
        planner=cls(start=d['start'],goal=d['goal'],obstacle_list=d['obstacles'],rand_area=d['bounds'],
            expand_dis=2.,path_resolution=.1,max_iter=1500,robot_radius=d['robot_radius'])
        path=planner.planning(animation=False) or []
        if path and math.dist(path[-1],d['start'])<math.dist(path[0],d['start']): path.reverse()
        return {'path_xy':path,'length_m':path_length(path)},path_checks(path,d['start'],d['goal'],d['obstacles'],d['robot_radius'])
    if op=='prm':
        lo,hi=d['bounds']
        if lo>=hi or hi-lo>40: raise ContractError('Invalid bounds')
        obs=d['obstacles']+[[x,y] for x in range(lo,hi+1) for y in (lo,hi)]+[[x,y] for y in range(lo,hi+1) for x in (lo,hi)]
        m.N_SAMPLE=300
        x,y=m.prm_planning(*d['start'],*d['goal'],[p[0] for p in obs],[p[1] for p in obs],d['robot_radius'],rng=np.random.default_rng(d['seed']))
        path=list(map(list,zip(x,y)))
        if path and math.dist(path[-1],d['start'])<math.dist(path[0],d['start']): path.reverse()
        return {'path_xy':path,'length_m':path_length(path)},path_checks(path,d['start'],d['goal'],obs,d['robot_radius'])
    if op in ('dubins','reeds_shepp'):
        fn=m.plan_dubins_path if op=='dubins' else m.reeds_shepp_path_planning
        x,y,yaw,modes,lengths=fn(*d['start'],*d['goal'],d['curvature'],step_size=d['step_size'])
        path=list(map(list,zip(x,y))) if x is not None else []
        checks=path_checks(path,d['start'],d['goal'],tolerance=1e-5)
        checks['goal_heading']=bool(path) and abs(math.atan2(math.sin(yaw[-1]-d['goal'][2]),math.cos(yaw[-1]-d['goal'][2])))<1e-5
        return {'path_xy':path,'yaw_rad':[] if yaw is None else list(yaw),'length_m':path_length(path)},checks
    if op in ('cubic','bspline','bezier','catmull'):
        pts=np.array(d['waypoints'])
        if any(math.dist(a,b)<1e-6 for a,b in zip(pts,pts[1:])): raise ContractError('Adjacent waypoints must differ')
        if op=='cubic':
            spline=m.CubicSpline2D(pts[:,0],pts[:,1])
            samples=np.linspace(0,spline.s[-1]-1e-10,d['samples'])
            path=[spline.calc_position(float(t)) for t in samples]
        elif op=='bspline':
            x,y,*_=m.interpolate_b_spline_path(pts[:,0],pts[:,1],d['samples'],degree=min(3,len(pts)-1))
            path=list(zip(x,y))
        elif op=='bezier': path=m.calc_bezier_path(pts,n_points=d['samples'])
        else:
            x,y=m.catmull_rom_spline(pts,d['samples']); path=list(zip(x,y))
        path=np.asarray(path).tolist()
        return {'path_xy':path,'length_m':path_length(path)},path_checks(path,d['waypoints'][0],d['waypoints'][-1],tolerance=1e-6)
    if op=='quintic':
        p=m.QuinticPolynomial(*d['start'],*d['goal'],d['duration'])
        t=np.linspace(0,d['duration'],d['samples'])
        position=[p.calc_point(v) for v in t]; velocity=[p.calc_first_derivative(v) for v in t]; acceleration=[p.calc_second_derivative(v) for v in t]
        return {'time_s':t,'position_m':position,'velocity_m_s':velocity,'acceleration_m_s2':acceleration}, {
            'initial_state':max(abs(a[0]-b) for a,b in zip([position,velocity,acceleration],d['start']))<1e-7,
            'terminal_state':max(abs(a[-1]-b) for a,b in zip([position,velocity,acceleration],d['goal']))<1e-7}
    if op in ('pure_pursuit','stanley'):
        path=np.asarray(d['path_xy']); state=m.State(*d['state'])
        if op=='pure_pursuit':
            course=m.TargetCourse(path[:,0],path[:,1]); steer,index=m.pure_pursuit_steer_control(state,course,0)
        else:
            yaw=np.arctan2(np.gradient(path[:,1]),np.gradient(path[:,0]))
            steer,index=m.stanley_control(state,path[:,0],path[:,1],yaw,0)
        return {'steering_rad':float(steer),'target_index':int(index)}, {'finite_command':bool(np.isfinite(steer)),'target_in_path':0<=int(index)<len(path)}
    if op=='dwa':
        cfg=m.Config(); cfg.robot_radius=d['robot_radius']; cfg.robot_type=m.RobotType.circle
        control,trajectory=m.dwa_control(np.asarray(d['state'],dtype=float),cfg,np.array(d['goal']),np.array(d['obstacles']))
        return {'control_v_yawrate':control,'trajectory_xy_yaw_v_w':trajectory}, {
            'velocity_bounds':bool(cfg.min_speed<=control[0]<=cfg.max_speed and abs(control[1])<=cfg.max_yaw_rate+1e-8),
            'collision_free_samples':all(math.dist(p[:2],o)>=cfg.robot_radius-1e-8 for p in trajectory for o in d['obstacles'])}
    if op in ('ekf','ekf_velocity','ukf'):
        dimension=5 if op=='ekf_velocity' else 4
        x=np.array(d['state']).reshape(dimension,1); cov=np.array(d['covariance']); z=np.array(d['measurement_xy']).reshape(2,1); u=np.array(d['control_v_yawrate']).reshape(2,1)
        if not np.allclose(cov,cov.T,atol=1e-10) or np.linalg.eigvalsh(cov).min()<=0: raise ContractError('Covariance must be symmetric positive definite')
        if op=='ukf': state,covariance=m.ukf_estimation(x,cov,z,u,*m.setup_ukf(4))
        else: state,covariance=m.ekf_estimation(x,cov,z,u)
        return {'state_xy_yaw_v_scale' if op=='ekf_velocity' else 'state_xy_yaw_v':state.reshape(-1),'covariance':covariance}, {
            'finite_state':bool(np.isfinite(state).all()), 'symmetric_covariance':bool(np.allclose(covariance,covariance.T,atol=1e-8)),
            'positive_semidefinite_covariance':bool(np.linalg.eigvalsh(covariance).min()>=-1e-8)}
    if op in ('fk','ik'):
        lengths=np.array(d['link_lengths']); angles=np.array(d['joint_angles'])
        if len(lengths)!=len(angles) or any(lengths<=0): raise ContractError('Positive link lengths must match joint count')
        m.N_LINKS=len(lengths)
        if op=='ik':
            if np.linalg.norm(d['target_xy'])>sum(lengths): raise ContractError('Target outside reach')
            m.N_ITERATIONS=1000; angles,solved=m.inverse_kinematics(lengths,angles,np.array(d['target_xy']))
        else: solved=True
        endpoint=m.forward_kinematics(lengths,angles)
        independent=np.array([sum(lengths*np.cos(np.cumsum(angles))),sum(lengths*np.sin(np.cumsum(angles)))])
        checks={'forward_kinematics_agrees':bool(np.linalg.norm(endpoint-independent)<1e-8)}
        if op=='ik': checks['target_residual_below_0_1_m']=bool(solved and np.linalg.norm(endpoint-np.array(d['target_xy']))<.1)
        return {'joint_angles_rad':angles,'end_effector_xy_m':endpoint},checks
    if op=='lqr':
        A,B=m.get_model_matrix(); K,P,eigs=m.dlqr(A,B,np.diag(d['state_cost_diagonal']),np.array([[d['force_cost']]]))
        force=-K@np.array(d['state']).reshape(4,1)
        return {'force_n':float(force.item()),'gain':K.tolist()[0],'closed_loop_spectral_radius':float(max(abs(eigs)))}, {'stable_discrete_linear_model':bool(max(abs(eigs))<1.)}
    if op=='potential':
        if not d['obstacles']: raise ContractError('Potential-field source requires obstacle points')
        x,y=m.potential_field_planning(*d['start'],*d['goal'],[p[0] for p in d['obstacles']],[p[1] for p in d['obstacles']],.5,d['robot_radius'])
        path=list(map(list,zip(x,y)))
        return {'path_xy':path,'length_m':path_length(path)},path_checks(path,d['start'],d['goal'],d['obstacles'],d['robot_radius'],tolerance=.5)
    if op=='smoothing':
        path=m.path_smoothing(d['path_xy'],100,d['obstacles'],robot_radius=d['robot_radius'])
        checks=path_checks(path,d['path_xy'][0],d['path_xy'][-1],d['obstacles'],d['robot_radius'])
        checks['not_longer']=path_length(path)<=path_length(d['path_xy'])+1e-8
        return {'path_xy':path,'length_m':path_length(path)},checks
    raise ContractError('Unknown reviewed operation')
