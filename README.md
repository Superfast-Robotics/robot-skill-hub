# Robot Skill Hub

Reuse the fix. Keep the context lean. Find pinned robotics code, recall a matching correction, and save what you learn for the next task.

**CLI inspection JSON: 17% fewer tokens. Same fields.** Two-link IK regression: **12/24 → 24/24 targets passed** after saved-fix reuse. [Measurements and reproduction](docs/reuse-benchmark.md).

- [Agent contract](https://hub.superfastrobotics.com/agent.json)
- [Search JSON](https://api.superfastrobotics.com/v1/search?q=grasp&limit=3) | [OpenAPI](https://hub.superfastrobotics.com/openapi.json)
- Read-only MCP: `https://api.superfastrobotics.com/mcp`
- [Catalog and source references](https://hub.superfastrobotics.com/) | [Published findings](https://hub.superfastrobotics.com/catalog/v2/memory-manifest.json)

Public reads need no account, GPU or simulator. Discovery never executes robot code.

[Task-specific entrypoints](docs/agent-distribution.md): `robot-motion-planning`, `robot-kinematics`, `robot-trajectory`. [Ten reproducible robotics problems](https://hub.superfastrobotics.com/problems/) provide pinned input, correction and evidence in HTML, Markdown and JSON. [ROS-MCP](examples/ros-mcp) and [RAI/LangChain](examples/rai) examples connect lookup to existing development workflows.

[Robot, environment and task coverage](https://hub.superfastrobotics.com/coverage.html) | [Coverage API](https://api.superfastrobotics.com/v1/coverage). Current-version completions, failed attempts and unexecuted recipes are counted separately; reference labels describe source coverage rather than verified robot support.

<!-- rsh-coverage:start -->
## Current execution and reference coverage

62 preparation recipes: **50 completed operations/tasks**, 1 failed current task attempt and 11 without a current task run. Unbound evidence: 0.

| Runtime | Declared robot / model | Domain | Prepared | Passed | Failed | No task run |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| maniskill | panda | simulation | 8 | 5 | 1 | 2 |
| maniskill | panda_stick | simulation | 2 | 0 | 0 | 2 |
| maniskill | panda_wristcam | simulation | 2 | 0 | 0 | 2 |
| maniskill | so100 | simulation | 1 | 0 | 0 | 1 |
| maniskill | xarm6_robotiq | simulation | 4 | 0 | 0 | 4 |
| pybullet | synthetic-seven-axis-or-procedural-scene | simulation | 12 | 12 | 0 | 0 |
| pythonrobotics | mathematical-model | computation | 28 | 28 | 0 | 0 |
| ruckig | independent-axes | computation | 5 | 5 | 0 | 0 |

Completion evidence covers 33 computations and 17 simulations across 6 exact environment combinations. **Physical robot completions: 0.** Recipe counts are not unique robot counts or general success rates. Older versions do not verify changed code.

| Task level | Prepared | Passed | Failed | No task run |
| --- | ---: | ---: | ---: | ---: |
| Algorithm / sensing | 39 | 39 | 0 | 0 |
| Motion / control | 6 | 6 | 0 | 0 |
| Task | 17 | 5 | 1 | 11 |

**1330 source references across 44 frameworks.** References are upstream declarations, not Hub execution evidence.

| Reference framework | Records |
| --- | ---: |
| mujoco-menagerie | 221 |
| webots | 193 |
| pinocchio | 76 |
| drake | 73 |
| franka-description | 72 |
| ros2-control | 72 |
| ur-description | 65 |
| isaaclab | 52 |
| Other 36 frameworks | 506 |

| Declared reference robot category | Records |
| --- | ---: |
| source-defined | 615 |
| arm | 262 |
| manipulator | 83 |
| humanoid | 69 |
| mobile-manipulator | 65 |
| legged | 46 |
| aerial | 37 |
| wheeled | 36 |
| dexterous-hand | 34 |
| quadruped | 18 |
| mobile | 9 |
| marine | 1 |

Robot categories and task/capability tags can overlap. Generic labels are preserved; supported physical robots are not inferred.

[All robot, environment and task tables](https://hub.superfastrobotics.com/coverage.html) | [Compact coverage API](https://api.superfastrobotics.com/v1/coverage) | [Complete coverage JSON](https://hub.superfastrobotics.com/catalog/v1/coverage.json)
<!-- rsh-coverage:end -->

[Executable skills and interfaces](docs/executable-skills.md): 62 preparation recipes, including 45 new parameterized adaptations for planning, kinematics, filtering, trajectory generation and headless simulation. Inputs and outputs declare units, frames, abstraction level and runtime evidence. Indexed references link to matching prepared adaptations without changing the reference's evidence.

```sh
npx skills add Superfast-Robotics/robot-skill-hub --skill find-robot-skills
python /PATH_TO_SKILL/scripts/rsh.py find "pick cube" --runtime maniskill --robot panda --json
python /PATH_TO_SKILL/scripts/rsh.py inspect SKILL_ID --project . --json
python /PATH_TO_SKILL/scripts/rsh.py prepare SKILL_ID --project ./experiment --plan --json
```

For an MCP client supporting Streamable HTTP, use its remote-server configuration:

```json
{"mcpServers":{"robot-skill-hub":{"url":"https://api.superfastrobotics.com/mcp"}}}
```

Clients supporting Agent Plugins 1.0.0 can use the small [read-only connection package](plugins/robot-skill-hub). Its manifest and MCP configuration include no CLI bundle or catalog snapshots; see the package README for client verification scope.

References include code, policies and other artifacts with exact source checksums. Use a reference's inspected `fetch_source_args` with `rsh.py` and append `--project DIR --json` to retrieve one verified file as inert data. This does not require a runtime adapter or install the source as an agent skill. Supported recipes use `prepare`; runtime evidence is limited to the exact configuration and seed recorded with each recipe. Existing project locks never silently change.

Recall previous setup work with `rsh.py inspect SKILL_ID --project DIR --json`. Preserve a useful finding with `save SKILL_ID --project DIR --finding FILE --json`. Local experience is immediately reusable. For already-authorized public project scope, `join` enrolls an installation and enables automatic publication, without a maintainer token or PR approval. Immutable variants and actual reuse outcomes remain tied to exact source pins. See the [community loop](skills/find-robot-skills/references/community.md).

Community data is contributor-reported and archived hourly on the [community-data branch](https://github.com/Superfast-Robotics/robot-skill-hub/tree/community-data). It never silently replaces canonical code or establishes runtime verification. New canonical sources (`register`) and changes to curated recipes retain their separate reviewed PR channel.

[Quickstart](docs/agent-quickstart.md) | [New skills](docs/new-skills.md) | [Task memory](docs/memory.md) | [Patch contributions](docs/contributing.md) | [Privacy](docs/privacy.md)

[Verification evidence](docs/verification.md) | [Development and deployment](docs/deployment.md)

Hub platform code is [Apache-2.0 licensed](LICENSE). Hub-authored robotics execution adapters and their templates are [MIT licensed](LICENSES/MIT.txt). Referenced artifacts retain their original licenses and notices; see [license scope](LICENSE_SCOPE.md). The [company website](https://superfastrobotics.com/) is separate from the Hub.

[![Robot Skill Hub on AI Agents Listing](https://aiagentslisting.com/robot-skill-hub/badge.svg?claim=dda60106e69784c82f0e6d2e7d166f64)](https://aiagentslisting.com/mcp/robot-skill-hub)
