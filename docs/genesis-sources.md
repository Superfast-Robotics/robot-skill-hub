# Genesis World source review

The catalog references one [Genesis World IK, motion-planning and grasp tutorial](https://github.com/Genesis-Embodied-AI/genesis-world/blob/50a2aa19cba6f3e1afdceb0fac239a56a0ef5502/examples/tutorials/IK_motion_planning_grasp.py), pinned to commit `50a2aa19cba6f3e1afdceb0fac239a56a0ef5502`. The repository was renamed from `Genesis-Embodied-AI/Genesis` to `Genesis-Embodied-AI/genesis-world`; official GitHub responses identify the canonical location. The [source evidence](../evidence/sources/genesis-2026-10-18.json) records exact source, Apache-2.0 license and setup hashes.

| Source | Bytes | Static source behavior |
| --- | ---: | --- |
| `examples/tutorials/IK_motion_planning_grasp.py` | 2,508 | Panda inverse kinematics, joint-path planning, position control, gripper force and simulated cube lifting |

The script explicitly calls `gs.init(backend=gs.cpu)` and sets `show_viewer=True`. It has no CPU/GPU command-line switch. This selected source requests CPU simulation and needs a working viewer/graphics environment; no framework-wide backend default or tested environment is inferred. Its `dt=0.01` and waypoint/loop counts are source parameters, not measured timing or successful task completion.

There is no main guard. Importing or executing the original file initializes Genesis, constructs the viewer-enabled scene, loads the Panda MJCF, sets gains and force limits for nine DOFs, solves pre-grasp IK, opens the fingers, plans and draws a path, advances simulation while commanding positions, reaches toward the cube, applies finger force and lifts. It prints two joint configurations. The `PYTEST_VERSION` environment check shortens waypoints and loops; it is not evidence that this review ran a test. The selected file contains no hardware controller connection. Imported library initialization and transitive effects were not exhaustively audited.

The pinned README declares Python >=3.10,<3.14, PyTorch installation before Genesis and separate CPU/CUDA installation options. The tutorial directly imports Genesis and NumPy. It also requires `xml/franka_emika_panda/panda.xml` and adjacent assets: the immutable source tree lists the MJCF and meshes, but those bytes and model-specific licenses were not retrieved or reviewed. A copy of this Python file alone is insufficient to run the example. The exact planning backend and transitive package requirements remain unreviewed; a `plan_path` call does not identify its implementation.

The Apache-2.0 review covers the selected Python source under the pinned repository declaration. Preserve upstream attribution, license and applicable notices when redistributing. Robot descriptions, meshes, binaries and dependencies retain their own terms. This source-only curation does not clear those assets or install, load or redistribute them.

The record uses `access.mode: source_reference`, `hub_prepare: false`, source-review evidence and `runtime_verification: not_run`. Every required compatibility dimension and its status remain `unknown`; the declared README Python range is a requirement, not a tested Python combination. This maintainer curation creates no API submission receipt, changes no ecosystem importer and claims no popularity metric. No upstream package was imported, installed or executed; no simulator, controller, robot, GPU or cloud account was used.
