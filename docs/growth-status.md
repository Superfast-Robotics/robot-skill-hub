# Launch measurement operations

The fixed launch window is **2026-10-17 15:47:38 UTC through 2026-10-18 15:47:38 UTC**, with a target of 100 eligible API accesses. Neither monitoring nor deployment resets this window.

Read the current counter at `https://api.superfastrobotics.com/v1/metrics`. It counts successful discovery/record reads from the Hub CLI or a recognized agent User-Agent, plus successful MCP tool calls. Health, metrics, protocol handshakes, crawlers, internal tests and telemetry opt-outs do not count. Client identity is self-reported: these counters cannot establish 100 distinct autonomous agents. Direct Pages, GitHub and offline use are outside this counter.

Preserve a local observation:

```sh
python tools/monitor_campaign.py --external
```

The monitor reads health, metrics and the publication version manifest. `--external` also reads the existing community PR and Commons post status. It sends `DNT: 1` and `X-RSH-Telemetry: off`; it never searches the catalog, calls MCP tools, executes robot code or creates visits. Missing or inconsistent measurements remain `null`.

Timestamped JSON snapshots and `latest.json` are written to `.local/campaign-monitor/`. Use `--output DIR` for another location. `--watch --interval 300` keeps observing until the fixed deadline and can be stopped with Ctrl-C.

The `Observe fixed launch campaign` GitHub Actions workflow runs hourly and can be dispatched manually from `main`. Observations are retained as artifacts for seven days. After the deadline, a separate job disables this workflow using its job-scoped Actions permission. It cannot write repository content. GitHub may delay scheduled runs, so the last observation can occur after the deadline; the API still counts only the fixed window.

The [first remote observation run](https://github.com/Superfast-Robotics/robot-skill-hub/actions/runs/39050122732) succeeded. Its logs and artifact preserve a configured counter of 3 eligible accesses at 2026-10-17 16:36:16 UTC; the deadline-disable job was correctly skipped while the window remained open. Those accesses cannot be attributed to three distinct autonomous agents.

## Published discovery channels

The following are publication receipts, not claims about traffic or adoption:

| Channel | Evidence and state |
| --- | --- |
| Official MCP Registry | [Version 0.2.0](https://registry.modelcontextprotocol.io/v0.1/servers/io.github.Superfast-Robotics%2Frobot-skill-hub/versions/0.2.0) is active. [Publishing run 39049616225](https://github.com/Superfast-Robotics/robot-skill-hub/actions/runs/39049616225) succeeded and checked the public registry record. |
| GitHub release | [Public preview 0.2.0](https://github.com/Superfast-Robotics/robot-skill-hub/releases/tag/v0.2.0) pins source commit `8adbd359627f39c68b49b74bbb8b97fac617573b`, with 17 preparation recipes, 651 source references and 3 reviewed findings. |
| Agent Skills directory | The [skills.sh listing](https://www.skills.sh/superfast-robotics/robot-skill-hub/find-robot-skills) exists. Its displayed installation count does not establish independent agents or task use. |
| Community directory submission | [Awesome Agent Skills PR 67](https://github.com/Ezeafk/awesome-agent-skills/pull/67) is open and awaiting maintainer review as of 2026-10-17. Submission is not acceptance or a merged listing. |
| Agent Commons | The [introduction](https://commons.dooza.ai/api/entries?id=post_rsh-commons-intro-20261017) and [deployed API/MCP follow-up](https://commons.dooza.ai/api/entries?id=post_rsh-commons-followup-20261017-v020) were published once and read back. The maintainer profile identifies its Codex-based role and affiliation with Superfast Robotics. |

The Commons host Hermes [replied](https://commons.dooza.ai/api/entries?id=msg_548da4ce-d5e3-4bad-aab3-e2657067c4ac) that it read the public catalog and identified a specific ManiSkill source pin before answering. This is qualitative evidence of external engagement. The static catalog read is outside the API counter and was not added to that counter retroactively.

In a [second reply](https://commons.dooza.ai/api/entries?id=msg_c14a75fc-44b5-40ba-8436-342c85d110e2), Hermes reported checking the live MCP handshake/tool list, filtered JSON lookup, wrong-commit conflict and registry record. It identified a wording gap: the `0.2.0` registry description could imply that MCP prepares runs, while preparation uses the separate Hub CLI. This is concrete external feedback; a corrected publication requires a new registry version because published metadata is immutable.

The first IndexNow request returned HTTP 403 with `SiteVerificationNotCompleted`, after the public ownership file was verified independently. One bounded retry at **2026-10-17 16:39:19 UTC**, using the updated sitemap's 679 canonical URLs, returned HTTP 200. This proves notification receipt, not search indexing or resulting visits.

At **2026-10-17 16:32:37 UTC**, the configured API reported **1 of 100 eligible accesses**, with the fixed window still open. This dated observation does not establish distinct autonomous agents or completion of the target. Read the live metrics endpoint and preserved observations for subsequent changes. Maintainer validation and monitoring send telemetry opt-out headers; synthetic visits are not used.
