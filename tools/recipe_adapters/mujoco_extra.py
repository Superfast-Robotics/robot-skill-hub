"""MIT: native Shadow DexEE PID setpoints and torque-limited Go2 standing."""
def mainstream_backend(root,data,spec):
    import importlib.metadata
    import numpy as np
    os.environ.setdefault('MUJOCO_GL','egl')
    for pin in spec['packages']:
        name,expected=pin.split('==');actual=importlib.metadata.version(name).split('+')[0]
        if actual!=expected:raise ContractError('Pinned package version differs: '+name)
    import mujoco
    m=mujoco.MjModel.from_xml_path(str(root/spec['model_path']));d=mujoco.MjData(m)
    if m.nkey:mujoco.mj_resetDataKeyframe(m,d,0)
    mujoco.mj_forward(m,d)
    indices=spec['actuator_indices'];joints=[int(m.actuator_trnid[a,0]) for a in indices]
    qaddrs=[int(m.jnt_qposadr[j]) for j in joints];vaddrs=[int(m.jnt_dofadr[j]) for j in joints]
    if spec['operation']=='quadruped_stand':
        target=d.qpos[qaddrs].copy();d.qvel[0]=data['push_velocity_m_s']
        body=int(m.jnt_bodyid[0]);minimum_height=10.
        for step in range(3500):
            torque=90*(target-d.qpos[qaddrs])-3*d.qvel[vaddrs]
            for k,a in enumerate(indices):d.ctrl[a]=np.clip(torque[k],*m.actuator_ctrlrange[a])
            mujoco.mj_step(m,d)
            if step>500:minimum_height=min(minimum_height,float(d.xpos[body,2]))
        error=float(np.max(np.abs(target-d.qpos[qaddrs])));up=float(d.xmat[body,8])
        xyz=d.xpos[body].tolist()
        return {'base_xyz_m':xyz,'minimum_base_height_m':minimum_height,'upright_z':up,'max_joint_error_rad':error}, {
            'standing_height':.15<xyz[2]<.5 and minimum_height>.15,'upright':up>.9,'joint_tracking':error<.18,
            'finite_state':bool(np.isfinite(d.qpos).all())}
    for a,q in zip(indices,qaddrs):d.ctrl[a]=d.qpos[q]
    for _ in range(500):mujoco.mj_step(m,d)
    start=d.qpos[qaddrs].copy();target=start+data['joint_offset_rad']
    for k,(a,j) in enumerate(zip(indices,joints)):
        target[k]=np.clip(target[k],m.jnt_range[j,0]+.02,m.jnt_range[j,1]-.02)
        target[k]=np.clip(target[k],*m.actuator_ctrlrange[a]);d.ctrl[a]=target[k]
    for _ in range(2500):mujoco.mj_step(m,d)
    final=d.qpos[qaddrs];error=float(np.max(np.abs(final-target)));moved=float(np.max(np.abs(final-start)))
    return {'joint_positions_rad':final.tolist(),'target_joint_positions_rad':target.tolist(),'max_error_rad':error,'movement_rad':moved}, {
        'nontrivial_target':bool(np.max(np.abs(target-start))>=.03),'joint_goal_reached':error<.035,'actual_motion':moved>=.02,
        'finite_state':bool(np.isfinite(d.qpos).all())}
