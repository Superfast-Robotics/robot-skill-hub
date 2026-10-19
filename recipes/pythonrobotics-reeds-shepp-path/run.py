# Generated from tools/recipe_adapters and catalog/executable-conversions.json.
# Hub adapter: MIT. Adapted upstream example retains its original license and authors.
"""Source template for standalone, bounded JSON recipe adapters (MIT, Hub authors).

The generator embeds this template and a reviewed backend in each published
recipe. Importing this template does not import or execute upstream source.
"""
import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import random
import sys


class ContractError(ValueError):
    pass


def validate_data(value, schema, path='$'):
    """Supported, published JSON Schema subset; bool is never a number."""
    kind = schema.get('type')
    checks = {'object': lambda: isinstance(value, dict), 'array': lambda: isinstance(value, list),
              'number': lambda: type(value) in (int, float) and math.isfinite(value),
              'integer': lambda: type(value) is int, 'string': lambda: isinstance(value, str),
              'boolean': lambda: isinstance(value, bool), 'null': lambda: value is None}
    if kind and (kind not in checks or not checks[kind]()):
        raise ContractError(path + ': expected ' + str(kind))
    if 'enum' in schema and value not in schema['enum']:
        raise ContractError(path + ': unsupported value')
    if type(value) in (int, float):
        if not math.isfinite(value) or value < schema.get('minimum', value) or value > schema.get('maximum', value):
            raise ContractError(path + ': outside numeric bounds')
    if isinstance(value, dict):
        if len(value) > 32: raise ContractError(path + ': too many keys')
        for name in schema.get('required', []):
            if name not in value: raise ContractError(path + '.' + name + ': required')
        props = schema.get('properties', {})
        for name, item in value.items():
            if name not in props and schema.get('additionalProperties') is False:
                raise ContractError(path + '.' + name + ': unknown field')
            validate_data(item, props.get(name, {}), path + '.' + name)
    elif isinstance(value, list):
        if not schema.get('minItems', 0) <= len(value) <= schema.get('maxItems', 4096):
            raise ContractError(path + ': invalid array length')
        for i, item in enumerate(value): validate_data(item, schema.get('items', {}), path + '[' + str(i) + ']')
    elif isinstance(value, str) and len(value) > schema.get('maxLength', 4096):
        raise ContractError(path + ': string too long')


def verify_source(root, spec):
    root = Path(root).resolve()
    for name, expected in spec['source_hashes'].items():
        target = root / name
        if target.is_symlink() or not target.resolve().is_relative_to(root) or not target.is_file():
            raise ContractError('Pinned source missing or outside source root: ' + name)
        if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
            raise ContractError('Pinned source checksum changed: ' + name)
    return root


def load_upstream(root, relative):
    """Only a generator-pinned path is accepted; never a path from task input."""
    target = root / relative
    for directory in [root, root / 'PathPlanning', target.parent]:
        sys.path.insert(0, str(directory))
    module_spec = importlib.util.spec_from_file_location('rsh_upstream', target)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    if hasattr(module, 'show_animation'): module.show_animation = False
    return module


def clean_json(value):
    if hasattr(value, 'tolist'): return clean_json(value.tolist())
    if isinstance(value, dict): return {k: clean_json(v) for k,v in value.items()}
    if isinstance(value, (tuple, list)): return [clean_json(v) for v in value]
    if hasattr(value, 'item'): return clean_json(value.item())
    if isinstance(value, float) and not math.isfinite(value): raise ContractError('Non-finite output')
    return value


