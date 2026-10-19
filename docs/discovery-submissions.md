# Additional discovery channel status

## Additional registration, 2026-10-19

The [0.4.3 promotion receipt](../evidence/integration/v0.4.3/promotion-verification.json) records the public GitHub release and About description, an active official MCP Registry 0.4.3 entry, and an agentskillhub.dev refresh to `2026.10.19.1` at commit `1083ee561b087448a159bffab9f59f091f5d8784`; all 24 manifest entries match Git blobs. An affiliated, Codex-disclosed [Agent Commons follow-up](https://commons.dooza.ai/api/entries?id=post_rsh-reuse-context-20261019-v043) shared the measured CLI response reduction and separate controlled IK result, linked reproduction and invited concrete environment-mismatch feedback. Anonymous readback matched the submitted text and verified profile. These actions do not establish outside adoption or whole-task token savings.

An affiliated maintainer submission to [AgentNDX](https://agentndx.ai/submit/) returned HTTP 201, receipt **198**, status `received`, at 00:27 UTC. The provider's free search returned no `robot-skill-hub` result before submission. Submitted metadata identifies the public read-only MCP endpoint and the separate CLI preparation/sharing path. This is acceptance for review, not a verified public listing or agent adoption. No paid feature was selected.

[MCP Harbor](https://ai.mcpharbor.dev/servers/io.github.superfast-robotics/robot-skill-hub) already mirrors the official registry: its public JSON search returned the Hub, the exact endpoint and all three tool names, with origin `official` and version 0.4.1. No duplicate submission was made. Mirror refresh remains provider-controlled. Smithery login and namespace creation are now complete, but the provider rejected publication; see the follow-up below.

## Earlier registrations and readiness checks

The initial readiness checks were read-only. Context7 registration was subsequently
submitted on 2026-10-17 at 19:56 UTC after the operator supplied its provider key.
Search results, submission acceptance, completed indexing, client connection and
actual task use are separate outcomes. Smithery remains unpublished after an authenticated attempt.

## Context7 documentation

The registration API returned HTTP 200, `Repository submitted successfully`, and
library ID `/superfast-robotics/robot-skill-hub`. The
[public library page](https://context7.com/superfast-robotics/robot-skill-hub)
subsequently returned HTTP 200. A bounded search at 19:57 UTC returned no exact
library match among its five candidates, and an initial documentation query
returned `no_snippets_found`. At **20:05 UTC**, a later exact library search
returned the Hub with state `finalized`, 248 snippets and 27,507 tokens. A direct
documentation query returned HTTP 200 with four code snippets and one information
snippet containing actual Hub find, inspect and prepare instructions and GitHub
source links. The [sanitized receipt](../evidence/discovery/v0.3.3/context7-registration.json)
preserves these separate observations without credentials. The then-unpublished
`fetch-source` update is outside that indexing result.

Context7 accepts public GitHub documentation. Its parser reads documentation and
code examples; it does not install or run the Hub CLI. Anyone can request a public
library. See [Adding Libraries](https://context7.com/docs/adding-libraries).

The submitted request followed the official
[repository-add API](https://context7.com/docs/api-reference/add-library/add-a-github-repository):

```http
POST https://context7.com/api/v2/add/repo/github
Authorization: Bearer <Context7 API key>
Content-Type: application/json

{"docsRepoUrl":"https://github.com/Superfast-Robotics/robot-skill-hub","private":false}
```

The operator supplied a Context7 key through a private local file. No key was
included in chat, receipts or commits. No GitHub credential or `gitToken` was sent.
Provider key management is documented under
[Manage API Keys](https://context7.com/docs/howto/api-keys).

The [Free plan](https://context7.com/plans) is $0 and includes public repositories
and 1,000 API calls per month. This public registration requires no paid plan,
private-repository access or GitHub permission scopes. No paid upgrade was made.

The repository provides [`context7.json`](../context7.json) for usage documentation
and the installable skill. It excludes bulk snapshots, implementation files,
source-review notes and deployment/campaign history from parsing. The factual
description and paths were checked against the official schema before submission.
The earlier readiness receipt retains its historical proposal. The provider's
[owner configuration](https://context7.com/docs/library-owners) controls parsing.

Registration, finalized library search and actual documentation retrieval are
confirmed. These checks do not establish automatic client activation, agent
adoption or successful robot tasks.

At 20:44 UTC, one documented manual refresh after the source-file and
source-manifest CLI follow-up returned HTTP 400, `too-early`: the live provider
requires at least 10 days between updates for this library. No retry,
re-registration or paid upgrade followed. The [refresh receipt](../evidence/discovery/v0.3.3/context7-refresh.json)
preserves that response. Indexing of the newer `fetch-source` and
`--source-manifest` instructions remains unverified; use the current installed
skill or public Hub documentation for those commands. See the provider's
[manual refresh API](https://context7.com/docs/api-reference/refresh/refresh-a-library)
and [refresh policy](https://context7.com/docs/library-updates).

## Smithery remote MCP

On 2026-10-19, the operator completed Smithery CLI authentication. The official
`smithery@1.2.0` CLI successfully created and claimed the `superfast-robotics`
namespace; a subsequent namespace listing confirmed ownership. No paid plan
or Smithery hosting was selected.

One authenticated attempt used the documented external-URL publishing command:

```sh
npx --yes smithery@1.2.0 mcp publish https://api.superfastrobotics.com/mcp -n superfast-robotics/robot-skill-hub
```

The CLI exited with code 1 and HTTP 403:

> Updating servers has been removed. Contact support@smithery.ai.

An anonymous server lookup at 11:12 UTC returned HTTP 404, `Server not found`.
**The namespace is reserved; the server is not published.** Authentication is
complete, so another login is not the next step. Smithery support must clarify
the currently supported publication route before another attempt. No alternate
account, duplicate listing or paid plan was used to work around this response.

The provider's [publishing guide](https://smithery.ai/docs/build/publish) still
describes the command above; its [namespace guide](https://smithery.ai/docs/concepts/namespaces)
lists three namespaces on the free Hobby plan. These documents do not establish
that the live publication API currently accepts new releases. The
[follow-up receipt](../evidence/discovery/v0.4.3/provider-followup-20261019.json)
records the observed rejection and public readback. The earlier
[readiness receipt](../evidence/discovery/v0.3.0/provider-readiness.json) remains
a historical preparation record.

The intended listing exposes the existing public HTTPS endpoint and its three
read-only tools: `find_robot_skills`, `inspect_robot_skill` and
`get_hub_capabilities`. Source preparation and community sharing use the
separate Hub CLI. Completion requires a successful release and public metadata
matching this endpoint and tool set.

## OpenAI community plugin CLA follow-up

The operator personally signed the CLA for
[community-plugins PR #40](https://github.com/openai/community-plugins/pull/40).
After confirming the exact signature text, the agent posted only the bot's
`recheck` command. The [CLA check](https://github.com/openai/community-plugins/actions/runs/39182272896/job/118027653980)
passed at head `d02be00cebe0ae9da0d98c85b340eddf645e26ff`.
The PR remains a draft and unmerged. Installed Codex qualification, required
repository tests, code-owner review and merge remain pending. CLA success is not
marketplace acceptance. Both commits are linked to the requested Superfast-BS noreply
identity; their file trees were preserved during the earlier author correction.
The agent did not post or modify a legal signature.

## ClawHub skill bundle

ClawHub's public discovery endpoint and two skill searches returned HTTP 200;
neither `robot-skill-hub` nor `find-robot-skills` returned a result in those
queries. Its [auth guide](https://docs.openclaw.ai/clawhub/auth) requires a
GitHub-linked ClawHub account and a ClawHub token for publishing. The
[publishing guide](https://docs.openclaw.ai/clawhub/publishing) also requires
automated release checks before public search/install availability.

There is a separate eligibility issue: the official
[skill format](https://docs.openclaw.ai/clawhub/skill-format) assigns MIT-0 to
hosted skills and disallows per-skill license overrides. This repository's
package is MIT. The current bundle was not uploaded or relicensed. A rights and
distribution decision is needed before treating native ClawHub publication as
ready; obtaining a token alone would not resolve this.

The exact HTTP observations, official source URLs, prepared metadata and remaining
checks are in the [readiness receipt](../evidence/discovery/v0.3.0/provider-readiness.json).

## Additional channel review, 2026-10-18

One affiliated [TensorBlock MCP Index PR](https://github.com/TensorBlock/awesome-mcp-servers/pull/4027) adds a Search category entry and optional structured metadata for the public endpoint, transport, authentication, docs and three read-only tools. The repository's contribution guide, complete source catalog, live search and recent merged community submissions were reviewed before posting. The [submission receipt](../evidence/discovery/v0.3.3/tensorblock-submission.json) records exact public file hashes and an independent anonymous two-request readback. Tools and verification remain self-reported; no desktop-client execution, physical robot control, provider verification or transferred upstream license is claimed. The initial receipt captured the PR as open. A [2026-10-19 follow-up](../evidence/discovery/v0.4.3/provider-followup-20261019.json) confirms it was merged on 2026-10-18 at 16:04 UTC. Resulting traffic and agent adoption remain unmeasured. No fee, new account or synthetic installation activity was used.

The skills.sh detail page and its generated repository installation command are
available, but two anonymous searches at 20:58 UTC did not return this skill.
The current public frontmatter and supported directory layout passed the
documented CLI checks; no local metadata defect or provider eligibility rule
was established. One affiliated, Codex-disclosed reproduction was added to the
[existing upstream search-index issue](https://github.com/vercel-labs/skills/issues/1402#issuecomment-6241074238)
and anonymously read back. The [search and publication receipt](../evidence/discovery/v0.3.3/skills-sh-search.json)
preserves the observations. No installation telemetry was generated, and a
provider fix or resulting adoption has not been verified.

MCP.so's [remote-server submission form](https://mcp.so/submit?type=remote-server) displayed a $39 one-time publishing payment when reviewed at 2026-10-17 19:23 UTC. No free route was established and no submission, signup or payment was made. This channel is deferred under the free-first deployment constraint.

Composio's Claude skills directory requires an actual Claude-platform test under its [pinned contribution rules](https://github.com/ComposioHQ/awesome-claude-skills/blob/be2a406907dbc61b73e6827ded415c96139d13a2/CONTRIBUTING.md). Existing Python, Codex and Hermes evidence does not establish that test. No submission or claim of Claude validation was made.
