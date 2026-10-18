# ASPIRE and real-platform source expansion

Reviewed on 2026-10-19 (Asia/Seoul). The [frozen manifest](../catalog/curated-source-projects.json) adds 32 source references across three official repositories. The total catalog is 17 preparation recipes and 1,330 references. These additions are source references, not new Hub execution adapters or hardware verification.

| Official source | Exact commit | Selection |
| --- | --- | --- |
| [NVIDIA ASPIRE](https://github.com/NVlabs/ASPIRE/tree/fa00f0ef2bc1d91d594b9aa502c22133c9f538f7) | `fa00f0ef2bc1d91d594b9aa502c22133c9f538f7` | 13: five agent instruction guides, five simulation programs and three real YAM program fragments |
| [Franka libfranka](https://github.com/frankarobotics/libfranka/tree/e88d08f64cbf842b8f53c0b551963684064038d6) | `e88d08f64cbf842b8f53c0b551963684064038d6` | Nine C++ examples for state, grasping, Cartesian/joint motion, impedance, force and frame poses |
| [Hello Robot Stretch Body](https://github.com/hello-robot/stretch_body/tree/92c9db0cc9ade6535f822e83bbf10cbd0c68136a) | `92c9db0cc9ade6535f822e83bbf10cbd0c68136a` | Ten Python tools for homing, stowing, monitoring, battery checks, teleoperation and trajectories |

Each entry retains its exact source SHA-256, byte count, Git blob, author notices, source-scoped Apache-2.0 license and pinned setup evidence. The importer parses text and Python ASTs without importing or following upstream instructions. Claude/Codex copies of the same ASPIRE guides are not counted twice. Rebuild with `python tools/import_curated_sources.py --cache PATH --fetch --check`; normal cached checks need no network.

ASPIRE instruction documents describe iterative debugging, evolutionary search and separate development/held-out evaluation. They are data for inspection, not automatically installed skills or authority to launch workers. Its CAP examples depend on the runner's injected API and services. Real YAM requires station calibration, arm servers, cameras and the upstream motion interlock; the pinned runbook says starting a server energizes motors. Its simulation provider stack has separate GPU, gated weights and asset requirements. None of those services or robots were started here.

Franka examples target the pinned 0.21.3 source and its C++17/CMake dependencies. Controller/FCI compatibility, real-time networking, payload and collision parameters require upstream setup. Example targets are not verified operating values for an installed robot. Pose inspection uses live robot state; it is not an offline IK solver.

Stretch's pinned README covers **Stretch 1–3**, with Stretch 4 in a separate repository. Selected `tools/` sources carry their own Apache-2.0 license; the `body/` dependency retains its separate declarations, including its package metadata's LGPL classifier. Several tools execute at import time. Homing checks remote update metadata. Arm/lift jogging explicitly calls `disable_runstop`; these tools are source references for deliberate upstream integration, not default autonomous motion commands.

All 32 entries retain `source_reviewed` and `runtime_verification: not_run`. Existing real-platform references (including LeRobot, Unitree, xArm, UR RTDE, MAVSDK and Spot) remain available. No physical robot, simulator, GPU instance, policy weight or gated dataset was used in this expansion.
