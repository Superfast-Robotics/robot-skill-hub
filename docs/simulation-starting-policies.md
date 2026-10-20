# Simulation starting policies for AI agents

Robot Skill Hub is a public repository of reusable robot code and executable recipes. These 41 additions are starting solutions an agent can inspect, prepare and improve. They were actually executed without physical robots on an isolated Linux Python 3.10 Lambda A10 host. Physics and feedback used CPU; these runs do not require CUDA or a paid GPU to reproduce.

| Cohort | Added recipes | All three cases complete | Cases passed / attempted |
| --- | ---: | ---: | ---: |
| dmcontrol | 9 | 7 | 22 / 27 |
| menagerie | 15 | 15 | 45 / 45 |
| pandagym | 5 | 3 | 10 / 15 |
| robosuite | 12 | 7 | 25 / 36 |

The current catalog contains **139 preparation recipes: 116 complete, 12 failed current suites, 11 without a current task run, zero unbound completion claims and zero physical robot completions**. Completed evidence comprises 33 computations and 83 simulations across 54 tested environment combinations. Source references remain separate: 1,330 references across 44 frameworks.

These are finite, maintainer-authored regression cases, not a general task success rate. The 123 new fixed cases contain 102 passes and 21 failures. All 82 unknown-field and source-drift rejection checks passed. All cases were selected before execution. The latest attempt for each exact adapter is retained as current; earlier failed or successful attempts remain in the [history](../evidence/runtime/diverse-sim-v1/initial-attempts/seed-expansion/). A later adapter never inherits an earlier success.

## Reusable control levels

The 15 new Menagerie recipes are **level-1 joint-control primitives**: ARX L5, Dynamixel 2R, Flexiv Rizon4 and Rizon4s, FR3 v2, Google Robot, Stretch 3, Low Cost Robot Arm, Robotis OMY 3M, ReBot DevArm, TidyBot, ViperX 300S, WidowX 250S, bimanual WXAI, and Unitree Z1. Only the explicitly listed position-actuated hinge joints are controlled. Fixed-base/support assumptions come from the pinned scene. This does not validate mobile-base navigation, humanoid balance, object tasks or hardware. ARX, Rizon4s, ViperX and WXAI use bounded integral setpoint compensation for static load while preserving the same measured joint goal.

The 26 level-2 candidates include Panda Gym reach/push/pick-place/slide/stack, six Robosuite embodiments performing stack and can-to-bin tasks, and nine DM Control task variants. Goal checks use native task predicates plus measured geometric errors, or a complete final 100-step native reward window. DM Control reward thresholds are task-specific; they are not a common accuracy score. Reacher uses constrained IK and dynamic feedback. Cartpole controller linearization uses a separate copied Euler model; actual native RK4 simulation is preserved. No active object or joint state is teleported after reset.

## Inputs, coordinates and reuse

Each recipe exposes bounded JSON input and one JSON stdout object. Metric position arrays specify metres and a world frame; joint arrays declare radians and exact joint order. Native DM Control state stays within its model frame. No automatic frame conversion or hardware actuation is enabled. Upstream code/assets retain their original notices; independent Hub adapters are MIT.

Panda Gym uses native PyBullet IK in headless rgb_array mode without requesting frames. Native Bullet diagnostics are redirected to stderr so ordinary CLI callers receive valid single-object JSON. DM Control needs generated MuJoCo bindings supplied in the pinned distribution; runtime Python/XML files are compared against the immutable source archive. Non-runtime demonstration files omitted by its wheel are not asserted to execute. Source selection preserves regular source and license files; archive link/traversal guards remain enabled.

