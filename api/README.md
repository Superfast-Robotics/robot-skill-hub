# Submission API

Small Cloudflare Worker; GitHub is its durable receipt store. Search and preparation remain static/local. No database, queue, paid plan or runtime execution is used by this API.

```powershell
cd api
npm.cmd ci
npm.cmd test
npm.cmd run check
npm.cmd run dev
```

`test` uses an in-memory fake GitHub adapter and mocked HTTP adapter. These tests verify the protocol, concurrency and recovery; they do not prove live GitHub PR creation or robot execution.

## Secrets and permission boundary

Set these under Cloudflare dashboard → Workers & Pages → robot-skill-hub-api → Settings → Variables and Secrets (type **Secret**), or run `npx.cmd wrangler secret put NAME` inside `api`:

* `GITHUB_TOKEN`: a dedicated fine-grained GitHub token restricted to **Superfast-Robotics/robot-skill-hub**. Repository permissions: **Contents: Read and write**, **Pull requests: Read and write**, Metadata read (automatic). Organization approval/SSO may be required. Checks and workflow permissions are not needed. This credential never goes into an agent installation.
* `SUBMISSION_TOKENS_JSON`: JSON array, for example `[{"principal_id":"pilot-1","sha256":"REPLACE_WITH_SHA256_OF_RANDOM_SUBMISSION_TOKEN"}]`. Use at least 32 random bytes, encode as base64url. Store only its SHA-256 here. Issue the raw token privately to the allowed pilot agent through local `RSH_SUBMISSION_TOKEN`. Token rotation retaining the same `principal_id` preserves access to the principal's own receipts. Set `disabled: true` to revoke. Do not put tokens in Git, CLI arguments, skill docs, logs or browser JavaScript.

The Bearer credential is separate from project sharing policy. `publication.public_submission_allowed: true` is mandatory and acknowledges that the patch, environment, evidence and attribution may be publicly visible immediately in GitHub. Only submit a minimal patch after local policy allows public contribution. This assertion is not verified identity or robot verification.

`wrangler.jsonc` fixes the account, Worker and `api.superfastrobotics.com` custom domain. Wrangler login needs that account's Workers Scripts edit and zone/domain management permissions to create the custom domain; no paid upgrade is required by this design. Run `npm.cmd run deploy`. The public manifest URL is the canonical custom-domain URL `https://superfastrobotics.com/catalog/v1/publication.json`; keep `PUBLICATION_URL` in sync with Pages because redirects are deliberately rejected.

## Contract

* `POST /v1/submissions`: `Authorization: Bearer <pilot token>`, `Idempotency-Key: <8–128 ASCII chars>`, `Content-Type: application/json`. Body is the contribution bundle from the installed CLI. Maximum 64 KiB, streamed and enforced even without Content-Length. The server receipt's metadata must fit 24 KiB (a larger environment/evidence block yields 422 before a branch is created). Up to eight existing text files, each up to 128 KiB after applying the patch.
* `GET /v1/submissions/<submission_id>`: same principal token required. Other principals receive 404.
* `GET /healthz`: public liveness only; does not imply configured secrets or a successful GitHub connection.

The repository and `main` base branch are compiled constants. A catalog record maps its skill to exact paths via `contribution.allowed_paths`; only that record, its `docs/recipes/<id>.md`, and files under `recipes/<id>/` can be allowlisted. Workflow, credentials, installation skill code and upstream repository changes are rejected. Only existing UTF-8 text-file edits are accepted. Renames, symlinks, deletion, binary diffs and new files require manual maintainer contribution. The API performs no evaluation, imports, shell calls or dependency installation.

For each accepted patch the API assigns `contrib-<16 hash characters>` as the new record version, preserving upstream pins and credit. Caller changes to record ID, source, license, attribution, hub evidence and permission mappings are rejected. Each proposed version has runtime evidence reset to `not_run` and compatibility marked `contributor_reported`; it cannot inherit verified task results from old code. Compatibility and requirements changes still require schema checks and manual review; they are not promoted to verified execution by intake.

The deterministic submission ID hashes the stable principal and idempotency key. The branch contains the patch plus a server receipt at `.hub/submissions/<id>.json` in one commit. Atomic Git ref creation selects the winner when concurrent requests race. An interrupted PR step resumes from the receipt. A second body for the same key returns 409. Draft PR metadata also stores the full receipt, so merged PRs and retries survive deleted branches. Duplicate discovery runs before current-base checks. A 201 response is sent only after the PR exists. A replay returns 200 and the same ID. After an ambiguous network failure, retry the same body and key.

Cloudflare rate-limit bindings restrict pilot writes to 10/minute and status to 60/minute per principal per Cloudflare location. These are approximate distributed limits, not a strict global quota. A denied request returns 429 with `Retry-After: 60`. GitHub's own quotas and Workers Free plan quotas also apply. At most a few dozen upstream calls occur per submission, below the Free plan's 50-subrequest limit. Request logging is disabled; API errors never echo request bodies or credentials.

## Review, checks and publication

Maintainers can apply `rsh:checking`, `rsh:needs_changes`, `rsh:rejected`, or `rsh:publish_failed` labels. Failed GitHub check runs yield `needs_changes`; completed successful checks yield `pending_review`. Intake's `hub_validation.runtime` remains `not_run` because it never runs submitted code. The contributor's evidence is always separate and self-reported.

Check runs are read without an Authorization header from the fixed **public** repository and a full commit SHA. [GitHub documents unauthenticated access to public check runs](https://docs.github.com/en/rest/checks/runs#list-check-runs-for-a-git-reference), so the dedicated token needs no Checks permission. All other GitHub operations retain the dedicated token; failed writes are never retried anonymously. Public reads share [GitHub's 60 requests/hour unauthenticated rate limit per originating IP](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api#primary-rate-limit-for-unauthenticated-users), so exhausted quota returns a retryable 503 rather than treating checks as successful. This public-read approach depends on the repository remaining public.

Merge alone yields `merged`. `published` requires the actually served public manifest to contain the receipt ID, exact new record/source versions and SHA-256 hashes of every changed file, plus proof that the PR merge commit is an ancestor of the manifest's deployed hub commit. Publication failure yields `publish_failed` when checks or the maintainer label show failure. Unreachable or stale manifests cannot yield `published`.

A new key and `supersedes_submission_id` can supplement the same principal's open `needs_changes` request. The old PR is closed and linked only after the replacement PR is durable. A failed replacement keeps the old request. Retry repairs an interrupted close/link step. Manual final code review and merge remain necessary; merging and deployment are not automatic approval of agent code.

Official references checked during implementation: [Worker secrets](https://developers.cloudflare.com/workers/configuration/secrets/), [rate-limit bindings](https://developers.cloudflare.com/workers/runtime-apis/bindings/rate-limit/), [Free limits](https://developers.cloudflare.com/workers/platform/limits/), [Git references](https://docs.github.com/en/rest/git/refs), [pull requests](https://docs.github.com/en/rest/pulls/pulls).
