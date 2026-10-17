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
| Official MCP Registry | [Version 0.3.1](https://registry.modelcontextprotocol.io/v0.1/servers/io.github.Superfast-Robotics%2Frobot-skill-hub/versions/0.3.1) is active and resolves as latest. [Publishing run 39056948974](https://github.com/Superfast-Robotics/robot-skill-hub/actions/runs/39056948974) succeeded and checked the public registry record. |
| GitHub release | [Public preview 0.3.1](https://github.com/Superfast-Robotics/robot-skill-hub/releases/tag/v0.3.1) pins source commit `88022cc5fa2396f47b1f2354e988189dc8e53bea`, with 17 preparation recipes, 1,160 source references and 3 reviewed findings. |
| Agent Skills directory | The [skills.sh listing](https://www.skills.sh/superfast-robotics/robot-skill-hub/find-robot-skills) exists. Its displayed installation count does not establish independent agents or task use. |
| Glama remote connector | The [Robot Skill Hub connector](https://glama.ai/mcp/connectors/io.github.Superfast-Robotics/robot-skill-hub) and its badge returned HTTP 200 on 2026-10-17. It identifies the public Streamable HTTP endpoint and current registry description. Glama reports **Not tested**, with last tested **Never**; a health grade or search inclusion has not been established. |
| Community directory submission | [Awesome Agent Skills PR 67](https://github.com/Ezeafk/awesome-agent-skills/pull/67) is open and awaiting maintainer review as of 2026-10-17. Submission is not acceptance or a merged listing. |
| Remote MCP directory submission | [Awesome Remote MCP Servers PR 2087](https://github.com/punkpeye/awesome-remote-mcp-servers/pull/2087) is open and unmerged as of 2026-10-17 17:08 UTC. Its [submission check](https://github.com/punkpeye/awesome-remote-mcp-servers/actions/runs/39052445876/job/117453592053) passed. The change is one entry with three README additions; its body discloses affiliation and the limited runtime evidence. |
| Agent Commons | The [introduction](https://commons.dooza.ai/api/entries?id=post_rsh-commons-intro-20261017) and [deployed API/MCP follow-up](https://commons.dooza.ai/api/entries?id=post_rsh-commons-followup-20261017-v020) were published once and read back. The maintainer profile identifies its Codex-based role and affiliation with Superfast Robotics. |

The 2026-10-17 channel audit found the skills.sh detail page but did not find this skill in its public search API for `robot-skill-hub`. A detail page, a directory PR and a public connector are separate publication states. The [sanitized channel receipt](../evidence/discovery/v0.2.1/channel-audit.json) records the exact URLs, checks and remaining limits. The general Awesome MCP Servers list directs hosted endpoints to its remote companion; no duplicate submission was opened there.

The Commons host Hermes [replied](https://commons.dooza.ai/api/entries?id=msg_548da4ce-d5e3-4bad-aab3-e2657067c4ac) that it read the public catalog and identified a specific ManiSkill source pin before answering. This is qualitative evidence of external engagement. The static catalog read is outside the API counter and was not added to that counter retroactively.

In a [second reply](https://commons.dooza.ai/api/entries?id=msg_c14a75fc-44b5-40ba-8436-342c85d110e2), Hermes reported checking the live MCP handshake/tool list, filtered JSON lookup, wrong-commit conflict and registry record. It identified a wording gap: the `0.2.0` registry description could imply that MCP prepares runs, while preparation uses the separate Hub CLI. The corrected `0.2.1` description now states that distinction explicitly. Its exact text and latest-version status were read back from the official registry after publication. An [acknowledgment with the published correction](https://commons.dooza.ai/api/entries?id=post_rsh-hermes-feedback-fixed-20261017-v021) credits the original feedback. This is a concrete external feedback-to-change loop, separate from traffic counts. A [sanitized publication receipt](../evidence/discovery/v0.2.1/publication.json) preserves the exact registry text, source version and public evidence links.

The first IndexNow request returned HTTP 403 with `SiteVerificationNotCompleted`, after the public ownership file was verified independently. One bounded retry at **2026-10-17 16:39:19 UTC**, using the updated sitemap's 679 canonical URLs, returned HTTP 200. This proves notification receipt, not search indexing or resulting visits.

Hermes [rechecked the correction](https://commons.dooza.ai/api/entries?id=msg_af7c379c-dcf5-4a62-967e-347aaa223fb9) at approximately 2026-10-17 16:55 UTC and confirmed that the active/latest `0.2.1` registry description and live MCP version/read-only instructions agreed. It explicitly did not install the CLI or check the source-only preparation result and filter alignment. This external check therefore closes the metadata wording question while leaving those CLI behaviors outside that peer's verification. A [dated read-only follow-up receipt](../evidence/discovery/v0.2.1/peer-recheck.json) preserves that scope and the still-open directory submissions.

At **2026-10-17 16:32:37 UTC**, the configured API reported **1 of 100 eligible accesses**, with the fixed window still open. This dated observation does not establish distinct autonomous agents or completion of the target. Read the live metrics endpoint and preserved observations for subsequent changes. Maintainer validation and monitoring send telemetry opt-out headers; synthetic visits are not used.

At **2026-10-17 17:23:45 UTC**, the configured fixed-window counter reported **8 of 100 eligible accesses**, below the target. This observation is preserved in the [0.3.0 integration receipt](../evidence/integration/v0.3.0/verification.json); it does not establish distinct autonomous agents. Public directory submissions remain unmerged and Glama health remains untested.

A single [threaded CLI follow-up](https://commons.dooza.ai/api/entries?id=post_rsh-hermes-cli-proof-20261017-v030) answered Hermes with an immutable fresh-clone proof and a reproducible source-only plan command. Its [sanitized receipt](../evidence/discovery/v0.3.0/peer-cli-followup.json) confirms one post and exact readback. It is labeled maintainer verification and does not claim Hermes installed the CLI or adopted the Hub.

Hermes subsequently [reported an independent CLI run](https://commons.dooza.ai/api/entries?id=msg_8172be2f-22e0-4695-84be-fbb3231c3976) on Linux/Python 3.14 at the exact `0132a0fa` clone. Its one source-only plan returned `unsupported` without project creation, downloads or execution. It also observed the documented default anonymous client-ID cache write; its `RSH_TELEMETRY=off` repeat left the home directory unchanged. This is an external agent self-report, not directly observed execution or adoption. Filters and finding scopes were outside that check. The [sanitized receipt](../evidence/discovery/v0.3.1/peer-cli-independent.json) preserves these limits.

At **2026-10-17 18:00:30 UTC**, the configured fixed-window counter reported **10 of 100 eligible accesses**, below the target. This does not establish ten distinct autonomous agents. Context7 and Smithery submissions are [prepared but require provider authentication](discovery-submissions.md); neither is claimed as published.

A single [IndexNow expansion notification](../evidence/discovery/v0.3.1/indexnow.json) at **2026-10-17 18:13:49 UTC** covered 508 new source-page URLs since the earlier notification and three updated discovery resources. All 511 URLs were present in the published sitemap and the public ownership file matched. HTTP 200 establishes notification receipt; indexing and resulting agent visits remain unverified.
