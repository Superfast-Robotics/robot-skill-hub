"""Shared synthetic PyBullet scene; same geometry in both experimental arms."""
def create_arm(p):
    shape=p.createCollisionShape(p.GEOM_SPHERE,radius=.035)
    robot=p.createMultiBody(baseMass=0,basePosition=[0,0,0],
        linkMasses=[1.]*7,linkCollisionShapeIndices=[shape]*7,linkVisualShapeIndices=[-1]*7,
        linkPositions=[[0,0,.2]]*7,linkOrientations=[[0,0,0,1]]*7,
        linkInertialFramePositions=[[0,0,0]]*7,linkInertialFrameOrientations=[[0,0,0,1]]*7,
        linkParentIndices=list(range(7)),linkJointTypes=[p.JOINT_REVOLUTE]*7,
        linkJointAxis=[[0,0,1],[0,1,0],[0,1,0],[1,0,0],[0,1,0],[1,0,0],[0,0,1]])
    p.setJointMotorControlArray(robot,list(range(7)),p.VELOCITY_CONTROL,forces=[0.]*7)
    return robot
