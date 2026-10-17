# Additional discovery channel status

The initial readiness checks were read-only. Context7 registration was subsequently
submitted on 2026-10-17 at 19:56 UTC after the operator supplied its provider key.
Search results, submission acceptance, completed indexing, client connection and
actual task use are separate outcomes. Smithery remains prepared and unpublished.

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

Smithery's [URL publishing](https://smithery.ai/docs/build/publish) accepts a
public HTTPS Streamable HTTP endpoint. The existing Hub endpoint fits this
transport: `https://api.superfastrobotics.com/mcp`, with three public read-only
discovery tools. Local preparation uses the separate Hub CLI.

Public server and skill searches returned HTTP 200 without a matching Hub
result in the returned candidates. The candidate server name
`superfast-robotics/robot-skill-hub` returned HTTP 404. The unauthenticated
own-namespaces endpoint returned HTTP 401 with an authentication requirement.

The ready command, after provider authentication and namespace ownership, is:

```sh
smithery mcp publish "https://api.superfastrobotics.com/mcp" -n superfast-robotics/robot-skill-hub
```

The requested namespace has not been reserved or ownership-verified. The
[namespace documentation](https://smithery.ai/docs/concepts/namespaces) and
[pricing page](https://smithery.ai/pricing) list the free Hobby plan with three
namespaces. Together with the documented bring-your-own-URL publishing path,
this supports registering the existing public endpoint without choosing a paid
plan or buying Smithery hosting. The anonymous pricing response does not state
a no-card signup guarantee; no checkout or account-specific entitlement was
tested. The
[server-create API](https://smithery.ai/docs/api-reference/servers/create-a-server)
requires a Smithery bearer key; it does not accept an existing GitHub credential
as a substitute. The receipt contains the concrete display name and description
for review, including Superfast Robotics' maintainer affiliation.

Use the documented CLI authentication route; no dashboard key menu is assumed.
With Node.js 20+ and the official CLI installed (`npm install -g smithery@latest`),
the operator runs:

```sh
smithery auth login
smithery auth whoami
smithery namespace list
```

Complete the authorization at the provider URL printed by `auth login`, using
the Smithery account/organization authorized for `superfast-robotics`.
`whoami` should be run without `--full`. If the namespace is absent and
available, the operator can create it with
`smithery namespace create superfast-robotics`; a namespace owned by someone
else cannot be authorized by a GitHub organization token. Review a replacement
qualified name before submission if the desired namespace is unavailable. See
the [CLI guide](https://smithery.ai/docs/concepts/cli) and
[namespace rules](https://smithery.ai/docs/concepts/namespaces).

For a separate local credential handoff, mint a token immediately before the
approved submission, scoped to namespace `superfast-robotics`, resource
`servers`, operations `read` and `write`, and a one-hour TTL. These operations
cover server creation/configuration, release publication and status readback;
namespace creation is completed separately by the operator. No `connections`
or `execute` grant, upstream Hub credential, or GitHub repository scope is
needed. The [token-scoping reference](https://smithery.ai/docs/use/token-scoping)
documents those grants. Its array-form CLI examples differ from the
[current official CLI parser](https://github.com/arcadeai-labs/smithery-cli/blob/407ac3b33944a585357379bc213fdf1ee55464d7/src/index.ts),
which accepts one JSON object per `--policy`. In a POSIX shell, use:

```sh
smithery --json auth token --policy '{"namespaces":"superfast-robotics","resources":"servers","operations":["read","write"],"ttl":"1h"}'
```

On Windows PowerShell, the following equivalent captures the response and saves
only its `token` field as one UTF-8 line without displaying it. Run from this
checkout; `--%` preserves the JSON quotes for the native CLI:

```powershell
$rshTokenReply = smithery.cmd --% --json auth token --policy "{\"namespaces\":\"superfast-robotics\",\"resources\":\"servers\",\"operations\":[\"read\",\"write\"],\"ttl\":\"1h\"}"
if ($LASTEXITCODE -ne 0) { throw 'Smithery token creation failed.' }
$rshTokenValue = ($rshTokenReply | ConvertFrom-Json).token
if ([string]::IsNullOrWhiteSpace($rshTokenValue)) { throw 'No Smithery token returned.' }
[IO.File]::WriteAllText((Join-Path $PWD '.local/smithery-api-key.secret'), $rshTokenValue, [Text.UTF8Encoding]::new($false))
Remove-Variable rshTokenReply, rshTokenValue
```

Keep the raw token out of chat, logs and commits. Both local secret paths are
gitignored. This short-lived service token is accepted through `SMITHERY_API_KEY`;
the filename does not imply that it is a permanent account key. An existing
Smithery key with the same required namespace authority is also sufficient. No
login, token mint, namespace creation, release submission or new account was
attempted here.

Completion requires a successful external-URL release, a readable public server
record and matching endpoint/tool metadata. An accepted release awaiting scan is
not a completed public listing. See the provider's
[release API](https://smithery.ai/docs/api-reference/servers/publish-a-server).

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

MCP.so's [remote-server submission form](https://mcp.so/submit?type=remote-server) displayed a $39 one-time publishing payment when reviewed at 2026-10-17 19:23 UTC. No free route was established and no submission, signup or payment was made. This channel is deferred under the free-first deployment constraint.

Composio's Claude skills directory requires an actual Claude-platform test under its [pinned contribution rules](https://github.com/ComposioHQ/awesome-claude-skills/blob/be2a406907dbc61b73e6827ded415c96139d13a2/CONTRIBUTING.md). Existing Python, Codex and Hermes evidence does not establish that test. No submission or claim of Claude validation was made.
