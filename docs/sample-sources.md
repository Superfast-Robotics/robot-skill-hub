# Official sample sources

The Hub contains two kinds of entries:

- **17 preparation recipes** wrap actual official ManiSkill motion-planning
  solvers with a pinned source archive, dependency recipe, isolated preparation,
  and a final JSON result contract.
- **651 source examples** point to immutable official files across 16 robotics
  ecosystems. They expose source and license hashes, imports, setup links,
  execution domains and entrypoints. They do not have a Hub preparation adapter.

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

The source index covers manipulation, navigation, inverse kinematics, dynamics,
joint control, robot learning, teleoperation, sensing, flight and legged robots.
Selection is finite and explicit; this is not an exhaustive inventory of all
robot skills on the internet.

| Official repository | Pinned release or branch label | Source examples |
| --- | --- | ---: |
| [Webots](https://github.com/cyberbotics/webots) | `R2025a` | 193 |
| [Pinocchio](https://github.com/stack-of-tasks/pinocchio) | `v4.1.0` | 76 |
| [Drake](https://github.com/RobotLocomotion/drake) | `v1.58.0` | 73 |
| [OMPL](https://github.com/ompl/ompl) | `2.0.2` | 47 |
| [Isaac Lab](https://github.com/isaac-sim/IsaacLab) | `v2.3.2` | 44 |
| [MoveIt 2 tutorials](https://github.com/moveit/moveit2_tutorials) | `main` | 36 |
| [LeRobot](https://github.com/huggingface/lerobot) | `v0.6.1` | 33 |
| [Robotics Toolbox for Python](https://github.com/petercorke/robotics-toolbox-python) | `v1.4.4` | 30 |
| [ROS 2 actions and executors](https://github.com/ros2/examples) | `jazzy` | 22 |
| [ros2_control demos](https://github.com/ros-controls/ros2_control_demos) | `jazzy` | 21 |
| [Bullet / PyBullet](https://github.com/bulletphysics/bullet3) | `3.25` | 20 |
| [PyRoboSim](https://github.com/sea-bass/pyrobosim) | `5.0.1` | 15 |
| [Crazyflie Python library](https://github.com/bitcraze/crazyflie-lib-python) | `0.1.34` | 12 |
| [robosuite](https://github.com/ARISE-Initiative/robosuite) | `v1.5.1` | 12 |
| [Nav2 Simple Commander](https://github.com/ros-navigation/navigation2) | `jazzy` | 9 |
| [MuJoCo](https://github.com/google-deepmind/mujoco) | `3.3.7` | 8 |

Every label above resolves to the full immutable commit in the source index.
These are stable source references, not a claim to use each project's latest
release. Repository stars, when present, are dated interest measurements rather
than skill usage or compatibility evidence.

The new manifest contains 611 accepted runnable source artifacts from 13
additional projects. Static inspection rejects library-only modules, native
files without `main`, unreviewed straight-line helper scripts and conflicting
explicit license identifiers. All 651 source files and their license pins were
downloaded and checked; no upstream example was executed by the importers.
The Webots portion includes 98 robot-specific controllers across 56 model
directories, plus device and controller examples.

Robot categories inferred from source paths are discovery labels. A project
supporting several robot families does not make every example compatible with
all of them. The pinned source, robot configuration and execution domain remain
the authority. The index distinguishes computation, simulation, middleware,
training and hardware workflows. Hardware examples can contain real motion;
they are not attached to automatic installation or execution.

The [source project manifest](../catalog/source-projects.json) records selection
roots, exact commits, license checksums, accepted source checksums and excluded
helper reasons. The [compact source index](../catalog/source-index.json) contains
the exact source identity used by contribution and memory APIs. Model assets,
datasets, policy weights, commercial simulator runtimes and dependencies retain
their separate upstream licenses; indexing a source reference does not copy
those artifacts or grant additional rights.

## Reproduce the index

```sh
# Use the existing pinned archive to inspect solver/task contracts.
python tools/import_official_samples.py --archive /path/to/maniskill.tar.gz --check

# Rebuild only the 15 new recipes; the two existing published records are kept.
python tools/import_official_samples.py

# Refresh the original three projects without deleting other import registries.
python tools/import_reference_examples.py --fetch

# Verify all reviewed ecosystem source and license pins from upstream.
python tools/import_ecosystem_examples.py --fetch --check

# Rebuild/validate from the local static-inspection cache without network access.
python tools/import_ecosystem_examples.py --check

# After reviewing a manifest commit/license change, explicitly inspect its tree.
python tools/import_ecosystem_examples.py --discover --project nav2 --fetch
```

Source refreshes preserve entries owned by other importers. Checksums, duplicate
source artifacts and duplicate IDs fail closed. A discovery or source fetch
failure stops publication; a partial tree is not accepted as complete coverage.
Import tools do not execute upstream modules, install simulators, download task
assets or run robots.
