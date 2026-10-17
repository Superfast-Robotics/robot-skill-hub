# Submission API

Small Cloudflare Worker; GitHub is its durable receipt store. Search and preparation remain static/local. No database, queue, paid plan or runtime execution is used by this API.

Agents can store a useful finding through `POST /v1/memories` when the project has already opted into that public sharing scope. Memory storage accepts one minimal observation, not a project, source archive, transcript or raw log. Patch contributions continue to use `POST /v1/submissions`.

```powershell
cd api
npm.cmd ci
npm.cmd test
npm.cmd run check
npm.cmd run dev
```

`test` runs contract tests with a fake GitHub adapter plus tests in the real workerd runtime. The contract tests include later documentation edits, exact historical publication proofs and both required commit ancestry links. The runtime tests intercept every outbound request locally with dummy credentials; they check native fetch behavior, redirect rejection and publication proof. These tests do not themselves prove live GitHub PR creation or robot execution. See [verification](../docs/verification.md) for separate live results.

## Secrets and permission boundary

Set these under Cloudflare dashboard → Workers & Pages → robot-skill-hub-api → Settings → Variables and Secrets (type **Secret**), or run `npx.cmd wrangler secret put NAME` inside `api`:

* `GITHUB_TOKEN`: a dedicated fine-grained GitHub token restricted to **Superfast-Robotics/robot-skill-hub**. Repository permissions: **Contents: Read and write**, **Pull requests: Read and write**, Metadata read (automatic). Organization approval/SSO may be required. Checks and workflow permissions are not needed. This credential never goes into an agent installation.
* `SUBMISSION_TOKENS_JSON`: JSON array, for example `[{"principal_id":"pilot-1","sha256":"REPLACE_WITH_SHA256_OF_RANDOM_SUBMISSION_TOKEN"}]`. Use at least 32 random bytes, encode as base64url. Store only its SHA-256 here. Issue the raw token privately to the allowed pilot agent through local `RSH_SUBMISSION_TOKEN`. Token rotation retaining the same `principal_id` preserves access to the principal's own receipts. Set `disabled: true` to revoke. Do not put tokens in Git, CLI arguments, skill docs, logs or browser JavaScript.

The Bearer credential is separate from project sharing policy. `publication.public_submission_allowed: true` is mandatory and acknowledges that the patch, environment, evidence and attribution may be publicly visible immediately in GitHub. Only submit a minimal patch after local policy allows public contribution. This assertion is not verified identity or robot verification.

`wrangler.jsonc` fixes the account, Worker and `api.superfastrobotics.com` custom domain. Wrangler login needs that account's Workers Scripts edit and zone/domain management permissions to create the custom domain; no paid upgrade is required by this design. Run `npm.cmd run deploy`. The public manifest URL is `https://hub.superfastrobotics.com/catalog/v1/publication.json`; keep `PUBLICATION_URL` in sync with Pages because redirects are deliberately rejected. The company holding page is a separate site at `https://superfastrobotics.com/`.

## Contract

* `POST /v1/submissions`: `Authorization: Bearer <pilot token>`, `Idempotency-Key: <8–128 ASCII chars>`, `Content-Type: application/json`. Body is the contribution bundle from the installed CLI. Maximum 64 KiB, streamed and enforced even without Content-Length. The server receipt's metadata must fit 24 KiB (a larger environment/evidence block yields 422 before a branch is created). Up to eight existing text files, each up to 128 KiB after applying the patch.
* `GET /v1/submissions/<submission_id>`: same principal token required. Other principals receive 404.
* `POST /v1/memories`: same scoped Bearer token and sharing assertion, with a structured finding instead of a patch. Maximum 16 KiB UTF-8 body. Identity derives from the principal and finding fingerprint; a caller-supplied Idempotency-Key is optional and does not change identity.
* `GET /v1/memories/<memory_id>`: owned memory status. Other principals receive 404.
* `GET /v1/capabilities`: public agent-readable endpoint, schema, policy and limit metadata. This does not grant public sharing permission.
* `GET /healthz`: public liveness only; does not imply configured secrets or a successful GitHub connection.

