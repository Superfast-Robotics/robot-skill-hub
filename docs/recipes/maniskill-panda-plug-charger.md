# ManiSkill panda_wristcam PlugCharger-v1 motion planner

Grasp a charger, align its pins, and plug it into a receptacle.

## Source

- Repository: https://github.com/haosulab/ManiSkill
- Release: v3.0.0b22; commit `33967b9e3ead1f841eec57cc9f31d0d8b8cf0907`
- Solver: [mani_skill.examples.motionplanning.panda.solutions.plug_charger:solve](https://github.com/haosulab/ManiSkill/blob/33967b9e3ead1f841eec57cc9f31d0d8b8cf0907/mani_skill/examples/motionplanning/panda/solutions/plug_charger.py)
- License: [Apache-2.0](https://github.com/haosulab/ManiSkill/blob/33967b9e3ead1f841eec57cc9f31d0d8b8cf0907/LICENSE); robot/mesh assets retain upstream notices.
- Recipe ID: `maniskill-panda-plug-charger`
- Canonical JSON: https://hub.superfastrobotics.com/skills/maniskill-panda-plug-charger/skill.json

## Agent preparation

```sh
python skills/find-robot-skills/scripts/rsh.py inspect maniskill-panda-plug-charger --json
python skills/find-robot-skills/scripts/rsh.py prepare maniskill-panda-plug-charger --project ./experiment --plan --json
python skills/find-robot-skills/scripts/rsh.py prepare maniskill-panda-plug-charger --project ./experiment --download-only --json
```

Run preparation on Linux x86_64 with Python 3.10 for the simulator environment.
Add `--install-deps` explicitly to install dependencies. The returned task command
is a separate execution step. Input is one seed (`--seed 0` by default); output is
a final JSON line with task status and success. Use a 300-second process timeout.

## Environment contract

`maniskill==3.0.0b22`, robot `panda_wristcam`, `pd_joint_pos`, `state` observations,
`cpu` simulation, `render_backend=none`, no video/display, sparse rewards.
The planner reads privileged simulator poses and collision geometry. It is a
simulation example, not a perception policy or a physical robot controller.

The source archive and direct dependency versions are pinned. Transitive Python
dependencies resolve during installation and are captured by the project lock.
The exact source and wrapper contracts were inspected; runtime status is recorded
in the JSON evidence fields. A nonzero exit and JSON error preserve failures.
