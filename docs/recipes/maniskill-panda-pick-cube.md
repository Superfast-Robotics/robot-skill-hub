## Recipe notes

The hub wrapper in `recipes/maniskill-panda-pick-cube/run.py` imports the original
ManiSkill `pick_cube.solve` implementation without copying or modifying it. The
original solver reads simulator object poses and uses MPlib motion planning.

The initial target is Linux x86_64 and Python 3.10. State observations and an
explicit CPU simulation backend and `render_backend="none"` are used. Setting
`render_mode=None` alone would leave the upstream GPU rendering backend enabled.
No camera observations, video recorder
or GUI are requested by the hub wrapper. The upstream demo runner has different
rendering defaults; do not substitute its invocation and assume the same hardware
requirements.

The source archive includes upstream LICENSE and any upstream attribution files;
retain them in prepared projects. Follow the original repository's contribution
rules for changes to upstream code. The hub API accepts only its own wrapper,
dependency metadata and documentation paths.

Runtime status: **not_run (미검증)**. A source review and checksum verification do
not prove dependency installation, imports or task completion on Linux.
