# Robot Skill Hub GPT-6 Luna productivity experiment

The primary comparison is mandatory Hub reuse versus direct implementation: three task families, five repetitions and two conditions, 30 scored trials. `required-plan.json` and its SHA-256 were fixed before scored calls. The user clarified that productivity from using the Hub, rather than tool-selection behavior, is the target.

Both groups use GPT-6 Luna with medium reasoning, identical dependencies, limits, development inputs and held-out cases. The Hub group must load the assigned recipe through a live API lookup and call its exact prepared adapter. The executor traces the real wrapper call and rejects numerically correct outputs that bypass reuse. Lookup time and model tokens count. Baseline can use pinned upstream sources or implement directly.

The first development-passing candidate is frozen. All three held-out numerical cases must pass. Failures, retries and token overhead remain. This is a warm-environment benchmark using an experiment-only wrapper: installation, task discovery, physical robots and cold-start costs are outside its scope.

`optional-plan.json` preserves an ancillary 18-trial selection study already underway when the user clarified the question. Its results are not pooled into the primary productivity comparison. The guided 18-trial plan was cancelled before any scored calls; its plan remains in Git history.

## Reproduce

```powershell
python tools/agent_reuse_pilot/prepare.py --output .local/luna-repeat --plan benchmarks/agent-reuse-luna/required-plan.json
```

Build the staged Dockerfile and start its loopback-only `executor.py` on an isolated Linux host. Forward local port 18769 to its port 8769. Do not copy API credentials to the execution host.

```powershell
python tools/agent_reuse_pilot/preflight.py --work .local/luna-repeat
python tools/agent_reuse_pilot/run.py --work .local/luna-repeat --key-file YOUR_LOCAL_KEY_FILE
python tools/agent_reuse_pilot/summarize.py --work .local/luna-repeat --output .local/luna-repeat-summary
```

Use a fresh directory. Do not rerun failed trials to improve a headline. The model alias and live lookup response can change; exact model exchanges, numerical execution traces and source hashes are retained. Pricing includes cache-write tokens where reported, not just cache reads.
