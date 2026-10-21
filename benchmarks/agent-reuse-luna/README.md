# Robot Skill Hub GPT-6 Luna reuse experiment

This is a 36-trial current-model repeat, with both cohorts frozen before any scored calls. The older-model pilot was withdrawn from promotion at the maintainer's request; its raw records remain in Git history and a private archive.

- `optional-plan.json`: the agent can choose the Hub tool or work directly.
- `guided-plan.json`: inspect the relevant resource first; use the returned adapter if it matches.
- Each cohort: 3 task families, 3 repetitions, 2 conditions. GPT-6 Luna, medium reasoning, identical per-condition limits. The 8,000 output-token limit includes reasoning.
- The first development-passing candidate is frozen. All three held-out numerical cases must pass. Failure, retries and token overhead remain in the results.
- Warm, preinstalled dependencies and three experiment-only adapter wrappers. This measures coding and reuse, not installation, independent discovery or physical-robot performance.

## Reproduce

```powershell
python tools/agent_reuse_pilot/prepare.py --output .local/luna-repeat --plan benchmarks/agent-reuse-luna/optional-plan.json
```

Build the staged Dockerfile and start its loopback-only `executor.py` on an isolated Linux host. Forward local port 18769 to its port 8769. Do not copy API credentials to the execution host.

```powershell
python tools/agent_reuse_pilot/preflight.py --work .local/luna-repeat
python tools/agent_reuse_pilot/run.py --work .local/luna-repeat --key-file YOUR_LOCAL_KEY_FILE
python tools/agent_reuse_pilot/summarize.py --work .local/luna-repeat --output .local/luna-repeat-summary
```

Use a fresh directory for the guided plan. Each attempt is preserved; do not rerun failures to improve the headline. The model alias and live lookup responses can change over time; exact request/response records and source hashes are retained.