Search or read the [static samples](https://hub.superfastrobotics.com/samples/) without installing anything. Each sample includes environment, input, canonical contract, source pin and evidence. Preparation and execution are separate explicit actions.

## New recipes

| Recipe and sample | Level | Complete cases | Evidence |
| --- | ---: | ---: | --- |
| [arx l5 joint-position control](https://hub.superfastrobotics.com/samples/mujoco-arx-l5-joint-control/) | 1 | 3 / 3 | [Receipt](../evidence/runtime/diverse-sim-v1/mujoco-arx-l5-joint-control.json) |
| [dynamixel 2r joint-position control](https://hub.superfastrobotics.com/samples/mujoco-dynamixel-2r-joint-control/) | 1 | 3 / 3 | [Receipt](../evidence/runtime/diverse-sim-v1/mujoco-dynamixel-2r-joint-control.json) |
| [flexiv rizon4 joint-position control](https://hub.superfastrobotics.com/samples/mujoco-flexiv-rizon4-joint-control/) | 1 | 3 / 3 | [Receipt](../evidence/runtime/diverse-sim-v1/mujoco-flexiv-rizon4-joint-control.json) |
| [flexiv rizon4s joint-position control](https://hub.superfastrobotics.com/samples/mujoco-flexiv-rizon4s-joint-control/) | 1 | 3 / 3 | [Receipt](../evidence/runtime/diverse-sim-v1/mujoco-flexiv-rizon4s-joint-control.json) |
| [franka fr3 v2 joint-position control](https://hub.superfastrobotics.com/samples/mujoco-franka-fr3-v2-joint-control/) | 1 | 3 / 3 | [Receipt](../evidence/runtime/diverse-sim-v1/mujoco-franka-fr3-v2-joint-control.json) |
| [google robot joint-position control](https://hub.superfastrobotics.com/samples/mujoco-google-robot-joint-control/) | 1 | 3 / 3 | [Receipt](../evidence/runtime/diverse-sim-v1/mujoco-google-robot-joint-control.json) |
| [hello robot stretch 3 joint-position control](https://hub.superfastrobotics.com/samples/mujoco-hello-robot-stretch-3-joint-control/) | 1 | 3 / 3 | [Receipt](../evidence/runtime/diverse-sim-v1/mujoco-hello-robot-stretch-3-joint-control.json) |
| [low cost robot arm joint-position control](https://hub.superfastrobotics.com/samples/mujoco-low-cost-robot-arm-joint-control/) | 1 | 3 / 3 | [Receipt](../evidence/runtime/diverse-sim-v1/mujoco-low-cost-robot-arm-joint-control.json) |
| [robotis omy 3m joint-position control](https://hub.superfastrobotics.com/samples/mujoco-robotis-omy-3m-joint-control/) | 1 | 3 / 3 | [Receipt](../evidence/runtime/diverse-sim-v1/mujoco-robotis-omy-3m-joint-control.json) |
| [seeed rebot devarm joint-position control](https://hub.superfastrobotics.com/samples/mujoco-seeed-rebot-devarm-joint-control/) | 1 | 3 / 3 | [Receipt](../evidence/runtime/diverse-sim-v1/mujoco-seeed-rebot-devarm-joint-control.json) |
| [stanford tidybot joint-position control](https://hub.superfastrobotics.com/samples/mujoco-stanford-tidybot-joint-control/) | 1 | 3 / 3 | [Receipt](../evidence/runtime/diverse-sim-v1/mujoco-stanford-tidybot-joint-control.json) |
| [trossen vx300s joint-position control](https://hub.superfastrobotics.com/samples/mujoco-trossen-vx300s-joint-control/) | 1 | 3 / 3 | [Receipt](../evidence/runtime/diverse-sim-v1/mujoco-trossen-vx300s-joint-control.json) |
| [trossen wx250s joint-position control](https://hub.superfastrobotics.com/samples/mujoco-trossen-wx250s-joint-control/) | 1 | 3 / 3 | [Receipt](../evidence/runtime/diverse-sim-v1/mujoco-trossen-wx250s-joint-control.json) |
| [trossen wxai joint-position control](https://hub.superfastrobotics.com/samples/mujoco-trossen-wxai-joint-control/) | 1 | 3 / 3 | [Receipt](../evidence/runtime/diverse-sim-v1/mujoco-trossen-wxai-joint-control.json) |
| [unitree z1 joint-position control](https://hub.superfastrobotics.com/samples/mujoco-unitree-z1-joint-control/) | 1 | 3 / 3 | [Receipt](../evidence/runtime/diverse-sim-v1/mujoco-unitree-z1-joint-control.json) |
| [Panda Gym Reach closed-loop starting policy](https://hub.superfastrobotics.com/samples/pandagym-panda-reach/) | 2 | 3 / 3 | [Receipt](../evidence/runtime/diverse-sim-v1/pandagym-panda-reach.json) |
| [Panda Gym Push closed-loop starting policy](https://hub.superfastrobotics.com/samples/pandagym-panda-push/) | 2 | 1 / 3 | [Receipt](../evidence/runtime/diverse-sim-v1/pandagym-panda-push.json) |
| [Panda Gym PickAndPlace closed-loop starting policy](https://hub.superfastrobotics.com/samples/pandagym-panda-pick-place/) | 2 | 3 / 3 | [Receipt](../evidence/runtime/diverse-sim-v1/pandagym-panda-pick-place.json) |
| [Panda Gym Slide closed-loop starting policy](https://hub.superfastrobotics.com/samples/pandagym-panda-slide/) | 2 | 0 / 3 | [Receipt](../evidence/runtime/diverse-sim-v1/pandagym-panda-slide.json) |
| [Panda Gym Stack closed-loop starting policy](https://hub.superfastrobotics.com/samples/pandagym-panda-stack/) | 2 | 3 / 3 | [Receipt](../evidence/runtime/diverse-sim-v1/pandagym-panda-stack.json) |
| [DM Control reacher easy feedback policy](https://hub.superfastrobotics.com/samples/dmcontrol-reacher-easy/) | 2 | 3 / 3 | [Receipt](../evidence/runtime/diverse-sim-v1/dmcontrol-reacher-easy.json) |
| [DM Control reacher hard feedback policy](https://hub.superfastrobotics.com/samples/dmcontrol-reacher-hard/) | 2 | 3 / 3 | [Receipt](../evidence/runtime/diverse-sim-v1/dmcontrol-reacher-hard.json) |
| [DM Control point mass easy feedback policy](https://hub.superfastrobotics.com/samples/dmcontrol-point-mass-easy/) | 2 | 3 / 3 | [Receipt](../evidence/runtime/diverse-sim-v1/dmcontrol-point-mass-easy.json) |
| [DM Control point mass hard feedback policy](https://hub.superfastrobotics.com/samples/dmcontrol-point-mass-hard/) | 2 | 3 / 3 | [Receipt](../evidence/runtime/diverse-sim-v1/dmcontrol-point-mass-hard.json) |
| [DM Control cartpole balance feedback policy](https://hub.superfastrobotics.com/samples/dmcontrol-cartpole-balance/) | 2 | 3 / 3 | [Receipt](../evidence/runtime/diverse-sim-v1/dmcontrol-cartpole-balance.json) |
| [DM Control cartpole balance sparse feedback policy](https://hub.superfastrobotics.com/samples/dmcontrol-cartpole-balance-sparse/) | 2 | 3 / 3 | [Receipt](../evidence/runtime/diverse-sim-v1/dmcontrol-cartpole-balance-sparse.json) |
| [DM Control pendulum swingup feedback policy](https://hub.superfastrobotics.com/samples/dmcontrol-pendulum-swingup/) | 2 | 3 / 3 | [Receipt](../evidence/runtime/diverse-sim-v1/dmcontrol-pendulum-swingup.json) |
| [DM Control finger spin feedback policy](https://hub.superfastrobotics.com/samples/dmcontrol-finger-spin/) | 2 | 0 / 3 | [Receipt](../evidence/runtime/diverse-sim-v1/dmcontrol-finger-spin.json) |
| [DM Control ball in cup catch feedback policy](https://hub.superfastrobotics.com/samples/dmcontrol-ball-in-cup-catch/) | 2 | 1 / 3 | [Receipt](../evidence/runtime/diverse-sim-v1/dmcontrol-ball-in-cup-catch.json) |
| [Panda two-cube stack](https://hub.superfastrobotics.com/samples/robosuite-panda-stack/) | 2 | 3 / 3 | [Receipt](../evidence/runtime/diverse-sim-v1/robosuite-panda-stack.json) |
| [Panda can pick and place into bin](https://hub.superfastrobotics.com/samples/robosuite-panda-pick-place-can/) | 2 | 3 / 3 | [Receipt](../evidence/runtime/diverse-sim-v1/robosuite-panda-pick-place-can.json) |
| [Sawyer two-cube stack](https://hub.superfastrobotics.com/samples/robosuite-sawyer-stack/) | 2 | 3 / 3 | [Receipt](../evidence/runtime/diverse-sim-v1/robosuite-sawyer-stack.json) |
| [Sawyer can pick and place into bin](https://hub.superfastrobotics.com/samples/robosuite-sawyer-pick-place-can/) | 2 | 0 / 3 | [Receipt](../evidence/runtime/diverse-sim-v1/robosuite-sawyer-pick-place-can.json) |
| [IIWA two-cube stack](https://hub.superfastrobotics.com/samples/robosuite-iiwa-stack/) | 2 | 2 / 3 | [Receipt](../evidence/runtime/diverse-sim-v1/robosuite-iiwa-stack.json) |
| [IIWA can pick and place into bin](https://hub.superfastrobotics.com/samples/robosuite-iiwa-pick-place-can/) | 2 | 3 / 3 | [Receipt](../evidence/runtime/diverse-sim-v1/robosuite-iiwa-pick-place-can.json) |
| [UR5e two-cube stack](https://hub.superfastrobotics.com/samples/robosuite-ur5e-stack/) | 2 | 3 / 3 | [Receipt](../evidence/runtime/diverse-sim-v1/robosuite-ur5e-stack.json) |
| [UR5e can pick and place into bin](https://hub.superfastrobotics.com/samples/robosuite-ur5e-pick-place-can/) | 2 | 3 / 3 | [Receipt](../evidence/runtime/diverse-sim-v1/robosuite-ur5e-pick-place-can.json) |
| [Jaco two-cube stack](https://hub.superfastrobotics.com/samples/robosuite-jaco-stack/) | 2 | 0 / 3 | [Receipt](../evidence/runtime/diverse-sim-v1/robosuite-jaco-stack.json) |
| [Jaco can pick and place into bin](https://hub.superfastrobotics.com/samples/robosuite-jaco-pick-place-can/) | 2 | 0 / 3 | [Receipt](../evidence/runtime/diverse-sim-v1/robosuite-jaco-pick-place-can.json) |
| [Kinova3 two-cube stack](https://hub.superfastrobotics.com/samples/robosuite-kinova3-stack/) | 2 | 2 / 3 | [Receipt](../evidence/runtime/diverse-sim-v1/robosuite-kinova3-stack.json) |
| [Kinova3 can pick and place into bin](https://hub.superfastrobotics.com/samples/robosuite-kinova3-pick-place-can/) | 2 | 3 / 3 | [Receipt](../evidence/runtime/diverse-sim-v1/robosuite-kinova3-pick-place-can.json) |

## Reproduce

Use Linux x86_64 and Python 3.10. Explicitly install the selected recipe requirements and EGL/GL system libraries where required. Use the checksum-verified archives and their extracted source trees in a local cache.

```sh
python tools/generate_runtime_expansion.py --check
python tools/verify_runtime_expansion.py --backend dmcontrol \
  --source-cache SOURCE_CACHE --output ./receipts \
  --hub-commit EXACT_HUB_COMMIT --workers 4
```

Use repeated `--skill-id ID` arguments to evaluate only chosen recipes. Unknown or mismatched selections are rejected. `--describe` inspects the contract without importing a simulator. Full pins, case inputs and source guards are in [the manifest](../catalog/runtime-expansion.json).

Four new fresh-project preparation proofs cover Panda Gym stacking, DM Control randomized point-mass control, Robosuite Panda stacking and load-compensated ARX joint control. They preserve adapter and MIT license bytes and execute the ordinary command returned by prepare; see [preparation evidence](../evidence/runtime/diverse-sim-v1/prepared/).
