"""Headless bounded adaptations of official PyBullet examples (Hub MIT).

Uses only procedural geometry. No model downloads, asset licenses, GUI, robot
servers or hardware calls are involved. The seven-axis arm is synthetic.
"""


def pybullet_backend(root, d, spec):
    import numpy as np
    import pybullet as p
    from importlib.metadata import version
    if version('pybullet')!='3.2.7': raise ContractError('Requires the tested pybullet==3.2.7 binding')
    client=p.connect(p.DIRECT)
    if client<0: raise ContractError('DIRECT simulation unavailable')
    try:
        p.setPhysicsEngineParameter(deterministicOverlappingPairs=1,numSolverIterations=100)
        p.setTimeStep(1/240)
        def box(position,mass=1.,half=.1):
            shape=p.createCollisionShape(p.GEOM_BOX,halfExtents=[half]*3)
            return p.createMultiBody(baseMass=mass,baseCollisionShapeIndex=shape,basePosition=position)
        def arm():
            shape=p.createCollisionShape(p.GEOM_SPHERE,radius=.035)
            robot=p.createMultiBody(baseMass=0,basePosition=[0,0,0],
                linkMasses=[1.]*7,linkCollisionShapeIndices=[shape]*7,linkVisualShapeIndices=[-1]*7,
                linkPositions=[[0,0,.2]]*7,linkOrientations=[[0,0,0,1]]*7,
                linkInertialFramePositions=[[0,0,0]]*7,linkInertialFrameOrientations=[[0,0,0,1]]*7,
                linkParentIndices=list(range(7)),linkJointTypes=[p.JOINT_REVOLUTE]*7,
                linkJointAxis=[[0,0,1],[0,1,0],[0,1,0],[1,0,0],[0,1,0],[1,0,0],[0,0,1]])
            p.setJointMotorControlArray(robot,list(range(7)),p.VELOCITY_CONTROL,forces=[0.]*7)
            return robot
        op=spec['operation']
        if op in ['ik','jacobian','inverse_dynamics','position_control','torque_pd','force_torque']:
            robot=arm(); q=d['joint_angles']
            for j,v in enumerate(q): p.resetJointState(robot,j,v)
            if op=='ik':
                target=d['target_xyz']
                joints=p.calculateInverseKinematics(robot,6,target,maxNumIterations=1000,residualThreshold=1e-7)
                for j,v in enumerate(joints): p.resetJointState(robot,j,v)
                point=p.getLinkState(robot,6,computeForwardKinematics=1)[4]
                error=math.dist(point,target)
                return {'joint_angles_rad':joints,'end_effector_xyz_m':point,'position_error_m':error}, {'target_residual':error<.002}
            if op=='jacobian':
                linear,angular=p.calculateJacobian(robot,6,[0,0,0],q,[0.]*7,[0.]*7)
                finite_difference=np.zeros((3,7)); eps=1e-5
                for j in range(7):
                    p.resetJointState(robot,j,q[j]+eps); plus=np.array(p.getLinkState(robot,6,computeForwardKinematics=1)[0])
                    p.resetJointState(robot,j,q[j]-eps); minus=np.array(p.getLinkState(robot,6,computeForwardKinematics=1)[0])
                    p.resetJointState(robot,j,q[j]); finite_difference[:,j]=(plus-minus)/(2*eps)
                error=float(np.max(np.abs(np.array(linear)-finite_difference)))
                return {'linear_jacobian':linear,'angular_jacobian':angular,'finite_difference_max_error':error}, {'matches_finite_difference':error<1e-5}
            if op=='inverse_dynamics':
                p.setGravity(0,0,-9.81)
                accel=d['joint_acceleration']; gravity=np.array(p.calculateInverseDynamics(robot,q,[0.]*7,[0.]*7))
                torque=np.array(p.calculateInverseDynamics(robot,q,[0.]*7,accel)); mass=np.array(p.calculateMassMatrix(robot,q))
                residual=float(np.max(np.abs(torque-gravity-mass@np.array(accel))))
                return {'torque_nm':torque,'gravity_torque_nm':gravity,'mass_matrix':mass,'dynamics_residual_nm':residual}, {
                    'mass_matrix_symmetric':bool(np.allclose(mass,mass.T,atol=1e-9)), 'mass_matrix_positive_definite':bool(np.linalg.eigvalsh(mass).min()>0), 'inverse_dynamics_identity':residual<1e-7}
            if op=='force_torque':
                p.setGravity(0,0,-9.81); p.enableJointForceTorqueSensor(robot,3,enableSensor=1)
                p.setJointMotorControlArray(robot,list(range(7)),p.POSITION_CONTROL,targetPositions=q,forces=[200]*7)
                for _ in range(240): p.stepSimulation()
                force=p.getJointState(robot,3)[2]
                return {'reaction_force_torque':force}, {'sensor_has_six_components':len(force)==6,'finite_sensor':all(math.isfinite(v) for v in force),'load_observed':math.sqrt(sum(v*v for v in force))>1e-3}
            target=np.array(d['target_joint_angles'])
            if op=='position_control':
                p.setJointMotorControlArray(robot,list(range(7)),p.POSITION_CONTROL,targetPositions=target.tolist(),forces=[200.]*7)
                for _ in range(720): p.stepSimulation()
            else:
                for _ in range(1440):
                    state=p.getJointStates(robot,list(range(7))); positions=np.array([s[0] for s in state]); velocities=np.array([s[1] for s in state])
                    # The synthetic chain has widely different axis inertias;
                    # mass-scaled PD uses inverse dynamics for those coordinates.
                    acceleration=40*(target-positions)-12*velocities
                    tau=p.calculateInverseDynamics(robot,positions.tolist(),velocities.tolist(),acceleration.tolist())
                    p.setJointMotorControlArray(robot,list(range(7)),p.TORQUE_CONTROL,forces=tau)
                    p.stepSimulation()
            achieved=[s[0] for s in p.getJointStates(robot,list(range(7)))]; error=max(abs(a-b) for a,b in zip(achieved,target))
            return {'joint_angles_rad':achieved,'maximum_joint_error_rad':error}, {'target_joint_residual':error<.02}
        if op in ['fall','friction']:
            p.setGravity(0,0,-9.81)
            plane=p.createMultiBody(baseMass=0,baseCollisionShapeIndex=p.createCollisionShape(p.GEOM_PLANE))
            body=box([0,0,d['height']],d['mass'])
            p.changeDynamics(plane,-1,lateralFriction=d['friction'],restitution=0)
            p.changeDynamics(body,-1,lateralFriction=d['friction'],restitution=0)
            if op=='friction':
                for _ in range(240): p.stepSimulation()
                p.resetBaseVelocity(body,linearVelocity=[1.,0,0])
            for _ in range(720): p.stepSimulation()
            position=p.getBasePositionAndOrientation(body)[0]; velocity=p.getBaseVelocity(body)[0]; contacts=p.getContactPoints(body,plane)
            checks={'settled_height':abs(position[2]-.1)<.005,'floor_contact':len(contacts)>0,'bounded_penetration':all(c[8]>-.005 for c in contacts)}
            if op=='friction': checks['sliding_stopped']=math.hypot(velocity[0],velocity[1])<.02
            return {'position_xyz_m':position,'velocity_xyz_m_s':velocity,'contact_count':len(contacts)},checks
        if op=='raycast':
            body=box(d['box_center'],mass=0)
            result=p.rayTest(d['ray_from'],d['ray_to'])[0]
            point=result[3]
            return {'hit':result[0]==body,'hit_fraction':result[2],'hit_xyz_m':point,'normal_xyz':result[4]}, {
                'expected_body_hit':result[0]==body,'fraction_in_segment':0<=result[2]<=1,
                'intersection_on_box_surface':abs(max(abs(a-b) for a,b in zip(point,d['box_center']))-.1)<1e-6}
        if op=='collision_filter':
            a=box([0,0,1],mass=0); b=box([d['offset'],0,1])
            p.performCollisionDetection(); before=len(p.getContactPoints(a,b))
            p.setCollisionFilterPair(a,b,-1,-1,enableCollision=0); p.performCollisionDetection(); after=len(p.getContactPoints(a,b))
            return {'contacts_enabled':before,'contacts_disabled':after}, {'overlap_detected':before>0,'filter_removed_contacts':after==0}
        if op=='constraint':
            p.setGravity(0,0,-9.81)
            a=box([0,0,1],mass=0); b=box([0,0,1.5],mass=d['mass'])
            p.createConstraint(a,-1,b,-1,p.JOINT_FIXED,[0,0,0],[0,0,.5],[0,0,0])
            for _ in range(720): p.stepSimulation()
            position=p.getBasePositionAndOrientation(b)[0]; error=math.dist(position,[0,0,1.5])
            return {'child_xyz_m':position,'anchor_error_m':error}, {'fixed_constraint_holds':error<.005}
        if op=='save_restore':
            body=box(d['position']); state=p.saveState()
            p.resetBasePositionAndOrientation(body,[3,2,1],[0,0,0,1]); p.restoreState(stateId=state)
            position=p.getBasePositionAndOrientation(body)[0]; p.removeState(state)
            return {'restored_xyz_m':position}, {'original_state_restored':math.dist(position,d['position'])<1e-10}
        raise ContractError('Unknown reviewed simulation operation')
    finally:
        p.disconnect(client)
