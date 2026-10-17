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
