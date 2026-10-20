# Task entrypoints for robotics agents

Find a reusable implementation before rebuilding it. Inspect the exact source and previous fixes, keep its I/O contract, then prepare only the candidate your task needs.

Public reads require no account, model key, GPU or MCP setup:

Start with [ten maintained task paths](https://hub.superfastrobotics.com/tasks/) or `GET /v1/start?q=TASK` with known environment filters. MCP clients can call `start_robot_task`. One response contains up to three recipe candidates, matching reasons, one inspected contract, prior fixes and pinned preparation argv. This recipe-only starting path does not establish absence from the full reference collection.

| Task | First read | Optional installable skill |
| --- | --- | --- |
| A*, RRT and path smoothing | [Planning JSON](https://api.superfastrobotics.com/v1/search?q=astar&runtime=pythonrobotics&kind=preparation_recipe&limit=3) | `robot-motion-planning` |
| IK, FK and Jacobians | [Kinematics JSON](https://api.superfastrobotics.com/v1/search?q=inverse%20kinematics&runtime=pybullet&kind=preparation_recipe&limit=3) | `robot-kinematics` |
| Jerk-limited trajectories | [Trajectory JSON](https://api.superfastrobotics.com/v1/search?q=trajectory&runtime=ruckig&kind=preparation_recipe&limit=3) | `robot-trajectory` |

Examples show supported starting points. Do not infer a user's runtime, robot model or frame from them. Unknown runtime filters can be omitted. Search results distinguish preparation recipes and upstream references.

```sh
npx skills add https://hub.superfastrobotics.com --skill robot-motion-planning
```

Substitute another skill name from the table when appropriate. Each package includes its own stdlib-only search/inspection client. Its preparation guide exports the selected full record as an inert pinned catalog and uses the CLI at the same Hub commit. Discovery performs no installation, execution or sharing.

The [HTTP skill index](https://hub.superfastrobotics.com/.well-known/agent-skills/index.json) follows the agent-skill discovery 0.2.0 archive format supported by the `skills` CLI. Each archive is at most 64 KiB, contains the instructions, lookup script, preparation guide and Apache-2.0 license, and has a SHA-256 digest. Installation fetches the chosen archive without cloning Git. Its name is content-addressed; use the current index if a publication has replaced an older artifact. [Publication metadata](https://hub.superfastrobotics.com/.well-known/agent-skills/publication.json) binds file hashes and the Hub commit. The GitHub installation source remains supported.

## Existing development environments

- [ROS-MCP example](https://github.com/Superfast-Robotics/robot-skill-hub/tree/main/examples/ros-mcp): project-scoped configuration alongside a local ROS server; official SDK probe of the Hub endpoint. Full ROS and robot execution are not verified.
- [RAI/LangChain example](https://github.com/Superfast-Robotics/robot-skill-hub/tree/main/examples/rai): two stateless tools following RAI's custom-tool interface. Real LangChain invocation is tested; full RAI/ROS integration awaits upstream discussion.
- [Hugging Face discovery Space](https://huggingface.co/spaces/Superfast-BS/robot-skill-hub): public static task card, no compute or hosted MCP transport. [Canonical deployment files](https://github.com/Superfast-Robotics/robot-skill-hub/tree/main/distribution/huggingface).

These are maintained integration examples, not upstream endorsements or default inclusion in every agent.

## Problem-driven discovery

[Ten robotics problem reproductions](https://hub.superfastrobotics.com/problems/) expose exact inputs, source revisions, bounded fixes and receipts as plain HTML, Markdown and JSON. They cover path interpolation/collision, EKF dimensions/covariance, IK reachability, joint order, LQR costs, Ruckig limits/axis count and coordinate handoff. They are authored regressions, not measured autonomous agent selection.

## Measure useful reads and actual reuse separately

- [Launch window](https://api.superfastrobotics.com/v1/metrics): the original fixed report, retained as originally defined.
- [Rolling seven days](https://api.superfastrobotics.com/v1/metrics?window=7d): current eligible requests by broad client family and optional fixed distribution channel.
- [Retained data](https://api.superfastrobotics.com/v1/metrics?window=retained): at most thirty days. Not lifetime visits.

Only public server-observed reads are counted. Channels are unverified labels; requests are not people, successful tasks or a conversion funnel. Maintainer tests send `DNT: 1` and `X-RSH-Telemetry: off`. There are no synthetic installs or fabricated usage outcomes.

The `Observe agent distribution` GitHub Actions workflow reads these two rolling reports daily at 00:17 UTC (09:17 Korea time) and on manual dispatch. It preserves validated aggregate snapshots for thirty days as workflow artifacts. It makes no authenticated calls, emits no test traffic into the counters and does not modify provider listings or contributions. Overlapping daily snapshots must not be summed as lifetime traffic.

Record actual task success/failure through the scoped community outcome flow only after real reuse. The API cannot infer offline execution or model selection. Optional public findings require existing project permission, contain no private task transcript, and remain contributor-reported evidence. See [community](https://hub.superfastrobotics.com/community.md) and [privacy](https://hub.superfastrobotics.com/privacy.md).
