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

## Separately declared follow-ups

`guided41-plan.json` repeats the same tasks and budgets with explicit workflows:
the control is told to read its upstream entry first; the treatment is told to
look up a recipe first and reuse it if compatible. `guided54-plan.json` repeats
that guided comparison with GPT-5.4 mini (2026-03-17), low reasoning, and its
own pricing. These follow-ups were declared after early optional-tool trials
showed non-selection. They are reported separately, never pooled into an
improved version of the first result. Each has 18 new trials.

`hub_lookup` and `hub_runtime` are experiment bridges to the public HTTP endpoint
and unchanged published adapters. This is not an evaluation of every production
MCP client's tool-selection behavior. Shared, preinstalled dependencies and the
warm wrapper exclude source acquisition and installation costs in both arms.

One optional-cohort trial emitted malformed tool JSON at the fixed output-token
limit. It was initially labeled an infrastructure exception, then classified as
a failed model submission. Its result and cost were not changed, and it was not
rerun. The correction receipt is included with the results. `--resume` only
continues trials that have not started; it does not replace scored outcomes.

For future live reruns, a new active catalog commit needs a newly declared plan.
The original public lookup responses, model submissions, outputs and judgments
are preserved for audit; stochastic model outputs are not promised to reproduce
byte-for-byte. Do not claim statistical independence across repetitions of the
same three task families.

The first GPT-5.4 mini Hub trial also exposed a harness bug: a valid HTTP 400
query-recovery response was not forwarded to the model. The same conversation
was resumed with that response, preserving its original model call and usage.
The repair pause is excluded from active task time and recorded in
`infrastructure-interruption.json`; no new model draw replaced the first call.
Subsequent recoverable lookup errors become tool feedback. Server outages still
pause the cohort. This protocol repair is disclosed with the results.

## Local Linux reproduction

Use an isolated checkout of this report's commit and a local Docker engine.
Keep the API key outside the generated executor directory.

```sh
python tools/agent_reuse_pilot/prepare.py --output /tmp/rsh-pilot \
  --plan benchmarks/agent-reuse-v1/guided54-plan.json
cd /tmp/rsh-pilot/executor
docker build -t rsh-reuse-pilot:v1 .
python executor.py
```

In a separate terminal, from the repository root:

```sh
python tools/agent_reuse_pilot/run.py --work /tmp/rsh-pilot \
  --endpoint http://127.0.0.1:8769 --key-file /PRIVATE/openai-key
python tools/agent_reuse_pilot/summarize.py --work /tmp/rsh-pilot --output /tmp/rsh-report
python tools/agent_reuse_pilot/export.py --work /tmp/rsh-pilot --output /tmp/rsh-report
```

The frozen live catalog generation must still be available for Hub lookup;
otherwise declare a new plan for the active generation rather than silently
changing the original experiment. `summarize.py` additionally needs matplotlib;
the model orchestrator uses only the Python standard library.