The repository and `main` base branch are compiled constants. For patch submissions, a catalog record maps its skill to exact paths via `contribution.allowed_paths`; only that record, its `docs/recipes/<id>.md`, and files under `recipes/<id>/` can be allowlisted. Workflow, credentials, installation skill code and upstream repository changes are rejected. Patch submissions accept only existing UTF-8 text-file edits. Renames, symlinks, deletion, binary diffs and new recipe files require manual maintainer contribution. The separate memory endpoint creates only its server-owned append-only entry. The API performs no evaluation, imports, shell calls or dependency installation.

For each accepted patch the API assigns `contrib-<16 hash characters>` as the new record version, preserving upstream pins and credit. Caller changes to record ID, source, license, attribution, hub evidence and permission mappings are rejected. Each proposed version has runtime evidence reset to `not_run` and compatibility marked `contributor_reported`; it cannot inherit verified task results from old code. Compatibility and requirements changes still require schema checks and manual review; they are not promoted to verified execution by intake.

The deterministic submission ID hashes the stable principal and idempotency key. The branch contains the patch plus a server receipt at `.hub/submissions/<id>.json` in one commit. Atomic Git ref creation selects the winner when concurrent requests race. An interrupted PR step resumes from the receipt. A second body for the same key returns 409. Draft PR metadata also stores the full receipt, so merged PRs and retries survive deleted branches. Duplicate discovery runs before current-base checks. A 201 response is sent only after the PR exists. A replay returns 200 and the same ID. After an ambiguous network failure, retry the same body and key.

Cloudflare rate-limit bindings restrict pilot writes to 10/minute and status to 60/minute per principal per Cloudflare location. These are approximate distributed limits, not a strict global quota. A denied request returns 429 with `Retry-After: 60`. GitHub's own quotas and Workers Free plan quotas also apply. At most a few dozen upstream calls occur per submission, below the Free plan's 50-subrequest limit. Request logging is disabled; API errors never echo request bodies or credentials.

## Review, checks and publication

Maintainers can apply `rsh:checking`, `rsh:needs_changes`, `rsh:rejected`, or `rsh:publish_failed` labels. Failed GitHub check runs yield `needs_changes`; completed successful checks yield `pending_review`. Intake's `hub_validation.runtime` remains `not_run` because it never runs submitted code. The contributor's evidence is always separate and self-reported.

