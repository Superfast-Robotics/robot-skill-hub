# Official sample sources

The Hub contains two kinds of entries:

- **17 preparation recipes** wrap actual official ManiSkill motion-planning
  solvers with a pinned source archive, dependency recipe, isolated preparation,
  and a final JSON result contract.
- **The earlier baseline of 1,060 official source references** covers 651
  runnable-source examples and
  409 robot model, description and configuration text artifacts across 19
  official robotics repositories. They expose immutable source and applicable license
  hashes, setup links and exact inspection limits. They have no Hub preparation
  adapter. The catalog also accepts separately reviewed intake references.

Later finite selections add **56 policy and hardware workflow entrypoints** and
**43 robot-agent instruction documents**. Their source-review notes below preserve
the baseline counts and evidence separately.

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

## Broader source examples (baseline selection)

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

The runnable-example manifest contains 611 accepted source artifacts from 13
additional projects. Static inspection rejects library-only modules, native
files without `main`, unreviewed straight-line helper scripts and conflicting
explicit license identifiers. All 651 source files and their license pins were
downloaded and checked; no upstream example was executed by the importers.
The Webots portion includes 98 robot-specific controllers across 56 model
directories, plus device and controller examples.

## Robot models, descriptions and configuration

The [artifact manifest](../catalog/artifact-projects.json) adds **409 official
text artifacts** beyond executable examples. Each source file has its own
immutable commit, SHA-256, byte size, artifact kind and format. Its applicable
license file is pinned and hashed separately. Existing example records and IDs
are preserved.