def adapter_main(spec, backend):
    parser = argparse.ArgumentParser(description=spec['name'])
    parser.add_argument('--source-dir')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--input', type=Path, help='UTF-8 JSON file; no code or paths inside task input')
    group.add_argument('--input-json', help='Inline JSON task input')
    group.add_argument('--example', action='store_true', help='Run the declared example input')
    group.add_argument('--describe', action='store_true', help='Read the contract without importing upstream code')
    args = parser.parse_args()
    try:
        if args.describe:
            print(json.dumps({'skill_id': spec['id'], 'interface': spec['interface'], 'example_input': spec['example']}, allow_nan=False))
            return 0
        if args.input:
            with args.input.open('rb') as stream: raw=stream.read(65537)
        else: raw=args.input_json.encode() if args.input_json else None
        if raw is not None and len(raw) > 65536: raise ContractError('Input exceeds 64 KiB')
        data = json.loads(raw) if raw is not None else spec['example']
        validate_data(data, spec['interface']['input_schema'])
        if not args.source_dir: raise ContractError('--source-dir is required for execution')
        root = verify_source(args.source_dir, spec)
        os.environ['MPLBACKEND'] = 'Agg'
        os.environ.setdefault('OMP_NUM_THREADS', '1')
        random.seed(data.get('seed', 0))
        # Upstream diagnostic prints do not contaminate the machine response.
        with contextlib.redirect_stdout(sys.stderr):
            outputs, checks = backend(root, data, spec)
        outputs, checks = clean_json(outputs), clean_json(checks)
        validate_data(outputs, spec['interface']['output_schema'])
        if not checks or not all(type(v) is bool for v in checks.values()): raise ContractError('Invalid postcondition report')
        ok = all(checks.values())
        print(json.dumps({'schema_version':'1','skill_id':spec['id'],'status':'task_complete' if ok else 'task_failed',
            'success':ok,'outputs':outputs,'checks':checks,'execution_domain':spec['interface']['execution_domain'],
            'source_commit':spec['source_commit'],'interface_version':'1','hardware_execution':False}, allow_nan=False, separators=(',',':')))
        return 0 if ok else 1
    except (ContractError, ValueError, OSError, ImportError) as error:
        print(json.dumps({'schema_version':'1','skill_id':spec['id'],'status':'failed','success':False,
            'reason_code':'invalid_input_or_environment','message':str(error),'hardware_execution':False}, allow_nan=False))
        return 2
    except Exception as error:
        print(json.dumps({'schema_version':'1','skill_id':spec['id'],'status':'failed','success':False,
            'reason_code':'execution_failed','message':str(error)[:1000],'hardware_execution':False}, allow_nan=False))
        return 1


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

