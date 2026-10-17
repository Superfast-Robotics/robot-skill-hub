## Recipe notes

The hub wrapper in `recipes/maniskill-panda-stack-cube/run.py` imports the original
ManiSkill `stack_cube.solve` implementation without copying or modifying it. It
combines grasping, lifting and placement using ground-truth simulator state.

Use the same exact Linux x86_64 / Python 3.10 / Panda / `pd_joint_pos` target as
the PickCube recipe. Sharing the physics engine or robot name with another
framework does not make the solver portable. This recipe is not an RGB-only
policy and must not be presented as an equivalent visual-policy benchmark.

The wrapper sets `render_backend="none"` explicitly, as `render_mode=None`
alone does not disable ManiSkill's default GPU rendering backend. No GUI, video
or camera output is requested by the wrapper. Graphics examples
and other observation modes require their own compatibility checks. Preserve the
upstream Apache-2.0 license and original author notices in the downloaded source.

The canonical JSON keeps source inspection and simulator execution evidence in
separate fields. Consult those fields for the exact recorded environment.

## Verified Hub recipe 1.1.0 execution

[Run 39045603320](https://github.com/Superfast-Robotics/robot-skill-hub/actions/runs/39045603320)
executed this exact version at Hub commit
`3a1c17905e76bf58ed58fab17009aec3806e634a`, once at seed 0. StackCube returned
`success=true`, `terminated=true`, `truncated=false`, `elapsed_steps=107` and
`max_episode_steps=1000`, with exit 0 in 3.823 seconds and no process timeout.
This verifies the recorded CPU/state/Panda configuration under the Hub budget.
It does not establish completion within the upstream 50-step benchmark horizon.
See [the preserved evidence](../../evidence/runtime/llm-bounded-39045603320).

## Historical CPU execution

The earlier wrapper returned final-state `success=true` at 107 steps, seed 0,
exit 0 on Ubuntu 22.04 / Python 3.10.22 with CPU simulation and no output
rendering. The Vulkan device was CPU llvmpipe. This observation occurred beyond
the upstream 50-step episode budget, and the old wrapper did not check
truncation. The immutable outputs do not establish success within the standard
horizon or verify the changed wrapper. See
[the horizon audit](../verification.md#historical-linux-cpu-execution-and-horizon-audit).

The upstream solver grasps cube A, lifts it, moves it over cube B and opens the
gripper. StackCube's task criteria include stacking and release, unlike
PickCube's pick-and-carry objective. Numerical motion planning and simulator
joint control execute the motions; selecting this code with an LLM does not turn
the LLM into the trajectory planner.

Use the same Mesa lavapipe ICD and CPU torch setup documented in the PickCube
recipe. Pinned SAPIEN still initializes a Vulkan device for materials despite
`render_backend="none"`. Run the returned command separately under the documented
180-second external timeout. The recorded execution does not establish other
seeds, observation modes or hardware execution. Preserve its exact version and
environment when reusing the evidence.

## Hub episode horizon

Hub recipe version `1.1.0` explicitly sets `max_episode_steps=1000`, a Hub
motion-planning budget rather than an upstream default or standard benchmark.
The upstream source pin is unchanged. Completion requires `success=true`,
`truncated=false` and `0 < elapsed_steps < 1000`; final JSON includes `terminated`,
`truncated` and the configured horizon. `terminated` alone does not establish
success. The step budget and 180-second wall-clock timeout are separate limits.
The version-specific run above satisfies this contract; it does not verify the
upstream benchmark horizon.
