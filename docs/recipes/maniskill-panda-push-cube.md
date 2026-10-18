# ManiSkill panda PushCube-v1 motion planner

Push a cube to a goal region with the official Panda motion planner.

## Source

- Repository: https://github.com/haosulab/ManiSkill
- Release: v3.0.0b22; commit `33967b9e3ead1f841eec57cc9f31d0d8b8cf0907`
- Solver: [mani_skill.examples.motionplanning.panda.solutions.push_cube:solve](https://github.com/haosulab/ManiSkill/blob/33967b9e3ead1f841eec57cc9f31d0d8b8cf0907/mani_skill/examples/motionplanning/panda/solutions/push_cube.py)
- License: [Apache-2.0](https://github.com/haosulab/ManiSkill/blob/33967b9e3ead1f841eec57cc9f31d0d8b8cf0907/LICENSE); robot/mesh assets retain upstream notices.
- Recipe ID: `maniskill-panda-push-cube`
- Canonical JSON: https://hub.superfastrobotics.com/skills/maniskill-panda-push-cube/skill.json

## Agent preparation

```sh
python skills/find-robot-skills/scripts/rsh.py inspect maniskill-panda-push-cube --json
python skills/find-robot-skills/scripts/rsh.py prepare maniskill-panda-push-cube --project ./experiment --plan --json
python skills/find-robot-skills/scripts/rsh.py prepare maniskill-panda-push-cube --project ./experiment --download-only --json
```

Run preparation on Linux x86_64 with Python 3.10 for the simulator environment.
Add `--install-deps` explicitly to install dependencies. The returned task command
is a separate execution step. Input is one seed (`--seed 0` by default); output is
a final JSON line with task status and success. Use a 300-second process timeout.

## Environment contract

`maniskill==3.0.0b22`, robot `panda`, `pd_joint_pos`, `state` observations,
`cpu` simulation, `render_backend=none`, no video/display, sparse rewards.
The planner reads privileged simulator poses and collision geometry. It is a
simulation example, not a perception policy or a physical robot controller.

The source archive and direct dependency versions are pinned. Transitive Python
dependencies resolve during installation and are captured by the project lock.
The exact source and wrapper contracts were inspected; runtime status is recorded
in the JSON evidence fields. A nonzero exit and JSON error preserve failures.

## Hub episode horizon

Hub recipe version `1.1.0` explicitly sets `max_episode_steps=1000`, a Hub
motion-planning budget rather than an upstream default or standard benchmark.
The upstream source pin is unchanged. Completion requires `success=true`,
`truncated=false` and `0 < elapsed_steps < 1000`; final JSON includes `terminated`,
`truncated` and the configured horizon. `terminated` alone does not establish
success. The step budget is separate from the 300-second wall-clock timeout.

## Recorded CPU execution

[Run 39097136411](https://github.com/Superfast-Robotics/robot-skill-hub/actions/runs/39097136411) executed this exact `1.1.0` wrapper at Hub commit
`a248d21d5cd09afedb93461ca5208298b6123dd3` once at seed 0: `success=true`,
`terminated=true`, `truncated=false`, `71 / 1000` steps, exit 0,
and 4.575 seconds task process time without hitting the 180-second executor timeout.
The same maintainer agent explicitly selected the `panda-transport` named batch.
Ubuntu 22.04 CPU/state simulation used Mesa 23.2.1 lavapipe for Vulkan initialization,
with no physical GPU or output rendering. Exact outputs, environment and pins are
preserved in the [immutable evidence manifest](https://raw.githubusercontent.com/Superfast-Robotics/robot-skill-hub/039c103622c93e79d7b2ddb60dd0fc7345ebeab5/evidence/runtime/panda-transport-39097136411/manifest.json).

This establishes only the recorded seed and configuration under the Hub horizon.
Other seeds, upstream default benchmark completion, camera modes and physical robots
remain unverified. This maintainer run does not establish fresh blind discovery or public adoption.
