"""MIT: contact stacking with native IK and explicit two-object geometry checks."""
def stack_backend(root,data,spec):
    import importlib.metadata
    import numpy as np
    for pin in spec['packages']:
        name,version=pin.split('==')
        if importlib.metadata.version(name)!=version:raise ContractError('Pinned package version differs: '+name)
    sys.path.insert(0,str(root))
    import gymnasium as gym,panda_gym
    env=gym.make(spec['env_id'],render_mode='rgb_array',max_episode_steps=1500)
    try:
        obs,info=env.reset(seed=data['seed']);steps=0;sim=env.unwrapped.sim
        def move(target,grip,limit):
            nonlocal obs,info,steps
            for _ in range(limit):
                a=np.r_[np.clip((target-obs['observation'][:3])*10,-.6,.6),grip]
                obs,_,_,_,info=env.step(a);steps+=1
        def carry(body,target,limit):
            for _ in range(limit):
                actual=np.asarray(sim.get_base_position(body))
                move(obs['observation'][:3]+target-actual,-1,1)
        def transfer(body,target):
            obj=np.asarray(sim.get_base_position(body)).copy()
            move(obj+np.array([0,0,.13]),1,40);move(obj+np.array([0,0,.003]),1,40)
            move(obj+np.array([0,0,.003]),-1,30);carry(body,obj+np.array([0,0,.18]),45)
            carry(body,target+np.array([0,0,.15]),50);carry(body,target,60)
            released=obs['observation'][:3].copy();move(released,1,30)
            move(released+np.array([0,0,.15]),1,40)
        goal=obs['desired_goal'].copy();transfer('object1',goal[:3])
        # Stack on the measured lower cube, rather than assuming a perfect first placement.
        lower=np.asarray(sim.get_base_position('object1')).copy()
        transfer('object2',lower+np.array([0,0,.041]))
        achieved=obs['achieved_goal'];error=float(np.linalg.norm(achieved-goal))
        height=float(achieved[5]-achieved[2]);alignment=float(np.linalg.norm(achieved[:2]-achieved[3:5]))
        success=bool(info['is_success'])
        return {'achieved_goal':achieved.tolist(),'desired_goal':goal.tolist(),'error_m':error,'steps':steps,'environment_success':success,
                'stack_height_m':height,'stack_alignment_m':alignment},{
            'native_environment_goal':success,'strict_goal_error':error<.04,'upper_cube_above_lower':.03<height<.05,
            'horizontal_support_alignment':alignment<.015,'finite_state':bool(np.isfinite(obs['observation']).all())}
    finally:env.close()

def mainstream_backend(root,data,spec):
    import ctypes
    saved=os.dup(1)
    try:
        os.dup2(2,1);return stack_backend(root,data,spec)
    finally:
        ctypes.CDLL(None).fflush(None);os.dup2(saved,1);os.close(saved)
