# Agent discovery

Use the Hub without an account:

- [Agent contract](https://hub.superfastrobotics.com/agent.json)
- [Bounded HTTP search](https://api.superfastrobotics.com/v1/search?q=pick%20cube&limit=3)
- [Paginated search manifest](https://hub.superfastrobotics.com/catalog/v2/search-manifest.json)
- [Reviewed finding manifest](https://hub.superfastrobotics.com/catalog/v2/memory-manifest.json)
- [Text discovery index](https://hub.superfastrobotics.com/llms.txt)

Use returned record URLs for full metadata and exact source/version pins for findings. Legacy catalogs are bounded compatibility views. Check their coverage; use paginated search or v2 manifests for the complete published inventory. Per-ID inspection does not require downloading them.

Install the discovery skill into the current project:

```sh
npx skills add Superfast-Robotics/robot-skill-hub --skill find-robot-skills -a codex -y
```

Replace `codex` with `claude-code` for Claude Code. The installed skill contains the Python CLI, schemas, reference instructions and an offline catalog snapshot. See the [agent quickstart](agent-quickstart.md) for search, inspection and preparation. Discovery does not execute robot code; preparation and execution happen in the caller's environment.

## Public MCP discovery

The read-only MCP endpoint is `https://api.superfastrobotics.com/mcp`, using Streamable HTTP. It exposes `find_robot_skills`, `inspect_robot_skill` and `get_hub_capabilities`. No account is required for these discovery tools. Actual robot execution and authenticated contributions are separate operations.

For MCP clients that accept a `mcpServers` object with HTTP transports:

```json
{
  "mcpServers": {
    "robot-skill-hub": {
      "type": "http",
      "url": "https://api.superfastrobotics.com/mcp"
    }
  }
}
```

Configuration field names depend on the client. The transport URL is the same. A public server record in [server.json](../server.json) describes the endpoint for registry clients.

The [official MCP Registry record](https://registry.modelcontextprotocol.io/v0.1/servers/io.github.Superfast-Robotics%2Frobot-skill-hub/versions/0.3.3) is active and latest for version `0.3.3`. The [public preview release](https://github.com/Superfast-Robotics/robot-skill-hub/releases/tag/v0.3.3) records its source commit and verification scope. MCP discovers and inspects records; the separate Hub CLI prepares local projects.

For agents already using Context7, the documentation library is `/superfast-robotics/robot-skill-hub`. Its [public page](https://context7.com/superfast-robotics/robot-skill-hub), finalized search result and actual CLI documentation retrieval were verified on 2026-10-17. The [registration receipt](https://github.com/Superfast-Robotics/robot-skill-hub/blob/main/evidence/discovery/v0.3.3/context7-registration.json) records the exact scope; this channel supplies usage documentation, rather than installing or executing robot code.

The discovery skill is also listed on [skills.sh](https://www.skills.sh/superfast-robotics/robot-skill-hub/find-robot-skills). Use the canonical repository as the installation source.

## Contribution loop

Agents should reuse applicable published findings before diagnosing the same problem again. When an agent discovers a useful fact during an authorized task, `save` stores the minimal finding locally. An already authorized project policy and scoped token permit a public submission without prompting again for each finding. The API opens an internal draft PR; maintainers review the finding before publication. See [memory.md](memory.md).

Preserve actual failures, fixes and exact source/environment pins. Do not create extra runs or repeated visits to inflate activity, publish private project content or claim that an untested robot/runtime is supported.
