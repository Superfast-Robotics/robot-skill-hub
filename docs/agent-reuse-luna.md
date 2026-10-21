# We gave a robot coding agent a head start

In our small test, GPT-6 Luna spent about 54 seconds per run building a path planner. Perfectly respectable. Also, somebody had already written the planner.

So we tested the obvious shortcut: let the agent start with working code.

[Robot Skill Hub](https://hub.superfastrobotics.com/) is a repository of robotics sources and executable recipes for AI agents. We compared **direct implementation** with **required reuse of a matching Hub recipe**, using the same model, tasks and execution limits.

Thirty runs. Three tasks: avoiding obstacles, generating a smooth joint trajectory, and positioning a simulated robot arm. Five repetitions per task, per approach. Both environments were prepared in advance; Hub adapters used a small experimental wrapper. Live lookup time counted.

| Across 15 runs per approach | Direct implementation | Hub reuse |
|---|---:|---:|
| Average agent time per run | 31.9 seconds | **17.7 seconds** |
| Runs passing every held-out test | 13/15 | **15/15** |
| Failed development tests before submission | 5 | **1** |
| Generated tokens (model output, including reasoning) | 30,318 | **9,437** |

**69% fewer generated tokens. About 45% less agent time.** Every attempt counted, including the slowest reuse run. We also checked that the Hub group actually called the prepared adapter. Reading its name was not enough.

The interesting failure was familiar: two freshly implemented planners passed the visible example, then failed on two new maps each. A working demo can be very persuasive. New inputs are less polite.

The agent had less to invent. That is the point of a useful starting point: spend the generation on what is new. The 69% figure measures output tokens only; it is not a reduction in total input-plus-output usage or billing.

This is a small benchmark of three numerical and simulation tasks, with installation outside the timed portion. The arm test checks position inverse kinematics, rather than a physical robot task. All code, failures and numerical checks are in the [experiment data](https://huggingface.co/datasets/Superfast-BS/robot-skill-hub-luna-reuse). The [frozen protocol](https://github.com/Superfast-Robotics/robot-skill-hub/tree/e6781c6b216b8a897a268126187025ba02fe7b29/benchmarks/agent-reuse-luna) explains the setup.

These runs used the earlier API response format. They do not measure the subsequent compact-response change.

[Find a robotics recipe for your next task.](https://hub.superfastrobotics.com/)
