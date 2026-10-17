# Official sample sources

The Hub contains two kinds of entries:

- **17 preparation recipes** wrap actual official ManiSkill motion-planning
  solvers with a pinned source archive, dependency recipe, isolated preparation,
  and a final JSON result contract.
- **40 source examples** point to immutable official MuJoCo, PyBullet, and
  robosuite files. They expose source hashes, licenses, imports, setup links and
  entrypoints. They do not have a Hub preparation adapter.

Read the [preparation catalog](https://hub.superfastrobotics.com/catalog/v1/index.json)
and [source example index](https://hub.superfastrobotics.com/catalog/v1/references.json)
directly as JSON. The [full text index](https://hub.superfastrobotics.com/llms-full.txt)
is available without browser scripting.

## Preparation recipes

All recipes use ManiSkill release `v3.0.0b22`, commit
`33967b9e3ead1f841eec57cc9f31d0d8b8cf0907`, with archive SHA-256
`d194e39e4f86063f7ea49f25c918ca7474d088ad8d5abdc37573daf4672f86d4`.
The archive is 243,636,110 bytes. The upstream code is Apache-2.0; robot models
and other assets retain their own notices.

| Robot UID | Official solver tasks | Count |
| --- | --- | ---: |
| `panda` | PickCube, StackCube, PushCube, PullCube, PullCubeTool, LiftPegUpright, PlaceSphere, StackPyramid | 8 |
| `panda_wristcam` | PegInsertionSide, PlugCharger | 2 |
| `panda_stick` | DrawTriangle, DrawSVG | 2 |
| `xarm6_robotiq` | PickCube, StackCube, PushCube, PlugCharger | 4 |
| `so100` | PickCubeSO100 | 1 |

The target environment is Linux x86_64 with Python 3.10, CPU simulation, state
observations and `pd_joint_pos`. Rendering is disabled. The drawing variants use
the stick-equipped robot; DrawSVG includes the optional SVG parser dependency.
The SO100 task supplies its robot UID in the environment subclass.

The xArm6 combinations come from the upstream xArm6 runner. Several upstream
task declarations list Panda/Fetch only and emit a warning for xArm6; the
source-level record preserves that distinction. The new adapters use sparse
rewards to avoid robot-specific dense reward code. Confirm any target combination
in your simulator environment before relying on it.

Source inspection, archive extraction and adapter contract tests are recorded
separately from simulator execution. The evidence fields retain the precise
runtime level; none of the additions claims a measured task success rate.

## Broader source examples

The selection favors official examples in widely followed simulator repositories
and common building blocks: inverse kinematics, inverse dynamics, Jacobians,
joint control, manipulation environments, teleoperation, sensing, domain
randomization, trajectory recording and replay.

| Official repository | Pinned release | Source examples | GitHub stars checked 2026-10-17 |
| --- | --- | ---: | ---: |
| [MuJoCo](https://github.com/google-deepmind/mujoco) | `3.3.7` / `f1d45bd5422c74beddfb0d1deb590a02583d21de` | 8 | 15,726 |
| [Bullet / PyBullet](https://github.com/bulletphysics/bullet3) | `3.25` / `2c204c49e56ed15ec5fcfa71d199ab6d6570b3f5` | 20 | 14,800 |
| [robosuite](https://github.com/ARISE-Initiative/robosuite) | `v1.5.1` / `a071383d53568ab798eb315c0e95357911be922d` | 12 | 2,666 |

Stars measure repository interest. They are not sample usage counts, install
counts, compatibility evidence, or a ranking of successful robot policies.
The pinned releases provide stable source links; they are not advertised as the
latest releases.

Every example points to a real Python script, official tutorial notebook, or
native C++ `main`. Source files were fetched at the exact commit and hashed;
Python imports, notebook cells, native entrypoints and repository licenses were
inspected. Read the source and upstream setup instructions before execution.
Some examples are interactive, run continuously, require OpenGL/input devices,
or expect adjacent assets, helper files, models or recorded logs. The MJX
tutorial requires a GPU runtime. No automatic dependency installation or source
execution is attached to these source references.

## Reproduce the index

```sh
# Use the existing pinned archive to inspect solver/task contracts.
python tools/import_official_samples.py --archive /path/to/maniskill.tar.gz --check

# Rebuild only the 15 new recipes; the two existing published records are kept.
python tools/import_official_samples.py

# Fetch immutable official source files for static inspection and SHA-256.
python tools/import_reference_examples.py --fetch

# Rebuild from the local source-inspection cache without network access.
python tools/import_reference_examples.py
```

Import tools only generate metadata and Hub adapters. They do not execute any
upstream module, install a simulator, download task assets or run a robot.
