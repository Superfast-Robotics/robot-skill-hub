# Diverse robot simulation skills

The catalog now has 98 preparation recipes. The 36 additions below were executed on two isolated Lambda A100 hosts, using fixed inputs selected before execution. Thirty-four additions passed all three cases. Existing evidence plus these runs gives 84 completed recipes: 33 computations and 51 simulations. Physical robot completions remain zero.

| New cohort | Recipes | Fixed cases passed / attempted | Recipes completing every case |
| --- | ---: | ---: | ---: |
| MuJoCo robot control | 17 | 51 / 51 | 17 |
| Robosuite reaching and lifting | 12 | 33 / 36 | 11 |
| Gymnasium-Robotics manipulation and navigation | 6 | 18 / 18 | 6 |
| LeRobot Diffusion Policy PushT | 1 | 1 / 3 | 0 |

These authored regression cases are not a general benchmark success rate. Repeated attempts are retained separately rather than added to the current recipe counts. [Current receipts](../evidence/runtime/diverse-sim-v1/README.md) bind adapter bytes, source archives, selected source hashes, package versions, declared environments and exact inputs. [Initial attempts](../evidence/runtime/diverse-sim-v1/initial-attempts/README.md) retain the failures that informed changes.

## Robots, tasks and levels

MuJoCo 3.3.7 uses the pinned Menagerie revision `62ab00f2bc44f6f20c1c9b7a13f3fb1dd41a4e35`. Fifteen controllers move named position-actuated hinge joints: Piper, ALOHA, Panda, FR3, Stretch wrist/head, YAM, Gen3, iiwa14, Sawyer, SO101, SO100, Lite6, xArm7, UR10e and UR5e. Small-offset joint motion is a level-1 control primitive, not end-effector planning or arbitrary task completion. The nontrivial-motion checks require an achievable displacement of at least 0.03 rad. Model-specific limits can make a requested offset fail.

Unitree Go2 maintains standing for 3500 native steps with torque-limited joint PD, including reset-time base-velocity perturbations. The goal checks height, upright orientation and joint tracking; no walking capability is asserted. Shadow DexEE controls six explicitly named J2/J3 distal finger joints through the original PID plugin. It verifies finger curl, not all-joint hand posture, grasping or object manipulation. Earlier all-joint hand attempts remain in the initial receipts.

Robosuite 1.5.2 uses Panda, Sawyer, IIWA, UR5e, Jaco and Kinova3 with operational-space feedback. All six reaching controllers passed. Five cube grasp/lift recipes passed the native Lift objective and measured height check. **Jaco lifting failed all three cases** and is not labeled task-complete.

Gymnasium-Robotics 1.4.2 with MuJoCo 3.3.7 covers Fetch reach, push and pick/place, plus PointMaze U, Medium and Large. Native goal predicates are checked after bounded control. Objects are never teleported after reset. Airborne Fetch goals retain the grasp; ground goals release. Navigation uses a grid route and damped feedback, with a 3800-step ceiling.

LeRobot 0.3.3 and Torch 2.7.1 execute the original frozen `lerobot/diffusion_pusht` checkpoint at revision `84a7c23178445c6bbf7e1a884ff497017910f653`. RGB images and pusher position drive CUDA inference without an object-state oracle or training. Seeds 0, 1 and 2 achieved maximum target overlap of approximately 95.03%, 49.90% and 94.49%; only seed 0 reached the native >95% success threshold. The recipe remains below task-complete. PushT's internal pixel coordinates are not exposed as metric robot poses.

## Reproduce the fixed cases

Use a Linux x86_64 Python 3.10 host. Install the selected recipe's pinned requirements explicitly. MuJoCo needs the EGL/GL system libraries; Linux device dependencies of Robosuite/LeRobot may require a C compiler to build evdev. Only LeRobot policy inference requires CUDA. The other simulation physics/control runs use CPU on the A100 hosts.

```sh
python tools/generate_runtime_expansion.py --check
python tools/verify_runtime_expansion.py --backend menagerie \
  --source-cache /PATH/TO/CACHE --output ./receipts \
  --hub-commit EXACT_HUB_COMMIT --workers 4
```

The cache contains each checksum-verified archive named `<source_id>.tar.gz` and its extracted `source-<source_id>` tree. The complete source pins, guard hashes, cases, direct package versions and interfaces are in [runtime-expansion.json](../catalog/runtime-expansion.json). Use `--backend robosuite`, `gymrobotics` or `lerobot` for the other cohorts. Checkpoint config and safetensors bytes are pinned separately. No API credential or physical robot is required.

## Verify the actual reuse path

Four [fresh-project integration receipts](../evidence/runtime/diverse-sim-v1/prepared/README.md) record normal CLI preparation, explicit dependency installation, preserved adapter/license bytes, and successful execution of the returned command: Menagerie Panda, PointMaze U, Robosuite Panda Lift, and the LeRobot seed-0 example. This does not promote the other failed LeRobot seeds.

```sh
python tools/verify_prepared_runtime_expansion.py \
  --skill-id robosuite-panda-lift --source-cache /PATH/TO/CACHE \
  --project-root ./fresh-projects --output ./prepared-receipts
```

LeRobot preparation selects regular pinned source files because its archive contains documentation links that the extractor correctly rejects. The link/traversal rejection remains enabled. Selected source files and their original licenses are retained separately from the Hub's MIT adapter.

[Indexable examples](https://hub.superfastrobotics.com/samples/) provide input, environment and evidence in plain HTML, Markdown and JSON. Their inspection URLs pin the publication and record version. [Coverage](https://hub.superfastrobotics.com/coverage.html) separates computation, simulation, failed attempts and unexecuted recipes; source-reference presence is not execution evidence.