SPEC = json.loads('{"id":"pythonrobotics-reeds-shepp-path","name":"Reeds-Shepp free-space pose path","operation":"reeds_shepp","source_path":"PathPlanning/ReedsSheppPath/reeds_shepp_path_planning.py","source_commit":"cdd0cc888802b584c2d654ca85e3c5460973487d","source_hashes":{"ArmNavigation/n_joint_arm_to_point_control/NLinkArm.py":"0050d72932952f05992c0195bdcc57cfb9dfaa13be81daf9e22c6344a8e5735d","ArmNavigation/n_joint_arm_to_point_control/n_joint_arm_to_point_control.py":"7ef0e52b7f949b84d82d5ea2824cd3dbc0f60e8e21dd8a9499b407231a310b1d","InvertedPendulum/inverted_pendulum_lqr_control.py":"8af1d6540a40866fdb35822e3eea9042a58d43c4df28d4ebd7beec22593d1b55","LICENSE":"ca6f10832a25c1cd07fa62872458ca336a6ea83ee2f2236216086bd7a5bbf264","Localization/extended_kalman_filter/ekf_with_velocity_correction.py":"58bb755f0f917b07d20dace4750aca16312c19e5f897e7e7d376732acd5e4cfe","Localization/extended_kalman_filter/extended_kalman_filter.py":"fa9bb52dbb63e6e959ba4e7bcf20cbe8d6ce69e88453ad0f605a21fc6979a28e","Localization/unscented_kalman_filter/unscented_kalman_filter.py":"ec89f8bd08c45d1dca15f41a7313dfa402679e73ad7290293ab7ea2d2fcce94e","PathPlanning/AStar/a_star.py":"387293061a8509557bb80a02a0f279b0b2b4629c0189db661a93fee5d9e0b74a","PathPlanning/BSplinePath/bspline_path.py":"5d45a5400b684b59ef0e3ed1f780f9ba1ad069e1fde3879abf2f21307b77aa94","PathPlanning/BezierPath/bezier_path.py":"4f3bb51aba78a47ab4665b7ccfbbd70acf75607bbdd5f1726a34962ecbc46f5d","PathPlanning/BidirectionalAStar/bidirectional_a_star.py":"6870b9bf1666b8d31ba0ffdfe92c9a715dcfdb3a40398e551352a3180da9dc01","PathPlanning/BidirectionalBreadthFirstSearch/bidirectional_breadth_first_search.py":"c0536f0296ddefd700b9d754e936949087d822d65901da462971ec2d82a9183c","PathPlanning/BreadthFirstSearch/breadth_first_search.py":"960bfbc9e15b81df08d78c8266e8467378f307b5fec9a58b8de2c4bb8feab069","PathPlanning/Catmull_RomSplinePath/catmull_rom_spline_path.py":"14d5f7046302cac828ebb9bbd338ef3e06952d79ae112415aa61369901b8af90","PathPlanning/CubicSpline/cubic_spline_planner.py":"eb416e3834f5881dbec824729a1ab6010138f49a030ceb29f758b23cc5ed2adc","PathPlanning/DepthFirstSearch/depth_first_search.py":"60147610b72c80ce8385f667f4a4e874b60421c5e40f19775f087693248f4afb","PathPlanning/Dijkstra/dijkstra.py":"5dceeacad5a3a03245bea9fb9b344252a51a5a1d364aa76d83a8832d975d6574","PathPlanning/DubinsPath/dubins_path_planner.py":"07fba67057d900d4c2b7794c9b0818a86342af8a520c914252dec620d94c61eb","PathPlanning/DynamicWindowApproach/dynamic_window_approach.py":"985aa9acb1e6de234fa15ec9c83d5a7435ce2d9e22c6f6e308e1ab038141c471","PathPlanning/GreedyBestFirstSearch/greedy_best_first_search.py":"5b166b9b6a62f1f40e0d018ff509a90d07ce40471f99e2acf2e9f0d5d32de434","PathPlanning/PotentialFieldPlanning/potential_field_planning.py":"79bc4c9b5cae8266d3bf4fee05385ea4dd1094f24cdcb09a3b1b4615d3719f01","PathPlanning/ProbabilisticRoadMap/probabilistic_road_map.py":"7a1ae0ff436bcdf203853449a56761841a57f16a288520d2727284daa9ee3691","PathPlanning/QuinticPolynomialsPlanner/quintic_polynomials_planner.py":"606e96761b7c1590afba5824bf9e3a23c575690a0a16b2256b8a23dae7797272","PathPlanning/RRT/rrt.py":"ed8844dba554c6a27cc18137c2214dd066145701216d0aeab974cc4e4fea5d6e","PathPlanning/RRT/rrt_with_pathsmoothing.py":"3d5aba05cccd5c065fbdebe24f175cecef3979e924ff637b8afe75ec1387c130","PathPlanning/RRTStar/rrt_star.py":"6beeefcc0c8b9755f0257fd442e9b0a35dac1d913fb56a8bf8ce973ba5a20b25","PathPlanning/ReedsSheppPath/reeds_shepp_path_planning.py":"7b2bc055cd9de93a95d9ed4a000bad049ccc889324600d3736ed4da18f7ea947","PathTracking/pure_pursuit/pure_pursuit.py":"d6702311927cb44cbe27546e6e76ba0b7371a6b0715013ac2a40735b299779eb","PathTracking/stanley_control/stanley_control.py":"ec426a511821620d798a46a35f0ab64382bd79ff417e0f59fb0c1f7873d8c7a0","utils/__init__.py":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855","utils/angle.py":"62c3f0fdc76298d772d574b7a4357fded9265d1e0af048d87b5c8ca1a528017a","utils/plot.py":"7958fb8403bd3b05550a0356e3aeaeaee194678dfb8a069350a089b0666e8537","ArmNavigation/n_joint_arm_to_point_control/__init__.py":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855","ArmNavigation/__init__.py":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855","__init__.py":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855","Localization/__init__.py":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855","PathPlanning/__init__.py":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855","PathPlanning/CubicSpline/__init__.py":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855","PathPlanning/DubinsPath/__init__.py":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855","PathPlanning/RRT/__init__.py":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855","PathPlanning/RRTStar/__init__.py":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855","PathTracking/__init__.py":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"},"interface":{"version":"1","kind":"algorithm","abstraction_level":0,"execution_domain":"computation","language":"python","input_transport":"json_file_or_inline","output_transport":"json_stdout","conventions":{"linear_unit":"m","angular_unit":"rad","time_unit":"s","coordinate_frame":"planar_map_xy","joint_order":"not_used","quaternion_order":"not_used"},"input_schema":{"type":"object","required":["start","goal","curvature","step_size"],"additionalProperties":false,"properties":{"start":{"type":"array","minItems":3,"maxItems":3,"items":{"type":"number","minimum":-20,"maximum":20},"x-unit":"mixed","x-frame":"planar_map_xy","x-order":["x_m","y_m","yaw_rad"],"description":"start; units=mixed; frame=planar_map_xy; component order=x_m,y_m,yaw_rad"},"goal":{"type":"array","minItems":3,"maxItems":3,"items":{"type":"number","minimum":-20,"maximum":20},"x-unit":"mixed","x-frame":"planar_map_xy","x-order":["x_m","y_m","yaw_rad"],"description":"goal; units=mixed; frame=planar_map_xy; component order=x_m,y_m,yaw_rad"},"curvature":{"type":"number","minimum":0.2,"maximum":2,"x-unit":"1/m","x-frame":"planar_map_xy","description":"curvature; units=1/m; frame=planar_map_xy"},"step_size":{"type":"number","minimum":0.05,"maximum":0.2,"x-unit":"upstream_normalized_path_increment; see pinned planner","x-frame":"planar_map_xy","description":"step_size; units=upstream_normalized_path_increment; see pinned planner; frame=planar_map_xy"}}},"output_schema":{"type":"object","required":["path_xy","yaw_rad","length_m"],"additionalProperties":false,"properties":{"path_xy":{"type":"array","minItems":2,"maxItems":2048,"items":{"type":"array","minItems":2,"maxItems":2,"items":{"type":"number","minimum":-100.0,"maximum":100.0}},"x-unit":"m","x-frame":"planar_map_xy","x-order":["x","y"],"description":"path_xy; units=m; frame=planar_map_xy; component order=x,y"},"yaw_rad":{"type":"array","minItems":2,"maxItems":2048,"items":{"type":"number","minimum":-100,"maximum":100},"x-unit":"rad","x-frame":"planar_map_xy","description":"yaw_rad; units=rad; frame=planar_map_xy"},"length_m":{"type":"number","minimum":0,"maximum":10000,"x-unit":"m","x-frame":"planar_map_xy","description":"length_m; units=m; frame=planar_map_xy"}}},"preconditions":["Free-space kinematic path only; there is no obstacle or vehicle-footprint check.","Pose order [x_m,y_m,yaw_rad]; yaw is counterclockwise about +z."],"postconditions":["All declared checks must pass and all outputs must be finite.","Success applies only to this operation and model, not higher-level task completion."],"failure_codes":["invalid_input_or_environment","execution_failed","task_failed"],"composition":{"depends_on":[],"automatic_frame_conversion":false,"automatic_hardware_execution":false},"output_selector":"outputs"},"example":{"start":[0,0,0],"goal":[4,4,1.5707963267948966],"curvature":1.0,"step_size":0.1}}')

if __name__ == "__main__":
    raise SystemExit(adapter_main(SPEC, pythonrobotics_backend))
