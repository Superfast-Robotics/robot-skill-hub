"""MIT: bounded runner for the pinned upstream goal-observable scripted policy."""
def mainstream_backend(root,data,spec):
    import importlib.metadata
    import numpy as np
    for pin in spec['packages']:
        name,version=pin.split('==')
        if importlib.metadata.version(name)!=version:raise ContractError('Pinned package version differs: '+name)
    # Load the actual archived controllers and task implementation, not an
    # unpinned policy with the same class name from a different installation.
    sys.path.insert(0,str(root))
    import metaworld
    from metaworld.env_dict import ALL_V3_ENVIRONMENTS_GOAL_OBSERVABLE
    from importlib import import_module
    policy=getattr(import_module(spec['policy_module']),spec['policy_class'])()
    env=ALL_V3_ENVIRONMENTS_GOAL_OBSERVABLE[spec['env_id']+'-goal-observable'](seed=data['seed'])
    try:
        obs,_=env.reset(seed=data['seed']);initial=obs[:3].copy();window=[];control=0.;finite=True
        for step in range(500):
            action=np.asarray(policy.get_action(obs),dtype=np.float64)
            if action.shape!=(4,) or not np.isfinite(action).all():raise ContractError('Invalid policy action')
            action=np.clip(action,env.action_space.low,env.action_space.high);control+=float(np.linalg.norm(action))
            obs,reward,terminated,truncated,info=env.step(action)
            finite=finite and bool(np.isfinite(obs).all() and math.isfinite(float(reward)))
            window.append(bool(info.get('success',False)));window=window[-20:]
            if len(window)>=5 and all(window[-5:]):break
            if terminated or truncated:break
        metrics=[{'name':k,'value':float(v)} for k,v in sorted(info.items()) if isinstance(v,(int,float,np.number)) and np.isfinite(v)]
        complete=len(window)>=5 and all(window[-5:])
        return {'success_window':window,'native_success':bool(info.get('success',False)),
                'steps':step+1,'control_effort':control,'hand_movement_m':float(np.linalg.norm(obs[:3]-initial)),
                'native_metrics':metrics}, {'sustained_native_task_predicate':complete,'finite_state':finite,
                'nonzero_control':control>0,'physical_simulation_steps':step+1>=5}
    finally:env.close()
