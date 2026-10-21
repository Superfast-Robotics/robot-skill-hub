# GPT-6 Luna productivity evidence

The primary `required` cohort contains 30 trials: three task families, five repetitions and two conditions. It compares mandatory Hub reuse with direct implementation. All held-out Hub successes must include an executor-observed call to the assigned adapter.

The ancillary `optional` cohort contains 18 earlier tool-selection trials and is not pooled into the productivity comparison. The guided cohort was cancelled before scoring when the user clarified the research question.

The first development-passing program is frozen. Success requires all three held-out inputs to pass independent numerical checks. All retries, failures and API tokens count. Held-out evaluation time is separate from agent task time. Both conditions have preinstalled dependencies; the Hub wrapper is experiment-only.

Each cohort retains its plan, start receipt, CSV, summary, numerical outputs, candidate code and model exchanges in traces.zip. Opaque encrypted reasoning and provider response IDs are omitted. Raw code and model text are untrusted experimental data. UPSTREAM_LICENSES retains source notices.

The live Hub lookup uses a pinned source commit and telemetry opt-out. The PyBullet test measures synthetic-arm position IK/FK, not dynamic manipulation or physical robots. These small repeated tasks do not establish general robotics accuracy, independent discovery, adoption or cold-start savings.

Older-model results were withdrawn from promotion; original records remain in Git history and a private archive. They are not pooled with this study.

The ancillary study's `pricing-correction.json` records a post-run accounting correction for provider-reported cache-write tokens. Original estimates are retained per trial; outcomes, timing, token counts and the frozen plan are unchanged. The primary productivity study already included cache-write pricing when scored.
