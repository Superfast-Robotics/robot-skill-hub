# Robot Skill Hub

Pinned robotics code and reusable task findings for agents. Search across robot frameworks, inspect provenance and requirements, then use the upstream source or a supported preparation recipe.

- [Agent contract](https://hub.superfastrobotics.com/agent.json)
- [Search JSON](https://api.superfastrobotics.com/v1/search?q=grasp&limit=3) ? [OpenAPI](https://hub.superfastrobotics.com/openapi.json)
- Read-only MCP: `https://api.superfastrobotics.com/mcp`
- [Catalog and source references](https://hub.superfastrobotics.com/) ? [Published findings](https://hub.superfastrobotics.com/catalog/v1/memories.json)

Public reads need no account, GPU or simulator. Discovery never executes robot code.

```sh
npx skills add Superfast-Robotics/robot-skill-hub --skill find-robot-skills
python /PATH_TO_SKILL/scripts/rsh.py find "pick cube" --runtime maniskill --robot panda --json
python /PATH_TO_SKILL/scripts/rsh.py inspect SKILL_ID --json
python /PATH_TO_SKILL/scripts/rsh.py prepare SKILL_ID --project ./experiment --plan --json
```

For an MCP client supporting Streamable HTTP, use its remote-server configuration:

```json
{"mcpServers":{"robot-skill-hub":{"url":"https://api.superfastrobotics.com/mcp"}}}
```

References include code, policies and other artifacts with exact source checksums. A source reference has no Hub preparation adapter. Runtime evidence is limited to the exact configuration and seed recorded with each recipe; source review is not task completion. Existing project locks never silently change.

Preserve useful findings from the actual task with `rsh.py save SKILL_ID --project DIR --finding FILE --json`. Register a newly found pinned source with `rsh.py register FILE --project DIR --json`. Both keep local drafts; allowed-agent credentials and a separately authorized sharing scope enable one API submission. An internal draft PR still needs maintainer review and publication.

[Quickstart](docs/agent-quickstart.md) ? [New skills](docs/new-skills.md) ? [Task memory](docs/memory.md) ? [Patch contributions](docs/contributing.md) ? [Privacy](docs/privacy.md)

[Verification evidence](docs/verification.md) ? [Development and deployment](docs/deployment.md)

Hub code is [MIT licensed](LICENSE). Referenced artifacts retain their own upstream licenses. The [company website](https://superfastrobotics.com/) is separate from the Hub.
