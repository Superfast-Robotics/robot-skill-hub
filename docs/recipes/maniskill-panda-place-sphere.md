# ManiSkill panda PlaceSphere-v1 motion planner

Pick up a sphere and place it into a bin with the official Panda planner.

## Source

- Repository: https://github.com/haosulab/ManiSkill
- Release: v3.0.0b22; commit `33967b9e3ead1f841eec57cc9f31d0d8b8cf0907`
- Solver: [mani_skill.examples.motionplanning.panda.solutions.place_sphere:solve](https://github.com/haosulab/ManiSkill/blob/33967b9e3ead1f841eec57cc9f31d0d8b8cf0907/mani_skill/examples/motionplanning/panda/solutions/place_sphere.py)
- License: [Apache-2.0](https://github.com/haosulab/ManiSkill/blob/33967b9e3ead1f841eec57cc9f31d0d8b8cf0907/LICENSE); robot/mesh assets retain upstream notices.
- Recipe ID: `maniskill-panda-place-sphere`
- Canonical JSON: https://hub.superfastrobotics.com/skills/maniskill-panda-place-sphere/skill.json

## Agent preparation

```sh
python skills/find-robot-skills/scripts/rsh.py inspect maniskill-panda-place-sphere --json
python skills/find-robot-skills/scripts/rsh.py prepare maniskill-panda-place-sphere --project ./experiment --plan --json
python skills/find-robot-skills/scripts/rsh.py prepare maniskill-panda-place-sphere --project ./experiment --download-only --json
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
This wrapper has no runtime-verification claim; inspect the current JSON evidence
for any later exact-version execution.
