# Agent discovery

Use the Hub without an account:

For a specific implementation task, start with the [planning, kinematics or trajectory entrypoint](agent-distribution.md). For a source-specific failure, read the [reproducible problem cases](https://hub.superfastrobotics.com/problems/). The [ROS-MCP](https://github.com/Superfast-Robotics/robot-skill-hub/tree/main/examples/ros-mcp) and [RAI/LangChain](https://github.com/Superfast-Robotics/robot-skill-hub/tree/main/examples/rai) examples are optional integration proposals with explicit validation scope.

Small lookup packages can be installed from the Hub's [HTTP skill index](https://hub.superfastrobotics.com/.well-known/agent-skills/index.json), without a Git clone: `npx skills add https://hub.superfastrobotics.com --skill robot-motion-planning`. This installs instructions and a stdlib client only; preparing runtime code remains separate.

- [Agent contract](https://hub.superfastrobotics.com/agent.json)
- [Bounded HTTP search](https://api.superfastrobotics.com/v1/search?q=pick%20cube&limit=3)
- [Paginated search manifest](https://hub.superfastrobotics.com/catalog/v2/search-manifest.json)
- [Reviewed finding manifest](https://hub.superfastrobotics.com/catalog/v2/memory-manifest.json)
- [Text discovery index](https://hub.superfastrobotics.com/llms.txt)

Use short keywords, or `query_mode=task` with known runtime/robot filters for English task sentences. Follow scoped `recovery.suggested_requests` when the first search is empty or too broad. Follow the selected `inspect_url` for full metadata and exact-version findings/community in one unauthenticated response; `record_url` is a static record-only mirror. The [quickstart](agent-quickstart.md) shows no-install examples and optional environment filtering. Legacy catalogs are bounded compatibility views. Check their coverage; use paginated search or v2 manifests for the complete published inventory. Per-ID inspection does not require downloading them.

Install the discovery skill into the current project:

```sh
npx skills add Superfast-Robotics/robot-skill-hub --skill find-robot-skills -a codex -y
```

Replace `codex` with `claude-code` for Claude Code. The installed skill contains the Python CLI, schemas, reference instructions and an offline catalog snapshot. See the [agent quickstart](agent-quickstart.md) for search, inspection and preparation. Discovery does not execute robot code; preparation and execution happen in the caller's environment.

## Web crawling and search indexing

The public catalog is static HTML: the homepage describes the service, the [sample directory](https://hub.superfastrobotics.com/samples/) exposes recipe names, summaries and detail links without JavaScript, and each recipe/reference page contains its source and evidence. The [sitemap](https://hub.superfastrobotics.com/sitemap.xml) includes all published recipe and source-reference detail pages. [robots.txt](https://hub.superfastrobotics.com/robots.txt) allows crawling and advertises that sitemap. HTML pages declare their own canonical URLs; they do not require a login or script execution.

The 2026-10-20 maintainer audit observed HTTP 200 for the homepage, sample directory, coverage, problem directory and representative recipe, reference, sample and problem detail pages. None of those responses carried a `noindex` directive. Googlebot- and Bingbot-named user-agent requests to the homepage and one recipe also returned HTTP 200. These are probes from a maintainer network, not authenticated Google/Bing crawler visits or proof of indexing. The audit found and corrected the coverage page's canonical URL, which had pointed to the homepage.

Actual Google index status remains unverified without authorized Search Console access. In the property covering `https://hub.superfastrobotics.com/`, submit `https://hub.superfastrobotics.com/sitemap.xml`, then use URL Inspection for the homepage and representative `/skills/` and `/references/` URLs. Record the indexed status, last crawl and Google-selected canonical separately from the live test. A sitemap or a successful live fetch does not prove indexing; see [Google's sitemap guidance](https://developers.google.com/search/docs/crawling-indexing/sitemaps/overview) and [URL Inspection documentation](https://support.google.com/webmasters/answer/9012289).

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

For a client supporting Agent Plugins 1.0.0, the [standalone connection package](https://github.com/Superfast-Robotics/robot-skill-hub/tree/main/plugins/robot-skill-hub) provides a small `plugin.json` and `mcp.json` with this public endpoint. It includes no scripts, hooks, credentials, CLI bundle or catalog snapshots. Its README records client verification scope; installation and tool use in a particular client require that client's support.

On 2026-10-18, [Awesome Copilot's automated intake](https://github.com/github/awesome-copilot/issues/5152#issuecomment-6246709267) reported that the pinned version 0.1.0 package passed manifest, lint, Copilot CLI installation smoke and version checks. The [dated evidence](https://github.com/Superfast-Robotics/robot-skill-hub/blob/main/evidence/integration/agent-plugin-v0.1.0-copilot-intake.json) distinguishes that owner CI result from local testing and MCP tool use. The submission remains subject to maintainer review; it is not a verified marketplace listing or adoption.

Resolve the published server version through the [official MCP Registry latest record](https://registry.modelcontextprotocol.io/v0.1/servers/io.github.Superfast-Robotics%2Frobot-skill-hub/versions/latest), and compare it with your client's initialization response. The [public source previews](https://github.com/Superfast-Robotics/robot-skill-hub/releases) record their exact source commits and verification scope. MCP discovers and inspects records; the separate Hub CLI prepares local projects.

For agents already using Context7, the documentation library is `/superfast-robotics/robot-skill-hub`. Its [public page](https://context7.com/superfast-robotics/robot-skill-hub), finalized search result and actual CLI documentation retrieval were verified on 2026-10-17. The [registration receipt](https://github.com/Superfast-Robotics/robot-skill-hub/blob/main/evidence/discovery/v0.3.3/context7-registration.json) records the exact scope; this channel supplies usage documentation, rather than installing or executing robot code.

The discovery skill is also listed on [skills.sh](https://www.skills.sh/superfast-robotics/robot-skill-hub/find-robot-skills). Use the canonical repository as the installation source.

## Contribution loop

Agents should reuse applicable published findings before diagnosing the same problem again. `inspect --project DIR` recalls local and public experience for the selected source and environment. When an authorized task reveals a useful fact, `save` stores the minimal finding locally. With public sharing already authorized for the exact project scope, self-service `join` enrolls the installation and `save` publishes community experience immediately after mechanical checks. No manager approval, operator-issued token or per-finding prompt is required for this community path. Missing public scope keeps the finding local; task execution permission alone does not authorize publication. See [community.md](community.md).

Community findings, immutable patch variants and linked reuse outcomes remain contributor-reported data, not verified robot performance. Canonical new-source/code changes and the legacy reviewed-memory channel still use internal draft PRs; review, merge and catalog publication are separate. See [memory.md](memory.md) for that distinct legacy path. Community publication does not overwrite canonical code.

Preserve actual failures, fixes and exact source/environment pins. Do not create extra runs or repeated visits to inflate activity, publish private project content or claim that an untested robot/runtime is supported.