| Official repository | Immutable commit | Text artifacts |
| --- | --- | ---: |
| [MuJoCo Menagerie](https://github.com/google-deepmind/mujoco_menagerie/tree/62ab00f2bc44f6f20c1c9b7a13f3fb1dd41a4e35) | `62ab00f2bc44f6f20c1c9b7a13f3fb1dd41a4e35` | 221: 219 MJCF and 2 URDF |
| [Universal Robots description](https://github.com/UniversalRobots/Universal_Robots_ROS2_Description/tree/d4042c1f5123c86645cc5dbd650b4f461f697ee9) | `d4042c1f5123c86645cc5dbd650b4f461f697ee9` | 65: 57 YAML and 8 Xacro |
| [Franka description](https://github.com/frankarobotics/franka_description/tree/7aeeddc449edf8d62b594f9e36a81da53e7796f9) | `7aeeddc449edf8d62b594f9e36a81da53e7796f9` | 72: 33 YAML and 39 Xacro |
| [ros2_control demos](https://github.com/ros-controls/ros2_control_demos/tree/3c35e783e268e5235bb042a71c68112a3ecb777e) | `3c35e783e268e5235bb042a71c68112a3ecb777e` | 51: 35 YAML and 16 Xacro |

Menagerie entries use **69 model-directory license files**, rather than a
single repository-wide license. The selection includes model definitions,
model components and scenes for arms, grippers, legged robots, humanoids,
mobile manipulators and aerial robots. Model-specific pinned README links
explain upstream simulator versions and adjacent assets.

The description/configuration selection covers nominal kinematics, inertial
parameters, joint limits, semantic robot groups and controller parameters.
Universal Robots' newer meshes have separate graphical-documentation terms;
the BSD-3-Clause scope recorded here covers selected description/configuration
text and does not grant rights to those meshes. Nominal kinematics are not
robot-specific calibration.

The importer downloaded and checked all 409 selected source files and 72
applicable license files. It parsed XML syntax, recorded direct include/mesh
references and inspected YAML mapping-key shape. It did not evaluate Xacro,
resolve includes, load models, deploy controller parameters or run a simulator.
YAML syntax/semantics and compatibility remain unverified. Source-only evidence
does not increase the number of runtime-verified preparation recipes.

A [sanitized ingestion receipt](../evidence/sources/robot-artifacts-2026-10-18.json)
records the exact manifest checksum, immutable repository commits, counts and
checks performed. This finite selection does not cover every model or parameter
file in these repositories.

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

## Policy and hardware workflows

The [workflow source review](workflow-sources.md) documents **56 additional
operational Python entrypoints**: 11 OpenPI, 10 robomimic, 18 Unitree SDK2 Python,
9 LeRobot CLIs and 8 Isaac Lab RL train/play scripts. The
[frozen workflow manifest](../catalog/workflow-projects.json) pins source,
applicable license, author and setup evidence. These are source references with
no Hub preparation adapter; policy performance and hardware compatibility were
not tested. The earlier 1,060 records remain unchanged.

## Robot-agent instruction sources

The [agent instruction source review](agent-skill-sources.md) documents **43
GaP bundle entry documents** from `graph-robots/open-robot-skills`: 33 skill,
8 tool and 2 policy contracts. The [frozen manifest](../catalog/agent-skill-projects.json)
and [sanitized receipt](../evidence/sources/agent-instructions-2026-10-18.json)
record exact source hashes and scope. Eleven MIT frontmatter declarations differ
from the repository's Apache-2.0 declaration and remain `NOASSERTION` with
`verified: false`. Requirements and behavior descriptions are upstream text
declarations; the Hub followed no bundle instructions and verified no runtime
or robot compatibility. All entries remain `not_run` and have no Hub adapter.

## Ruckig Community trajectories

The [Ruckig source review](../docs/ruckig-sources.md) adds seven pinned Community
trajectory-generation examples for position, velocity, stopping, minimum
duration and C++ integration. These numerical examples have no Hub execution
adapter and remain `runtime_verification: not_run`.

## UR RTDE control and I/O

The [UR RTDE source review](../docs/ur-rtde-sources.md) describes three pinned SDU
Robotics examples: the existing basic-motion reference plus joint-servo and
digital/analog I/O sources. These GitLab-hosted references use upstream setup,
have no Hub execution adapter and remain `runtime_verification: not_run`.

## Genesis World IK and grasping

The [Genesis World source review](../docs/genesis-sources.md) describes one pinned
Panda tutorial for inverse kinematics, joint-path planning, position control and
gripper force in CPU simulation. The source requires a viewer and upstream model
assets, has no Hub execution adapter and remains `runtime_verification: not_run`.

## Klampt IK, waypoint planning and pose control

The [Klampt source review](../docs/klampt-sources.md) distinguishes an IK library
module from two guarded planning and pose-control programs. The pose interface
may control hardware; examples retain unresolved upstream attribution. These
source references have no Hub adapter and remain `runtime_verification: not_run`.

## ROS 2 tf2 frames and following

The [ROS 2 tf2 source review](../docs/ros2-tf2-sources.md) describes two registered
console-entrypoint nodes for transform broadcasting and frame-based turtle
following. Component Apache/BSD terms and ROS graph effects are explicit. These
source references have no Hub adapter and remain `runtime_verification: not_run`.

## Nav2 controller and planner plugins

The [Nav2 plugin source review](../docs/nav2-plugin-sources.md) adds MPPI controller
integration, regulated pure pursuit and Smac Hybrid-A* implementation references
beyond the existing Simple Commander clients. These C++ plugins require configured
Nav2 hosts, have no Hub adapter and remain `runtime_verification: not_run`.

## robot_localization state estimation

The [robot_localization source review](../docs/robot-localization-sources.md)
adds the EKF prediction/correction library implementation with explicit selected-file
BSD and package-level Apache declarations. It is not a standalone sensor-fusion
node, has no Hub adapter and remains `runtime_verification: not_run`.

## ros2_controllers implementations

The [ros2_controllers source review](../docs/ros2-controller-sources.md) adds
joint trajectory and differential-drive plugin implementations beyond the
existing demo configuration/launch references. Their command-interface writes,
ROS graph effects and complete-package requirements are explicit. Both remain
source-only with unknown compatibility and `runtime_verification: not_run`.

The [joint-state broadcaster review](../docs/ros2-joint-state-broadcaster-source.md)
adds its actual state-interface-to-ROS-message implementation, class header and
registration/build contracts. It requests no command interfaces and remains
source-only with unknown compatibility and `runtime_verification: not_run`.

## ViSP image-based visual servoing

The [ViSP source review](../docs/visp-sources.md) adds one four-point IBVS C++
tutorial using a numerical free-flying camera. GPL project scope and absent
individual file attribution are explicit. It has no Hub adapter and remains
`runtime_verification: not_run` with unknown compatibility.

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

# Verify the explicit robot-description/model/controller text pins upstream.
python tools/import_robot_artifacts.py --fetch --check

# Check those artifacts and the additive source indexes from local cached text.
python tools/import_robot_artifacts.py --check

# Validate frozen workflow source, license and author/setup text offline.
python tools/import_robot_workflows.py --check

# Validate frozen agent instruction/provenance text as inert data offline.
python tools/import_agent_skill_sources.py --check

# Check reviewed ROS 2 plugin registrations against pinned local files.
python tools/import_robot_plugins.py --check

# After reviewing a manifest commit/license change, explicitly inspect its tree.
python tools/import_ecosystem_examples.py --discover --project nav2 --fetch
```

Source refreshes preserve entries owned by other importers. Checksums, duplicate
source artifacts and duplicate IDs fail closed. A discovery or source fetch
failure stops publication; a partial tree is not accepted as complete coverage.
Import tools do not execute upstream modules, install simulators, download task
assets or run robots.

For the plugin manifest, cache layout and draft submission commands, see
[ROS 2 plugin intake](robot-plugin-import.md).
