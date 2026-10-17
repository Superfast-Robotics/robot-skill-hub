# Compatibility

The catalog wraps official ManiSkill 3.0.0b22 motion planners for Panda variants (`panda`, `panda_wristcam`), Panda Stick (`panda_stick`), xArm6 Robotiq (`xarm6_robotiq`) and SO100. Each recipe pins a full upstream commit and archive SHA-256. Requirements are recorded as complete combinations of task, robot, controller and runtime.

The preparation target is Linux x86_64, Python 3.10, `maniskill` 3.0.0b22, simulator state observations and one CPU simulation environment with rendering disabled. Consult each record for its exact robot, controller, package versions and command arguments. A state-based planner uses privileged simulator information; evaluate it separately from an RGB-only controller.

Records distinguish source review from runtime results. Task execution has not been demonstrated on this Windows development host; current recipes retain their recorded evidence levels. Source review and structural tests do not establish installation, import, success rate, hardware safety, performance improvement or compatibility with other ManiSkill releases. Video rendering and real hardware control are outside the current preparation scope.

Windows/macOS can read the public catalog. The local tool reports unsupported simulator OS rather than treating it as compatible. Unknown requirements remain unknown. Existing research locks remain unchanged until an explicit new preparation is requested.

The separate [official source example index](https://hub.superfastrobotics.com/catalog/v1/references.json) covers additional frameworks. Those entries support source browsing only. They are not preparation records, compatibility claims or local execution results; see [source selection notes](sample-sources.md).

Discovery can refresh its catalog and reference cache without changing a prepared project. Existing locks pin their original record/source and environment. Published task-memory queries use those exact record/source versions and known environment fields; unrelated versions or mismatches are excluded. A maintainer-merged memory remains contributor-reported reference data, not a verified compatibility or task-success claim.
