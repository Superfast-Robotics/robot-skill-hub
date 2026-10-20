"""MIT: Genesis Panda PD control and IK-to-dynamic-servo adaptation."""
def mainstream_backend(root,data,spec):
    import importlib.metadata
    import numpy as np
    import torch
    import genesis as gs
    for pin in spec['packages']:
        name,version=pin.split('==')
        installed=importlib.metadata.version(name).split('+')[0]
        if installed!=version:raise ContractError('Pinned package version differs: '+name)
    for relative in ['genesis/__init__.py','genesis/engine/entities/rigid_entity/rigid_entity.py']:
        installed=Path(gs.__file__).parent/Path(relative).relative_to('genesis')
        if installed.read_bytes()!=(root/relative).read_bytes():raise ContractError('Installed Genesis code differs: '+relative)
    gs.init(backend=gs.gpu,precision='32',logging_level='error',seed=data['seed'])
    scene=gs.Scene(sim_options=gs.options.SimOptions(dt=.01),show_viewer=False)
    scene.add_entity(gs.morphs.Plane())
    model=root/'genesis/assets/xml/franka_emika_panda/panda.xml'
    robot=scene.add_entity(gs.morphs.MJCF(file=str(model)));scene.build()
    joints=['joint'+str(i) for i in range(1,8)]+['finger_joint1','finger_joint2']
    indices=[robot.get_joint(name).dofs_idx_local[0] for name in joints]
    robot.set_dofs_kp(np.array([4500,4500,3500,3500,2000,2000,2000,100,100]),indices)
    robot.set_dofs_kv(np.array([450,450,350,350,200,200,200,10,10]),indices)
    robot.set_dofs_force_range(np.array([-87,-87,-87,-87,-12,-12,-12,-100,-100]),np.array([87,87,87,87,12,12,12,100,100]),indices)
    home=np.array([0,-.5,0,-1.8,0,1.4,.6,.04,.04]);robot.set_dofs_position(home,indices)
    robot.control_dofs_position(home,indices)
    for _ in range(100):scene.step()
    def cpu(value):return value.detach().cpu().numpy()
    initial=cpu(robot.get_link('hand').get_pos()).copy()
    if spec['operation']=='cartesian_ik':
        target=initial+np.asarray(data['target_offset_m'])
        desired=cpu(robot.inverse_kinematics(link=robot.get_link('hand'),pos=target))
    else:
        desired=cpu(robot.get_dofs_position()).copy();desired[indices[0]]+=data['joint_offset_rad'];target=None
    robot.control_dofs_position(desired)
    for _ in range(700):scene.step()
    final=cpu(robot.get_link('hand').get_pos());actual=cpu(robot.get_dofs_position());joint_error=float(np.max(np.abs(actual-desired)))
    if target is None:target=final.copy()
    error=float(np.linalg.norm(final-target));movement=float(np.linalg.norm(final-initial));gpu=bool(torch.cuda.is_available() and robot.get_dofs_position().is_cuda)
    return {'final_xyz_m':final.tolist(),'target_xyz_m':target.tolist(),'error_m':error,'movement_m':movement,
            'max_joint_error_rad':joint_error,'cuda_simulation':gpu,'steps':800}, {
        'cartesian_goal_reached':error<.015,'joint_goal_reached':joint_error<.04,'nontrivial_motion':movement>.015,
        'finite_state':bool(np.isfinite(actual).all()),'cuda_simulation':gpu}
