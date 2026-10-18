# ManiSkill panda StackPyramid-v1 motion planner

Arrange three cubes into a pyramid using the official Panda planner.

## Source

- Repository: https://github.com/haosulab/ManiSkill
- Release: v3.0.0b22; commit `33967b9e3ead1f841eec57cc9f31d0d8b8cf0907`
- Solver: [mani_skill.examples.motionplanning.panda.solutions.stack_pyramid:solve](https://github.com/haosulab/ManiSkill/blob/33967b9e3ead1f841eec57cc9f31d0d8b8cf0907/mani_skill/examples/motionplanning/panda/solutions/stack_pyramid.py)
- License: [Apache-2.0](https://github.com/haosulab/ManiSkill/blob/33967b9e3ead1f841eec57cc9f31d0d8b8cf0907/LICENSE); robot/mesh assets retain upstream notices.
- Recipe ID: `maniskill-panda-stack-pyramid`
- Canonical JSON: https://hub.superfastrobotics.com/skills/maniskill-panda-stack-pyramid/skill.json

## Agent preparation

```sh
python skills/find-robot-skills/scripts/rsh.py inspect maniskill-panda-stack-pyramid --json
python skills/find-robot-skills/scripts/rsh.py prepare maniskill-panda-stack-pyramid --project ./experiment --plan --json
python skills/find-robot-skills/scripts/rsh.py prepare maniskill-panda-stack-pyramid --project ./experiment --download-only --json
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

## Recorded task failure

[Run 39100095436](https://github.com/Superfast-Robotics/robot-skill-hub/actions/runs/39100095436)
installed and executed this exact `1.1.0` wrapper once at seed 0 on Linux x86_64 /
Python 3.10.22 with CPU/state observations and Mesa lavapipe. The process returned
`success=false`, `task_objective_not_reached`, 176 steps, `terminated=false`,
`truncated=false` and exit 1 after 5.678 seconds. It did not hit the executor's
180-second timeout or the Hub 1000-step horizon. The pinned task's default horizon
is 250; this attempt is not a default-horizon benchmark.

The [immutable manifest](https://raw.githubusercontent.com/Superfast-Robotics/robot-skill-hub/e81d47efc18f98d811e12fea0b8b5622a2dbbeaf/evidence/runtime/panda-stacking-39100095436/manifest.json)
preserves exact outputs, command metadata, environment, dependency freeze and
software-device evidence. `import_verified` records the passed setup/import
stage, while `evidence.hub_verification.last_task_attempt.status=failed` records
the failed objective. Compatibility remains `source_reviewed`, with no successful
task-completion claim. The final result contains no detailed objective
subconditions, and the initial-pose warning does not establish a cause. This is
one maintainer-selected invocation, with no automatic retry, independent adoption,
camera, physical GPU or hardware result.
