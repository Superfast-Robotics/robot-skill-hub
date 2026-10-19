# Reuse the fix. Keep the context lean.

**CLI inspection JSON: 17% fewer tokens. Same fields.**

**Two-link IK regression: 12/24 to 24/24 targets passed after saved-fix reuse.**

Find a pinned starting point. Recall a matching correction. Save what you learn for the next task.

```sh
npx skills add Superfast-Robotics/robot-skill-hub --skill find-robot-skills
python /PATH_TO_SKILL/scripts/rsh.py find "pick cube" --json
python /PATH_TO_SKILL/scripts/rsh.py inspect SKILL_ID --project . --json
```

## Token measurement

The [declared plan](../benchmarks/reuse/plan.json) includes all 17 bundled preparation recipes at baseline commit `2dba85ccb23b29316ca44250268ad2a4f63ec1d3`. Each actual old and new CLI invocation inspected the same offline catalog. Parsed output was identical in every case. Version 0.4.3 changes `--json` to compact serialization; interactive output remains indented. No fields, evidence, source pins or recall data were removed.

The [per-case receipt](../evidence/integration/v0.4.3/cli-token-benchmark.json) records all cases and output hashes. With tiktoken 0.14.0 and `o200k_base`, text tokens fell from **66,078 to 54,463** in aggregate: **17.58%**, rounded down to 17% in the headline. Per-response reductions were 16.35–18.37%, with a median of 18.03%. The sensitivity encoding `cl100k_base` measured 65,718 to 53,694 tokens, or 18.30% in aggregate.

This measures the text of CLI inspection responses, including a final newline. It does not measure whole-task tokens, reasoning tokens, tool framing, billing or savings from solving a robot task. A client that reformats JSON before placing it in context can change the result. The [official token-counting guide](https://developers.openai.com/api/docs/guides/token-counting) distinguishes local text counts from complete API request counts.

To reproduce with an isolated Python environment and `tiktoken==0.14.0`:

```sh
python tools/benchmark_cli_tokens.py --output /NEW_OUTPUT_DIRECTORY
```

The runner reconstructs the exact prior `indent=2` representation and preserves both complete outputs. To also execute the old CLI, pass `--baseline-cli /BASELINE_CHECKOUT/skills/find-robot-skills/scripts/rsh.py`. Use the baseline catalog snapshot for the declared cohort; a changed cohort requires a new plan. No LLM service or API key is used.

## Correction reuse measurement

The existing [native Worker/D1 regression](../api/test/workerd/community.test.ts) uses a maintainer-authored planar two-link IK solver with a known quadrant error. Development targets, held-out targets, residual scoring and the correction were unchanged for this rerun. The baseline passed 4/8 development targets and 12/24 held-out targets. A second enrolled installation retrieved the stored immutable correction through anonymous recall. A separate Node CPU process then passed 24/24 held-out targets at residual tolerance `1e-9`, and published a reuse outcome linked to that correction.

Held-out success increased from 50% to 100%, **+50 percentage points**. This is a deterministic authored numerical regression, not a statistical estimate across robotics tasks. It demonstrates transfer, exact-scope retrieval and linked outcomes. No autonomous LLM, upstream skill, simulator or physical robot was evaluated, and no production adoption counts were generated.

```sh
cd api
npm ci
node --experimental-strip-types --test --test-name-pattern="controlled IK task" test/workerd/community.test.ts
```

The harness permits execution only of its two exact authored source strings; it does not execute arbitrary community patches. Local recall is available immediately. Public sharing uses the project's explicit allowed scope, immutable contributor-reported records and bounded delivery; it never silently upgrades a report into verified robot performance.
