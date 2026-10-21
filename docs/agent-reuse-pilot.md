# What helps a robotics coding agent reuse a skill? Results from 54 trials

*Superfast Robotics · October 21, 2026 · Small, maintainer-run engineering pilot*

Robot Skill Hub is a repository of pinned robotics code and execution recipes for AI agents. Its promise is practical: find a useful starting point, inspect its contract and evidence, then spend effort on the part of your task that is new.

We tested that idea with real model calls and executed Python, rather than counting catalog entries or treating an agent's answer as proof of success. **We found a useful reuse case, but we did not establish general token savings.** Simply making a lookup tool available was not enough. Guided lookup improved the number of completed trials in our two small follow-ups, while increasing total API tokens in both.

[Try a task](https://hub.superfastrobotics.com/tasks/) · [Full data and traces](https://huggingface.co/datasets/Superfast-BS/robot-skill-hub-agent-reuse-pilot) · [Source and reproducibility protocol](https://github.com/Superfast-Robotics/robot-skill-hub/tree/main/benchmarks/agent-reuse-v1)

## What we measured

Each condition used the same pinned upstream code, preinstalled dependencies, visible development input, output contract, execution budgets and independent numerical judge. The agent wrote a reusable `solve(task)` function. Its first development-passing candidate was frozen and evaluated on three other inputs that were not shown to it.

| Task | What the independent judge checked |
|---|---|
| A* / 2D path planning | Start and goal, continuous segment clearance from obstacles, map bounds and consistent path length |
| Ruckig joint trajectory | Boundary positions, velocities and accelerations; limits, sampling and derivative consistency |
| PyBullet arm IK | Forward kinematics in a new simulator instance, with position error below 2 mm on a synthetic seven-axis arm |

The PyBullet task is an IK/FK simulation check, not a manipulation episode or a physical robot demonstration. The other two tasks are numerical robotics computations. No perception system, real hardware, installation or internet search was evaluated.

We ran three repetitions per task and condition, in a shuffled order: **18 trials per cohort, 54 total**. Repetitions reuse the same task families and are not 54 independent robotics tasks. We retained failures, unsuccessful retries and their token costs.

The control integrated upstream code directly. The treatment additionally had a `hub_lookup` tool calling the live, pinned Hub `/v1/start` endpoint. Three matching adapters were preinstalled behind a thin, experiment-only `hub_runtime` wrapper. That wrapper is **not a public SDK**. Other retrieved recipes required fallback to direct integration. This is a warm-runtime programming comparison, not a claim about end-to-end cold setup or every MCP client's behavior.

## The full results

These are cohort totals, with **nine trials in each condition**. A completed trial must pass all three held-out inputs. API tokens include provider-reported input and output usage across every model call, including retries; they are not just generated code tokens.

| Cohort | Completed: control → Hub | API tokens: control → Hub | Active time: control → Hub |
|---|---:|---:|---:|
| GPT-4.1 mini, optional lookup | 4/9 → 2/9 | 116,446 → 153,241 | 284.1 s → 306.8 s |
| GPT-4.1 mini, guided lookup | 4/9 → 7/9 | 95,651 → 220,659 | 250.5 s → 190.8 s |
| GPT-5.4 mini, guided lookup | 7/9 → 8/9 | 87,428 → 201,764 | 116.7 s → 156.1 s |

The optional tool was called in **0/9 treatment trials**. Those results do not show a reuse benefit, and their variation should not be interpreted as proof that Hub harms task performance.

For the guided cohorts, the control was told to inspect its upstream entry first; the treatment was told to look up a matching recipe first and reuse it if suitable. These follow-ups were declared separately after early optional-tool trials showed non-selection. The original results remain in the dataset.

![Guided GPT-5.4 mini results, including increased token and time costs](https://huggingface.co/datasets/Superfast-BS/robot-skill-hub-agent-reuse-pilot/resolve/main/guided54/pilot-results.png)

The guided GPT-4.1 mini cohort completed three more trials and used 23.8% less active time, but consumed **130.7% more total API tokens**. The newer model completed one more trial, used **130.8% more tokens**, and took **33.7% more active time**. These small differences in completion counts are descriptive observations, not estimates of general robotics accuracy or statistical significance.

Here is the task-level breakdown. Each cell is completed trials out of three:

| Cohort | Path planning: control → Hub | Trajectory: control → Hub | PyBullet IK: control → Hub |
|---|---:|---:|---:|
| Optional GPT-4.1 mini | 1/3 → 1/3 | 1/3 → 1/3 | 2/3 → 0/3 |
| Guided GPT-4.1 mini | 1/3 → 3/3 | 3/3 → 1/3 | 0/3 → 3/3 |
| Guided GPT-5.4 mini | 1/3 → 2/3 | 3/3 → 3/3 | 3/3 → 3/3 |

## One useful result: reuse instead of guessing the PyBullet integration

In the guided GPT-4.1 mini PyBullet task, the agent reused the exact published adapter in all three treatment trials. All three passed the held-out checks; none of the three direct-integration control trials completed successfully.

Across this **one task family and model**, total API tokens fell from **30,307 to 21,735**, or **28.3%**, and active time fell from **49.3 to 17.0 seconds**, or **65.5%**. This is a concrete, small example of a useful starting point avoiding repeated integration work. It is not a general savings rate. With GPT-5.4 mini, the same task completed 3/3 in both conditions and did not demonstrate the same token benefit.

The final reused functions were short calls to an already prepared adapter. The adapter itself still ran its pinned implementation, and a separate fresh simulator checked the returned joint angles. A model's `success: true` assertion could not satisfy the judge.

![Guided GPT-4.1 mini task-level results, including the trajectory failures](https://huggingface.co/datasets/Superfast-BS/robot-skill-hub-agent-reuse-pilot/resolve/main/guided41/pilot-results.png)

## What did not work

**Lookup was not the same as reuse.** Manual review of the executed final candidates found calls to the prepared wrapper in 5/9 guided GPT-4.1 mini trials and 0/9 guided GPT-5.4 mini trials. The latter model read Hub results but wrote fresh implementations. These numbers describe our harness and prompts, not all agents or the production MCP ecosystem.

**A broad query could choose another valid algorithm.** Two guided GPT-4.1 mini path-planning queries selected an RRT recipe outside the three preinstalled adapters. The agent fell back to writing code. That cost belongs in the results, rather than being removed as an inconvenient case.

**Correct retrieval did not ensure correct integration.** Two older-model trajectory trials retrieved the intended Ruckig recipe but ignored the prepared invocation and guessed nonexistent library methods. Those trials failed. The successful trajectory trial reused the prepared adapter.

**Retrieval had a context cost.** Both guided cohorts used substantially more input tokens. Every newer-model treatment trial initially exceeded the endpoint's 16-content-term query limit and then narrowed the query after receiving its error response. Extra lookups and verbose context can outweigh reduced code generation.

**A passing example was not enough.** Some generated path planners passed the development input and then failed new inputs. We counted them as failed trials instead of publishing the development-only result.

## Audit trail and limits

The data includes frozen plans, hashes, per-trial CSV and JSON, model tool traces, candidate programs, execution outputs and judgments. Upstream source/license notices are retained. Model snapshots were `gpt-4.1-mini-2025-04-14` at temperature 0.2 and `gpt-5.4-mini-2026-03-17` with low reasoning. Both conditions had eight model turns, five execution attempts and a 3,500-output-token limit per model response. Output-limit failures are included.

Two harness issues are disclosed in the receipts: a truncated model tool call was reclassified as an agent failure without changing its outcome; a recoverable HTTP 400 interrupted one newer-model trial and was then delivered to the **same** conversation, without repeating its model call. The repair pause is excluded from active time; the original usage and active time remain included. No scored trial was replaced with a more favorable model draw.

Estimated model charges for all 54 trials were **$0.516**, using the [GPT-4.1 mini](https://developers.openai.com/api/docs/models/gpt-4.1-mini) and [GPT-5.4 mini](https://developers.openai.com/api/docs/models/gpt-5.4-mini) published rates and reported cache usage. The disposable execution host added approximately **$0.83** and was confirmed terminated. These are estimates, not billing invoices. Preparation time and compute are separate from the task-time comparison. Maintainer requests opted out of Hub adoption telemetry.

The task set is small and maintainer-authored, the environment was preinstalled, and the models had explicit function-writing tasks with bounded retries. We did not measure autonomous web discovery, real users, public contribution reuse, ecosystem self-improvement or physical-robot performance. We are publishing the negative findings alongside the useful example because they determine what to build next.

## Try a pinned starting point on your own task

Robot Skill Hub has 194 preparation recipes and 1,897 upstream references in the catalog used for this experiment. References are not completed execution tests. Use short task keywords to obtain source pins, contracts, evidence and preparation instructions:

```sh
curl 'https://api.superfastrobotics.com/v1/start?q=pybullet%20inverse%20kinematics&limit=1'
```

Public lookup needs no account or installation. Local execution still requires the declared environment. The [task pages](https://hub.superfastrobotics.com/tasks/) and [quickstart](https://github.com/Superfast-Robotics/robot-skill-hub/blob/main/docs/agent-quickstart.md) explain that transition; the experiment-only wrapper above is not an installation instruction.

Our next priorities are to make the local execution handoff easier, reduce redundant first-response context, and test short-query guidance with the actual supported agent clients. The useful question is not whether an agent can find a catalog entry. It is whether it reuses a compatible implementation and completes its task with less unnecessary work.
