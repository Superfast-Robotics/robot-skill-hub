"""Parameterized local-only Ruckig Community example adaptations (MIT)."""


def ruckig_backend(root, d, spec):
    from importlib.metadata import version
    if version('ruckig')!='0.19.4': raise ContractError('Requires the tested ruckig==0.19.4 binding')
    from ruckig import InputParameter, OutputParameter, Result, Ruckig, Trajectory, ControlInterface, Synchronization
    n=len(d['current_position'])
    fields=['current_position','current_velocity','current_acceleration','target_position','target_velocity','target_acceleration','max_velocity','max_acceleration','max_jerk']
    if any(len(d[key])!=n for key in fields): raise ContractError('All axis arrays must have the same length')
    if any(v<=0 for key in ['max_velocity','max_acceleration','max_jerk'] for v in d[key]): raise ContractError('Kinematic limits must be positive')
    if any(abs(v)>lim for key,limit in [('current_velocity','max_velocity'),('target_velocity','max_velocity'),('current_acceleration','max_acceleration'),('target_acceleration','max_acceleration')] for v,lim in zip(d[key],d[limit])):
        raise ContractError('Boundary state exceeds declared limits')
    inp=InputParameter(n)
    for key in fields: setattr(inp,key,d[key])
    op=spec['operation']
    if op=='velocity': inp.control_interface=ControlInterface.Velocity
    if op=='minimum_duration': inp.minimum_duration=d['minimum_duration']
    generator=Ruckig(n,d['dt'])
    time_values=[]; positions=[]; velocities=[]; accelerations=[]
    stopped=False
    if op=='offline':
        trajectory=Trajectory(n)
        result=generator.calculate(inp,trajectory)
        if result!=Result.Working or trajectory.duration>30: raise ContractError('Trajectory calculation failed or exceeded 30 s budget')
        count=min(3000,max(2,int(math.ceil(trajectory.duration/d['dt']))+1))
        for i in range(count):
            t=trajectory.duration*i/(count-1)
            p,v,a=trajectory.at_time(t)
            time_values.append(t); positions.append(p); velocities.append(v); accelerations.append(a)
    else:
        out=OutputParameter(n)
        for tick in range(3000):
            result=generator.update(inp,out)
            if result not in (Result.Working,Result.Finished): raise ContractError('Ruckig rejected the trajectory')
            time_values.append((tick+1)*d['dt']); positions.append(list(out.new_position)); velocities.append(list(out.new_velocity)); accelerations.append(list(out.new_acceleration))
            out.pass_to_input(inp)
            if op=='stop' and not stopped and (tick+1)*d['dt']>=d['stop_time']:
                inp.control_interface=ControlInterface.Velocity; inp.synchronization=Synchronization.No
                inp.target_velocity=[0.]*n; inp.target_acceleration=[0.]*n; stopped=True
                result=Result.Working
            if result==Result.Finished: break
        else: raise ContractError('Trajectory exceeded 3000-cycle budget')
    target_velocity=[0.]*n if op=='stop' else d['target_velocity']
    target_acceleration=[0.]*n if op=='stop' else d['target_acceleration']
    checks={'terminal_velocity':max(abs(a-b) for a,b in zip(velocities[-1],target_velocity))<1e-7,
            'terminal_acceleration':max(abs(a-b) for a,b in zip(accelerations[-1],target_acceleration))<1e-7,
            'acceleration_bounds':all(abs(a)<=lim+1e-7 for sample in accelerations for a,lim in zip(sample,d['max_acceleration'])),
            'sampled_jerk_bounds':all(abs(a-b)/(t2-t1)<=lim+1e-5 for before,after,t1,t2 in zip(accelerations,accelerations[1:],time_values,time_values[1:]) for a,b,lim in zip(before,after,d['max_jerk']))}
    if op not in ['velocity','stop']:
        # Online mode reports the first control sample at/after completion. With
        # nonzero target velocity compare its analytic continuation, not zero drift.
        duration=out.trajectory.duration if op!='offline' else trajectory.duration
        extra=max(0.,time_values[-1]-duration)
        expected=[p+v*extra+.5*a*extra*extra for p,v,a in zip(d['target_position'],d['target_velocity'],d['target_acceleration'])]
        checks['terminal_position']=max(abs(a-b) for a,b in zip(positions[-1],expected))<1e-6
        checks['velocity_bounds']=all(abs(v)<=lim+1e-7 for sample in velocities for v,lim in zip(sample,d['max_velocity']))
    if op=='minimum_duration': checks['minimum_duration']=time_values[-1]+1e-8>=d['minimum_duration']
    if op=='stop': checks['stop_triggered']=stopped
    return {'time_s':time_values,'position':positions,'velocity':velocities,'acceleration':accelerations,
            'coordinate_type':d['coordinate_type'],'duration_s':time_values[-1]},checks
