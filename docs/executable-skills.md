# Executable skills and interface v1

Find a preparation recipe, inspect its exact source, interface and evidence, then prepare it in the caller's project. Execution is a separate explicit local operation. The public API/MCP never executes robotics code.

```sh
python /PATH_TO_SKILL/scripts/rsh.py find "astar" --runtime pythonrobotics --json
python /PATH_TO_SKILL/scripts/rsh.py inspect pythonrobotics-astar-planner --json
python /PATH_TO_SKILL/scripts/rsh.py prepare pythonrobotics-astar-planner --project ./planning --install-deps --json
```

Use the returned `next_command` argv and `next_command_cwd`. It runs the declared example. For a JSON-interface adapter, replace `--example` with `--input /ABSOLUTE_PATH/task.json` or `--input-json '{...}'`. Use `--describe` instead of `--example` to read its interface and example without importing upstream code. Do not append a second input mode to `--example`. The self-contained adapter and pinned dependencies live in the prepared project; a repository checkout is not needed afterward.

Example input for the A* adapter:

```json
{"start":[2,2],"goal":[18,18],"bounds":[0,20],"obstacles":[[10,8],[10,9],[10,10]],"robot_radius":0.3}
```

One JSON object is written to stdout. Upstream diagnostics go to stderr. Success requires exit 0, `status=task_complete`, `success=true`, valid finite outputs and every named check passing. New adapters put operation data under `outputs`; older ManiSkill task adapters expose their result at the root. Always read `interface.output_selector`. A computed path or trajectory is not a physical movement or evidence of a higher-level task.

## Abstraction and implementation

| Level | Contract meaning | Examples |
| --- | --- | --- |
| 0 | Computational or sensing primitive | IK, Jacobian, path planning, filtering, trajectory calculation, simulation query |
| 1 | Motion/control primitive | One steering command, bounded simulated joint-control operation |
| 2 | Task | Existing ManiSkill pick, push and stack recipes |
| 3 | Workflow | Composition of separately pinned lower-level skills; no workflow verification is implied by this schema |

`kind` describes an algorithm, controller, sensor operation, trajectory generator, task or workflow. Level does not describe quality or runtime evidence. `execution_domain` distinguishes computation, simulation and hardware. Interface v1 can describe Python, Rust or C++; currently bundled adapters use Python. The interface is defined in [execution-interface.schema.json](https://hub.superfastrobotics.com/schemas/execution-interface.schema.json); the canonical record schema includes it. Legacy records without an interface remain readable.

## Units, frames and composition

The base conventions are meters, radians and seconds. Schema annotations `x-unit`, `x-frame` and `x-order` describe each field, including mixed state vectors and matrix axes. There is no implicit degrees/radians conversion, axis reordering or coordinate transform. Ruckig's `coordinate_type` explicitly selects uniform linear or revolute axes; it does not carry a robot model. Synthetic PyBullet arms have their own seven-axis model and are not KUKA hardware adapters.

Use `rshlib.interfaces.validate_handoff(value, source_interface, source_field, target_interface, target_field)` to check a concrete transfer: units, frame, field annotations and both bounded value schemas must agree. This validates that field transfer, not all task preconditions, dynamics or safety. For example an A* `path_xy` can feed the smoother's `path_xy` in the same map frame when the actual path fits the smoother's input limit. Supply its other required fields explicitly. An end-effector position cannot be passed as a joint vector or silently transformed to another frame.

ManiSkill task adapters retain their seed CLI input, fixed robot/controller/state-observation setup and declared horizon. Their new interface describes this existing boundary; it does not turn them into arbitrary-pose `grasp` APIs.

## Source adaptations and preparation

Source-reference search results can include `prepared_adaptations`; follow the selected adapter ID and inspect its contract. Source pages link to the same adapters. A reference keeps its original evidence, while an adaptation records its own model, inputs and tests. Origin, source revision, authors and upstream license remain intact. An adaptation can intentionally replace a GUI demonstration with a bounded headless operation or a robot asset with synthetic geometry; it does not validate the original robot setup.

Converted recipes use `preparation.source_selection=declared_paths`. Preparation verifies the complete immutable archive checksum, extracts only the declared regular files and dependencies, preserves licenses/notices, and records those file hashes in the project lock. Unselected archive links are never created. Modified cached sources or existing project locks are preserved rather than silently replaced.

## Verification and extension

This release adds 45 parameterized adapters: 28 PythonRobotics algorithms, five Ruckig trajectory operations and 12 PyBullet DIRECT simulation operations. Together with 17 existing ManiSkill task recipes, there are 62 preparation recipes. Twenty-four indexed reference origins now point to executable adaptations; the other 21 operations extend those same reviewed upstream projects. The 1,330 source references retain their own evidence and are not counted as executed skills.

The path smoother adapts upstream shortcut selection with corrected arclength interpolation and an exact segment/circle collision predicate. It rejects an already colliding input path. `tools/verify_executable_composition.py` tests real A* outputs passed through the shared interface into the smoother on three fixed maps, including obstacle and convex map-bound checks. The [composition receipt](https://github.com/Superfast-Robotics/robot-skill-hub/blob/main/evidence/integration/executable-composition-v1.json) records the exact adapter hashes. This verifies this specific two-step composition, not arbitrary workflows.

The finite cohort is in `catalog/executable-conversions.json`. `tools/generate_executable_recipes.py` generates adapters and metadata from the manifest and `tools/recipe_adapters/`; `--check` detects drift without network or execution. Execution receipts are accepted only when adapter bytes, source guards, source commit and the frozen case plan still match. Changing behavior or a contract requires rerunning its evidence.

`tools/verify_executable_recipes.py` runs each declared input in a separate CPU process with a timeout and tests an unknown-field rejection. Numerical adapters verify operation-specific conditions such as endpoints, collision-free path segments, covariance properties, IK residuals or trajectory boundaries and sampled limits. Simulation adapters additionally check outcomes in PyBullet DIRECT. These are authored regression cases, not a general accuracy estimate, autonomous LLM discovery, real-time guarantee or physical robot verification.

The Linux workflow installs the declared CPU dependencies, fetches checksum-verified source files and retains raw runtime artifacts. Local Windows support is declared only for the numerical/Ruckig environment. The Sobol candidate was excluded because its dependency contains conflicting MIT/LGPL function notices. Sources requiring live robots, gated assets or unprepared services remain references until their separate prerequisites and execution evidence exist.

To reproduce on a supported Linux CPU environment with Python 3.10:

```sh
python -m pip install --only-binary=:all: -r tools/recipe_adapters/requirements-cpu.txt
python tools/fetch_executable_sources.py --cache .local/executable-sources --fetch
python tools/verify_executable_recipes.py --source-cache .local/executable-sources --output .local/executable-run
python tools/verify_executable_composition.py --source-cache .local/executable-sources --output .local/composition-run
```

Use fresh output directories. Preparation recipes pin the complete measured numerical dependency set; they do not promise identical floating-point results across all platforms. Public API responses and `--describe` require no numerical runtime installation.
