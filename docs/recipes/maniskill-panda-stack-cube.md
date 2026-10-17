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

## Verified CPU-only execution

The exact wrapper completed StackCube-v1 seed 0 on Ubuntu 22.04 / Python 3.10.22:
`success=true`, 107 steps, exit 0, CPU simulation and no output rendering. The
Vulkan device was CPU llvmpipe; no physical GPU was used. The canonical record
links immutable package, hash and execution artifacts.

Use the same Mesa lavapipe ICD and CPU torch setup documented in the PickCube
recipe. Pinned SAPIEN still initializes a Vulkan device for materials despite
`render_backend="none"`. Run the returned command separately under the documented
180-second external timeout. Only the recorded seed and environment were tested;
this does not establish other seeds, observation modes or hardware execution.
