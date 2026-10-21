# We gave a robot coding agent a head start

In our small test, GPT-6 Luna spent about 54 seconds per run building a path planner. Perfectly respectable. Also, somebody had already written the planner.

So we tested the obvious shortcut: let the agent start with working code.

[Robot Skill Hub](https://hub.superfastrobotics.com/) is a repository of robotics sources and executable recipes for AI agents. We compared **direct implementation** with **required reuse of a matching Hub recipe**, using the same model, tasks and execution limits.

Thirty runs. Three tasks: avoiding obstacles, generating a smooth joint trajectory, and positioning a simulated robot arm. Five repetitions per task, per approach. Both environments were prepared in advance; Hub adapters used a small experimental wrapper. Live lookup time and its tokens counted.

| Across 15 runs per approach | Direct implementation | Hub reuse |
|---|---:|---:|
| Average agent time per run | 31.9 seconds | **17.7 seconds** |
| Runs passing every held-out test | 13/15 | **15/15** |
| Failed development tests before submission | 5 | **1** |
| Total API tokens, including input | 132,101 | 317,157 |

**About 45% less agent time in this warm-environment benchmark.** Every attempt counted, including the slowest reuse run. We also checked that the Hub group actually called the prepared adapter. Reading its name was not enough.

The interesting failure was familiar: two freshly implemented planners passed the visible example, then failed on two new maps each. A working demo can be very persuasive. New inputs are less polite.

There is a useful tradeoff here. Reuse generated fewer output tokens, but reading the recipe increased total tokens to about 2.4 times the baseline. The measured win was less waiting and fewer failed development tests. Smaller retrieval responses are an obvious next experiment.

This is a small benchmark of three numerical and simulation tasks, with installation outside the timed portion. The arm test checks position inverse kinematics, rather than a physical robot task. All code, failures and numerical checks are in the [experiment data](https://huggingface.co/datasets/Superfast-BS/robot-skill-hub-luna-reuse). The [frozen protocol](https://github.com/Superfast-Robotics/robot-skill-hub/tree/e6781c6b216b8a897a268126187025ba02fe7b29/benchmarks/agent-reuse-luna) explains the setup.

The idea is simple: give the agent a working starting point, then spend its effort on the part that is actually new.

[Find a robotics recipe for your next task.](https://hub.superfastrobotics.com/)
