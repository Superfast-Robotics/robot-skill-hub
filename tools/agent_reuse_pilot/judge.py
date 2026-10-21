"""Independent numerical judges. Never trust a candidate's success flag."""
import json,math,sys

def finite(value):
    if isinstance(value,dict):return all(finite(v) for v in value.values())
    if isinstance(value,list):return all(finite(v) for v in value)
    return not isinstance(value,(int,float)) or (not isinstance(value,bool) and math.isfinite(value))

def segment_distance(p,a,b):
    dx,dy=b[0]-a[0],b[1]-a[1]
    t=max(0,min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/(dx*dx+dy*dy))) if dx or dy else 0
    return math.dist(p,[a[0]+t*dx,a[1]+t*dy])

def grade(kind,task,out):
    try:
        assert isinstance(out,dict) and finite(out),'Nonfinite or malformed result'
        if kind=='astar':
            path=out['path_xy'];lo,hi=task['bounds']
            assert 2<=len(path)<=2048 and all(len(p)==2 for p in path)
            obstacles=task['obstacles']+[[x,y] for x in range(lo,hi+1) for y in (lo,hi)]+[[x,y] for y in range(lo,hi+1) for x in (lo,hi)]
            length=sum(math.dist(a,b) for a,b in zip(path,path[1:]))
            checks={'start':math.dist(path[0],task['start'])<1e-6,'goal':math.dist(path[-1],task['goal'])<1e-6,
                    'inside_bounds':all(lo<p[0]<hi and lo<p[1]<hi for p in path),
                    'continuous_collision_clearance':all(segment_distance(o,a,b)>=task['robot_radius']-1e-8 for a,b in zip(path,path[1:]) for o in obstacles),
                    'length_consistent':abs(out['length_m']-length)<1e-6}
        elif kind=='trajectory':
            t=out['time_s'];pos=out['position'];v=out['velocity'];acc=out['acceleration'];n=len(task['current_position'])
            assert 2<=len(t)<=3000 and len(t)==len(pos)==len(v)==len(acc)
            assert all(len(row)==n for data in (pos,v,acc) for row in data)
            assert all(b>a for a,b in zip(t,t[1:]))
            err=lambda a,b:max(abs(x-y) for x,y in zip(a,b))
            checks={'time_start':abs(t[0])<1e-9,'duration':0<t[-1]<=30 and abs(out['duration_s']-t[-1])<1e-9,
                'sampling':max(b-a for a,b in zip(t,t[1:]))<=task['dt']+1e-8,
                'units':out['coordinate_type']==task['coordinate_type'],
                'initial_state':all(err(series[0],task[key])<1e-6 for series,key in [(pos,'current_position'),(v,'current_velocity'),(acc,'current_acceleration')]),
                'terminal_state':all(err(series[-1],task[key])<1e-6 for series,key in [(pos,'target_position'),(v,'target_velocity'),(acc,'target_acceleration')]),
                'velocity_limits':all(abs(x)<=limit+1e-7 for row in v for x,limit in zip(row,task['max_velocity'])),
                'acceleration_limits':all(abs(x)<=limit+1e-7 for row in acc for x,limit in zip(row,task['max_acceleration'])),
                'sampled_jerk_limits':all(abs(y-x)/(tb-ta)<=limit+1e-5 for aa,ab,ta,tb in zip(acc,acc[1:],t,t[1:]) for x,y,limit in zip(aa,ab,task['max_jerk'])),
                'position_velocity_consistency':all(abs((pb[j]-pa[j])/(tb-ta)-(va[j]+vb[j])/2)<.002 for pa,pb,va,vb,ta,tb in zip(pos,pos[1:],v,v[1:],t,t[1:]) for j in range(n)),
                'velocity_acceleration_consistency':all(abs((vb[j]-va[j])/(tb-ta)-(aa[j]+ab[j])/2)<.02 for va,vb,aa,ab,ta,tb in zip(v,v[1:],acc,acc[1:],t,t[1:]) for j in range(n))}
        elif kind=='bullet_ik':
            import pybullet as p
            from scene import create_arm
            q=out['joint_angles_rad'];assert len(q)==7
            client=p.connect(p.DIRECT)
            try:
                robot=create_arm(p)
                for i,x in enumerate(q):p.resetJointState(robot,i,x)
                xyz=p.getLinkState(robot,6,computeForwardKinematics=1)[4]
                residual=math.dist(xyz,task['target_xyz'])
                checks={'independent_fk_residual':residual<.002,'reported_fk_consistent':math.dist(xyz,out['end_effector_xyz_m'])<1e-6,
                    'reported_error_consistent':abs(residual-out['position_error_m'])<1e-6}
            finally:p.disconnect(client)
        else:raise ValueError('Unknown task')
        return {'passed':all(checks.values()),'checks':checks}
    except Exception as exc:return {'passed':False,'error':type(exc).__name__+': '+str(exc)[:800]}

if __name__=='__main__':
    item=json.load(sys.stdin)
    print('RSH_RESULT='+json.dumps(grade(item['kind'],item['task'],item['output'])))
