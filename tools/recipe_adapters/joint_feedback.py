"""MIT: position-servo feedback compensates static load without changing the goal."""
def mainstream_backend(root,data,spec):
    import importlib.metadata
    import numpy as np
    import mujoco
    for pin in spec['packages']:
        name,version=pin.split('==')
        if importlib.metadata.version(name)!=version:raise ContractError('Pinned package version differs: '+name)
    m=mujoco.MjModel.from_xml_path(str(root/spec['model_path']));d=mujoco.MjData(m)
    if m.nkey:mujoco.mj_resetDataKeyframe(m,d,0)
    mujoco.mj_forward(m,d);indices=[]
    for name in spec['interface']['output_schema']['properties']['joint_positions_rad']['x-order']:
        joint=m.joint(name).id
        candidates=[a for a in range(m.nu) if m.actuator_trntype[a]==0 and m.actuator_trnid[a,0]==joint and m.actuator_biasprm[a,1]<0]
        if len(candidates)!=1:raise ContractError('Expected one position actuator per joint')
        indices.append(candidates[0])
    joints=[int(m.actuator_trnid[a,0]) for a in indices];qaddrs=[int(m.jnt_qposadr[j]) for j in joints]
    for a,q in zip(indices,qaddrs):d.ctrl[a]=d.qpos[q]
    for _ in range(500):mujoco.mj_step(m,d)
    initial=d.qpos[qaddrs].copy();target=initial+data['joint_offset_rad'];integral=np.zeros(len(joints))
    for k,(a,j) in enumerate(zip(indices,joints)):
        if m.jnt_limited[j]:target[k]=np.clip(target[k],m.jnt_range[j,0]+.02,m.jnt_range[j,1]-.02)
        if m.actuator_ctrllimited[a]:target[k]=np.clip(target[k],*m.actuator_ctrlrange[a])
    for _ in range(4000):
        integral=np.clip(integral+3*m.opt.timestep*(target-d.qpos[qaddrs]),-.4,.4)
        for k,a in enumerate(indices):
            command=target[k]+integral[k]
            d.ctrl[a]=np.clip(command,*m.actuator_ctrlrange[a]) if m.actuator_ctrllimited[a] else command
        mujoco.mj_step(m,d)
    final=d.qpos[qaddrs];error=float(np.max(np.abs(final-target)));motion=float(np.max(np.abs(final-initial)))
    return {'joint_positions_rad':final.tolist(),'target_joint_positions_rad':target.tolist(),'max_error_rad':error,'movement_rad':motion},{
        'nontrivial_target':bool(np.max(np.abs(target-initial))>=.03),'joint_goal_reached':error<.035,'actual_motion':motion>=.02,
        'finite_state':bool(np.isfinite(d.qpos).all() and np.isfinite(d.qvel).all())}
