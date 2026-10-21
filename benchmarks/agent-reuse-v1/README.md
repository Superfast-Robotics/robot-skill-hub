# Agent recipe reuse pilot

This prospective pilot compares direct integration of pinned upstream robotics
code with optional access to Robot Skill Hub recipes. It measures a warm,
preinstalled Python programming environment, not installation, web discovery,
physical robot execution, or independent adoption.

The immutable plan and its hash are written before the first scored model call.
Three task families (grid planning, bounded joint trajectories, synthetic
seven-axis PyBullet inverse kinematics) each receive three repetitions in both
conditions. All 18 trials are retained, including failures. Order is shuffled
with a declared seed. No task is dropped based on its result.

Both conditions use the same model snapshot, upstream files, dependencies,
development input, output contract, execution limits and independent judges.
The Hub condition additionally offers live, telemetry-disabled recipe lookup
and the exact published adapters through a thin preinstalled `hub_runtime`
helper. This helper is experiment infrastructure, not a public SDK. The model
may choose whether to use it. This comparison measures the bundle of retrieval
and adapter reuse, not which component caused a difference.

The agent writes `solve(task)` and receives development-case feedback. The first
development-passing candidate is frozen and run on three new held-out inputs;
their exact values and results are never fed back to that agent. Primary success
means all held-out inputs pass independently checked numerical conditions.
Inputs vary within the published recipe contracts. They are maintainer-authored,
not a representative sample of all robotics work.

Report all per-task trial results, total provider-reported input/output/cached
tokens, calls, development failures, elapsed time and estimated model charges.
Report efficiency on all trials and separately on jointly successful pairs.
Do not interpret three task families as statistical evidence for general
accuracy, a representative fleet or autonomous ecosystem self-improvement.

Generated code executes in fresh containers with no network, no credentials,
read-only source mounts, non-root user, resource/time limits, and no Docker
socket. Held-out grading occurs outside the candidate's container. Host-side
model keys are never sent to the execution host or model context.

Reproduce: see `tools/agent_reuse_pilot/` and the final evidence receipt. The
executor requires Linux Docker. Model calls require an explicitly supplied
OpenAI key file and incur charges. Infrastructure setup is excluded from trial
timing and reported separately.
