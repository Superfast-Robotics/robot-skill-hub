# Explicit bounded task search

`all_terms` remains the default word-prefix query. `query_mode=task` opts into deterministic ASCII English lexical ranking; the CLI flag is `--query-mode task`. Supply known runtime/robot filters. Unknown environment values remain unknown, and an explicit incompatibility still excludes a record.

The fixed [normalization and coefficients](task-lexical-v1.json) were frozen before the after-evaluation. The [candidate-scope amendment](task-candidate-scope-v2.json) replaces only the original candidate predicate: task mode scores **all hard-filtered records, before text matching**, with a 512-record limit. Native D1 retrieves at most513 rows to detect overflow and does not use FTS preselection for this mode. Static and Python paths use the same cap. `query_too_broad` requires narrower environment/kind filters; adding text alone does not reduce scope. Default FTS/word-prefix search is unchanged.

Ranking removes general request words, uses conservative prefix stems and fixed field weights, then reports integer scores and matched/unmatched terms. It has no embeddings, corpus statistics, synonym rules, per-task aliases or model calls. Source/record pins, declared compatibility and execution evidence are preserved. Exact ID has priority; then score, recipe tie-break and ASCII ID determine ordering. Page arguments retain the mode and exact generation.

The [historical baseline](../../evidence/search/h15-baseline-01/result.json) and its original cases/runner remain unchanged. The [separate after-evaluation](../../evidence/search/task-mode-v1-01/result.json) calls the actual Python matcher on the same complete retained H15 publisher fixture (17 recipes, 1,286 references). Its 40 task cases opt into task mode; all20 controls keep `all_terms`.

| Authored task variants | Default baseline hit@3 | Task hit@3 | Task MRR@10 |
| --- | ---: | ---: | ---: |
| Short keywords (20) | 0.95 | 1.00 | 1.00 |
| Natural sentences (20) | 0.00 | 1.00 | 0.95 |

These are 20 maintainer-authored engineering tasks with two phrasings each, not independent user requests or evidence of adoption. Selected relevant labels are incomplete; precision, exhaustive recall and broad language generalization are unmeasured. The FR3 natural sentence still ranks a duo model before the labeled single-arm model (target rank2). One historical strict-control label error remains preserved; its separate adjudication explains why both returned recipes satisfy the eight explicit environment fields. No robot, source program, model or public API was executed by either offline benchmark. Protocol/native parity is checked separately by contract tests; the measured benchmark corpus is not relabeled as a newer live catalog.

Reproduce with `python tools/evaluate_task_search.py --site LOCAL_COMPLETE_PUBLISHER_SITE --build-receipt MATCHING_RECEIPT --output-dir FRESH_PATH`. It checks fixture/target pins, scoring dependencies, full/compact field projection and denied network/process events, and saves every actual response. It requires the exact historical fixture and does not download one.
