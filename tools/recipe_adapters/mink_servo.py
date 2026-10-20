"""MIT: bounded differential IK followed by dynamic actuator tracking."""
def mainstream_backend(root,data,spec):
    import importlib.metadata
    import numpy as np
    import mujoco
    # The archive is the selected code version; PyPI supplies locked dependency
    # installation metadata. Use its documented Python fallback explicitly.
    os.environ['MINK_DISABLE_NATIVE']='1'
    sys.path.insert(0,str(root/'src'))
    import mink
    for pin in spec['packages']:
        name,version=pin.split('==')
        if importlib.metadata.version(name)!=version:raise ContractError('Pinned package version differs: '+name)
    for relative in spec['runtime_guards']:
        module=__import__(relative,fromlist=['_'])
        path=Path(module.__file__)
        source=root/'src'/Path(*relative.split('.')).with_suffix('.py')
        if path.read_bytes()!=source.read_bytes():raise ContractError('Installed Mink code differs: '+relative)
    m=mujoco.MjModel.from_xml_path(str(root/spec['model_path']));d=mujoco.MjData(m)
    if m.nkey:mujoco.mj_resetDataKeyframe(m,d,m.key('home').id)
    mujoco.mj_forward(m,d);initial=d.site('attachment_site').xpos.copy();target=initial+np.asarray(data['target_offset_m'])
    q=mink.Configuration(m);q.update(d.qpos);task=mink.FrameTask(frame_name='attachment_site',frame_type='site',position_cost=1.,orientation_cost=1.,lm_damping=1e-6)
    posture=mink.PostureTask(m,cost=1e-3);posture.set_target_from_configuration(q)
    pose=mink.SE3.from_rotation_and_translation(mink.SO3.from_matrix(d.site('attachment_site').xmat.reshape(3,3)),target);task.set_target(pose)
    limits=[mink.ConfigurationLimit(m)]
    if spec['robot']=='ur5e':
        limits.append(mink.CollisionAvoidanceLimit(m,geom_pairs=[(['wrist_3_link'],['floor','wall'])]))
    for _ in range(300):
        velocity=mink.solve_ik(q,[task,posture],.005,'daqp',damping=1e-3,limits=limits);q.integrate_inplace(velocity,.005)
        if np.linalg.norm(task.compute_error(q))<1e-4:break
    desired=q.q.copy();indices=[]
    for a in range(m.nu):
        if m.actuator_trntype[a]==0 and m.actuator_biasprm[a,1]<0:
            j=int(m.actuator_trnid[a,0]);indices.append((a,int(m.jnt_qposadr[j])))
    if len(indices)<6:raise ContractError('Missing position actuators')
    for _ in range(3000):
        for a,j in indices:d.ctrl[a]=desired[j]
        mujoco.mj_step(m,d)
    mujoco.mj_forward(m,d);final=d.site('attachment_site').xpos.copy();error=float(np.linalg.norm(final-target))
    rotation=d.site('attachment_site').xmat.reshape(3,3);orientation_error=float(np.linalg.norm(mink.SO3.from_matrix(rotation).minus(pose.rotation())))
    return {'final_xyz_m':final.tolist(),'target_xyz_m':target.tolist(),'error_m':error,
            'movement_m':float(np.linalg.norm(final-initial)),'orientation_error_rad':orientation_error,'steps':3000}, {
        'cartesian_goal_reached':error<.015,'orientation_held':orientation_error<.05,'nontrivial_motion':bool(np.linalg.norm(final-initial)>.015),
        'finite_state':bool(np.isfinite(d.qpos).all() and np.isfinite(d.qvel).all())}
