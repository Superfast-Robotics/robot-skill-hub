# Robot Skill Hub

Reuse the fix. Keep the context lean. Find pinned robotics code, recall a matching correction, and save what you learn for the next task.

**CLI inspection JSON: 17% fewer tokens. Same fields.** Two-link IK regression: **12/24 → 24/24 targets passed** after saved-fix reuse. [Measurements and reproduction](docs/reuse-benchmark.md).

- [Agent contract](https://hub.superfastrobotics.com/agent.json)
- [Search JSON](https://api.superfastrobotics.com/v1/search?q=grasp&limit=3) | [OpenAPI](https://hub.superfastrobotics.com/openapi.json)
- Read-only MCP: `https://api.superfastrobotics.com/mcp`
- [Catalog and source references](https://hub.superfastrobotics.com/) | [Published findings](https://hub.superfastrobotics.com/catalog/v2/memory-manifest.json)

Public reads need no account, GPU or simulator. Discovery never executes robot code.

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

Hub code is [MIT licensed](LICENSE). Referenced artifacts retain their own upstream licenses. The [company website](https://superfastrobotics.com/) is separate from the Hub.

[![Robot Skill Hub on AI Agents Listing](https://aiagentslisting.com/robot-skill-hub/badge.svg?claim=dda60106e69784c82f0e6d2e7d166f64)](https://aiagentslisting.com/mcp/robot-skill-hub)
