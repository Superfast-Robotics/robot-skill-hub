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

The canonical JSON keeps source inspection and simulator execution evidence in
separate fields. Consult those fields for the exact recorded environment.

## Historical CPU execution

The earlier wrapper returned final-state `success=true` at 74 steps, seed 0,
exit 0 on Ubuntu 22.04 / Python 3.10.22 with a CPU llvmpipe Vulkan device. This
was beyond the upstream 50-step episode budget, and the old wrapper did not check
truncation. Its immutable output establishes a final-state observation, not
success within the standard horizon or verification of the changed wrapper.
See [the horizon audit](../verification.md#historical-linux-cpu-execution-and-horizon-audit).

The upstream objective requires the cube at the goal and a stationary arm. The
solver keeps the gripper closed: this is pick-and-carry, with no release or
placement-on-support requirement. Python computes target poses from simulator
geometry; the numerical motion planner produces joint trajectories, and the
`pd_joint_pos` controller tracks joint targets. An LLM can select and invoke this
code; it does not generate the executed joint trajectory in this recipe.

Although output rendering is disabled, pinned SAPIEN creates a Vulkan device for
material initialization. On the verified CPU-only host, the required setup was:

```sh
sudo apt-get install --no-install-recommends libgl1 libegl1 libxext6 libglib2.0-0 libvulkan1 mesa-vulkan-drivers
export VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/lvp_icd.x86_64.json
```

First prepare the project without `--install-deps` to create its isolated Python
environment. For the tested CPU package variant, use that environment's Python:

```sh
/PATH_TO_ENV/bin/python -m pip install --upgrade pip
/PATH_TO_ENV/bin/python -m pip install torch==2.5.1+cpu --no-deps --index-url https://download.pytorch.org/whl/cpu
```

Then repeat the same pinned preparation with `--install-deps`; its normal PyPI
installation resolves the remaining dependencies. Execute the returned
`next_command` separately, using the returned working directory and a 180-second
external timeout. The complete reproducible procedure is
`tools/run_runtime_verification.py`; it is maintainer-run, never triggered by a
submitted patch or memory. The historical environment check does not establish
other seeds, robots, observation modes or physical hardware. Check the current
record's evidence before treating the new wrapper as runtime verified.

## Hub episode horizon

Hub recipe version `1.1.0` explicitly sets `max_episode_steps=1000`. This is the
Hub motion-planning budget; the upstream source remains pinned and its benchmark
default is not changed. The wrapper accepts completion only with `success=true`,
`truncated=false` and `0 < elapsed_steps < 1000`, and reports `terminated`,
`truncated` and the configured horizon in its final JSON. `terminated` alone is
not proof of task success. The 180-second process timeout is a separate wall-clock
limit. This contract needs a fresh run and is not a standard-horizon benchmark.

## Prepare the source from Windows

Search and source preparation work on Windows even though the simulator target
is Linux. To preserve the pinned source and adapter without attempting an
unsupported simulation environment, use the installed skill directory:

```sh
python /PATH_TO_SKILL/scripts/rsh.py --catalog https://hub.superfastrobotics.com/catalog/v1/index.json prepare maniskill-panda-pick-cube --project ./pick-cube-source --download-only --json
```

The expected result is `needs_configuration` with
`reason_code: source_ready_runtime_not_prepared` and `next_command: null`.
It verifies the archive SHA-256 and writes a source/recipe lock, but creates no
venv, installs no dependencies and runs no robot task. Use a separate matching
Linux environment for execution; keep the existing research project's lock.
