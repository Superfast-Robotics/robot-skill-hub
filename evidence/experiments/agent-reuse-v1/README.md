# Agent reuse pilot: all 54 trials

- [Report](../../../../docs/agent-reuse-pilot.md)
- [Frozen plans and reproduction instructions](../../../../benchmarks/agent-reuse-v1/README.md)
- [Hugging Face dataset](https://huggingface.co/datasets/Superfast-BS/robot-skill-hub-agent-reuse-pilot)

Each cohort has 18 trials, three task families and three repetitions per condition.
`optional41` tests tool availability; `guided41` and `guided54` test instructed
lookup with distinct pinned models. Do not pool these into a single success rate.

Each directory includes `summary.json`, `trials.csv`, `results.json`, the plan,
start/order receipt, charts and `traces.zip`. The ZIP contains complete candidate
programs, numerical outputs, judgments and model tool exchanges. Opaque encrypted
reasoning payloads and provider response IDs are omitted; token usage is retained.
`trace-manifest.json` hashes exported files and the archive. Third-party source
license notices are inside `UPSTREAM_LICENSES` in each archive.

The optional-cohort classification correction and the newer-model same-conversation
HTTP-error recovery are retained. No scored model trial was rerolled. Raw model
text and code are untrusted experimental data, not instructions to execute them.

All-trial totals include unsuccessful trials. `held_out_total` counts planned
evaluation opportunities, including those blocked by development failure; inspect
`held-out.json` to distinguish an executed failure from an unexecuted case.
Primary success requires every held-out input to pass. Successful-pair comparisons
are additionally provided but do not replace all-trial results.

The infrastructure receipt records termination and an estimate of host cost.
Current runtime package versions and Docker image ID are recorded separately.