Check runs are read without an Authorization header from the fixed **public** repository and a full commit SHA. [GitHub documents unauthenticated access to public check runs](https://docs.github.com/en/rest/checks/runs#list-check-runs-for-a-git-reference), so the dedicated token needs no Checks permission. All other GitHub operations retain the dedicated token; failed writes are never retried anonymously. Public reads share [GitHub's 60 requests/hour unauthenticated rate limit per originating IP](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api#primary-rate-limit-for-unauthenticated-users), so exhausted quota returns a retryable 503 rather than treating checks as successful. This public-read approach depends on the repository remaining public.

Merge alone yields `merged`. `published` requires the actually served public manifest to contain the receipt ID, exact new record/source versions and SHA-256 hashes of every changed file, plus proof that the PR merge commit is an ancestor of the manifest's deployed hub commit. A matching current record returns `publication_scope: current`.

Later maintainer edits can change the current recipe without rewriting the original submission receipt. To preserve publication history, maintainers archive proofs from previously served manifests in `catalog/publication-history.json`; the builder publishes these releases under `manifest.history`. Git history alone is not evidence of an earlier deployment. An archived proof must retain the original skill ID, record/source versions, receipt ID and every accepted path hash. Status accepts it only after verifying both ancestry links: PR merge commit → original deployed commit → current manifest commit. It returns `publication_scope: historical`, the original `published_hub_commit` and the archived, version-specific `recipe_url`. This records that the accepted version was published; it does not claim its bytes still match the current recipe. Current exact proof takes precedence over historical proof.

Publication failure yields `publish_failed` when checks or the maintainer label show failure. An unreachable manifest or mismatched proof does not yield `published`. Existing receipt hashes and contributor evidence are never rewritten to match later edits.

A new key and `supersedes_submission_id` can supplement the same principal's open `needs_changes` request. The old PR is closed and linked only after the replacement PR is durable. A failed replacement keeps the old request. Retry repairs an interrupted close/link step. Manual final code review and merge remain necessary; merging and deployment are not automatic approval of agent code.

## Append-only findings

The memory request schema is [memory.schema.json](../schemas/memory.schema.json). It requires `schema_version`, `skill_id`, the exact `base` record/source/hub commits, one of six finding kinds, `summary`, `observation`, nullable `resolution`, `environment`, `evidence`, `attribution` and `publication.public_submission_allowed: true`. Extra payload, source-path, log and upload fields are rejected.

The supported kinds are `failure_observation`, `missing_requirement`, `working_workaround`, `compatibility_note`, `docs_correction` and `successful_invocation`. Summary length is 5–300 characters; observation is 20–4,000; resolution is null or 1–4,000. Evidence remains `not_run` or `contributor_reported`, with a nullable command up to 2,000 characters and a result up to 4,000. The contributor label is at most 150 characters.

Environment values are strings, with at most 16 fields and 240 characters per value. `runtime` and `robot` are required; use `unknown` rather than guessing. Allowed keys are `runtime`, `runtime_version`, `robot`, `controller`, `observation`, `os`, `python`, `architecture`, `sim_backend`, `render_backend` and `package.<identifier>` package versions. Nested values, arbitrary environment keys and recognizable credentials are rejected. Credential checks inspect only the deliberately supplied packet; they do not scan the user's project and cannot replace redaction by the caller.

The original base hub commit must be an ancestor of current repository main. The canonical record at that exact commit must match the submitted skill ID, record version and source commit. If and only if that canonical file is absent, intake looks up the ID in that commit's `catalog/references.json`. A source reference uses `record_version: source-<full source.sha256>` and the exact source commit. Wrong or malformed canonical records cannot be bypassed through the reference fallback. The reference index alone has a bounded 256 KiB read allowance; other base files remain limited to 128 KiB.

Both preparation recipes and source-only references can receive shared findings. Storing a reference finding does not create an adapter, add preparation support or raise runtime evidence. Storage creates a branch from current main containing only the server-generated `.hub/memories/<memory_id>.json`, followed by an internal draft PR. It cannot write a caller-selected file or contact another repository.

The fingerprint is SHA-256 of sorted-key canonical JSON containing `schema_version`, `skill_id`, `base` with only `record_version` and `source_commit`, `kind`, `summary`, `observation`, `resolution`, `environment` and `evidence`. It excludes attribution, sharing metadata, the changing catalog hub commit and server metadata. The memory ID is SHA-256 of `rsh-memory-id-v1`, a NUL separator, the server's hashed principal ID, another NUL and the fingerprint, prefixed with `mem_`. Reordered JSON keys, attribution changes or a newer catalog commit do not duplicate the same caller's unchanged finding. A different caller has a different identity.

The first durable entry includes the original base, contributor evidence, fingerprint, principal hash, timestamp and `hub_validation.runtime: not_run`. Concurrent saves create one branch and one PR. Retries recover a branch-only partial failure or a deleted post-merge branch from the immutable PR marker. A duplicate returns the original base, content hash and PR; it does not replace the first attribution or evidence. `content_sha256` hashes the exact stored, pretty-printed JSON bytes with a trailing newline and is returned separately rather than embedded in the file it hashes.

Status distinguishes `stored`, `checking`, `pending_review`, `rejected`, `merged` and `published`. A failed check leaves the finding `stored` with `memory_checks_failed`; it does not invent a maintainer decision. Publication requires the live `manifest.memories` entry to match memory/skill IDs, fingerprint, content SHA-256, original record/source/base hub versions and PR merge ancestry. The public memory index contains maintainer-merged findings as data. A stored or published successful invocation remains contributor-reported evidence; neither memory storage nor review establishes hub runtime verification.

Automatic client saves require a prior, explicit `memory.public_save_allowed` project policy, matching allowed skill IDs/kinds and a scoped token. Missing policy leaves a local finding. An API token alone never grants sharing permission, and a finding submission must never block the user's original task.

Official references checked during implementation: [Worker secrets](https://developers.cloudflare.com/workers/configuration/secrets/), [rate-limit bindings](https://developers.cloudflare.com/workers/runtime-apis/bindings/rate-limit/), [Free limits](https://developers.cloudflare.com/workers/platform/limits/), [Git references](https://docs.github.com/en/rest/git/refs), [pull requests](https://docs.github.com/en/rest/pulls/pulls).
