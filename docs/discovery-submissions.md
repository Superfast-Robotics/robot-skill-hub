# Additional discovery channel readiness

This records a read-only provider check on 2026-10-17. None of the submissions
below was sent. Search results, submission acceptance, completed indexing,
client connection and actual task use are separate outcomes.

## Context7 documentation

Context7 accepts public GitHub documentation, and the launch guide explicitly
names this channel. Its parser reads documentation and code examples; this does
not install or run the Hub CLI. Anyone can request a public library without
owning its repository. See [Adding Libraries](https://context7.com/docs/adding-libraries).

The public search API returned HTTP 200 without a matching Hub result, and
`https://context7.com/superfast-robotics/robot-skill-hub` returned HTTP 404.
This is the observed state for those queries, rather than a claim about every
possible provider alias.

The documented submission is:

```http
POST https://context7.com/api/v2/add/repo/github
Authorization: Bearer <Context7 API key>
Content-Type: application/json

{"docsRepoUrl":"https://github.com/Superfast-Robotics/robot-skill-hub","private":false}
```

The [repository-add API](https://context7.com/docs/api-reference/add-library/add-a-github-repository)
requires a Context7 key. A GitHub token is unnecessary for this public repository
and was not sent. For manual submission, use
[Add Library](https://context7.com/add-library) → GitHub → repository URL above.
The browser form itself could not be verified because this session has no
available browser surface.

To enable an authenticated API submission, an operator can use the free public
library path, open [Dashboard](https://context7.com/dashboard), then select
**API Keys → Create API Key**. The provider's
[key instructions](https://context7.com/docs/howto/api-keys) describe the
`ctx7sk-` format and one-time display. Supply it through `CONTEXT7_API_KEY` or a
private local secret file, never repository content or a public message.

An optional `context7.json` proposal is preserved in the readiness receipt; it
has not been committed or applied. It limits parsing to usage documentation and
the installable skill, and gives a factual description. The provider's
[owner configuration](https://context7.com/docs/library-owners) controls parsing
and presentation; adding that file alone does not prove registration.

Completion requires a successful submission response, completed library
indexing, and a documentation query that returns actual Hub instructions and
source links. Neither submission nor that query was performed in this check.

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
[namespace documentation](https://smithery.ai/docs/concepts/namespaces) lists
three namespaces on the free Hobby plan. The
[server-create API](https://smithery.ai/docs/api-reference/servers/create-a-server)
requires a Smithery bearer key; it does not accept an existing GitHub credential
as a substitute. The receipt contains the concrete display name and description
for review, including Superfast Robotics' maintainer affiliation.

Authentication can be completed with **`smithery auth login`** (or
`npx smithery auth login`) and **`smithery auth whoami`**, following the
[official CLI guide](https://smithery.ai/docs/concepts/cli). The login command
prints its provider authorization URL. Use an account with ownership of the
chosen namespace and authority to create/update its server and publish a release;
no extra GitHub repository permission is required by this API. An existing
provider key can instead be supplied as `SMITHERY_API_KEY`. No login, namespace
creation, release submission or new account was attempted here.

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
