# ManiSkill xarm6_robotiq StackCube-v1 motion planner

Stack one cube on another with the official xArm6 Robotiq solver.

## Source

- Repository: https://github.com/haosulab/ManiSkill
- Release: v3.0.0b22; commit `33967b9e3ead1f841eec57cc9f31d0d8b8cf0907`
- Solver: [mani_skill.examples.motionplanning.xarm6.solutions.stack_cube:solve](https://github.com/haosulab/ManiSkill/blob/33967b9e3ead1f841eec57cc9f31d0d8b8cf0907/mani_skill/examples/motionplanning/xarm6/solutions/stack_cube.py)
- License: [Apache-2.0](https://github.com/haosulab/ManiSkill/blob/33967b9e3ead1f841eec57cc9f31d0d8b8cf0907/LICENSE); robot/mesh assets retain upstream notices.
- Recipe ID: `maniskill-xarm6-stack-cube`
- Canonical JSON: https://hub.superfastrobotics.com/skills/maniskill-xarm6-stack-cube/skill.json

## Agent preparation

```sh
python skills/find-robot-skills/scripts/rsh.py inspect maniskill-xarm6-stack-cube --json
python skills/find-robot-skills/scripts/rsh.py prepare maniskill-xarm6-stack-cube --project ./experiment --plan --json
python skills/find-robot-skills/scripts/rsh.py prepare maniskill-xarm6-stack-cube --project ./experiment --download-only --json
```

Run preparation on Linux x86_64 with Python 3.10 for the simulator environment.
Add `--install-deps` explicitly to install dependencies. The returned task command
is a separate execution step. Input is one seed (`--seed 0` by default); output is
a final JSON line with task status and success. Use a 300-second process timeout.

## Environment contract

`maniskill==3.0.0b22`, robot `xarm6_robotiq`, `pd_joint_pos`, `state` observations,
`cpu` simulation, `render_backend=none`, no video/display, sparse rewards.
The planner reads privileged simulator poses and collision geometry. It is a
simulation example, not a perception policy or a physical robot controller.

The source archive and direct dependency versions are pinned. Transitive Python
dependencies resolve during installation and are captured by the project lock.
The exact source and wrapper contracts were inspected; runtime status is recorded
in the JSON evidence fields. A nonzero exit and JSON error preserve failures.

This robot variant comes from the official xArm6 runner. Some upstream task declarations list Panda/Fetch only and log a warning for xArm6. Sparse rewards avoid Panda-specific dense reward code; confirm the variant in your simulator environment.
