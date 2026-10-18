# Deployment and operations

| Component | Location |
| :--- | :--- |
| Hub repository | https://github.com/Superfast-Robotics/robot-skill-hub |
| Company website | https://superfastrobotics.com/ |
| Company website repository | https://github.com/Superfast-Robotics/superfast-robotics.github.io |
| Catalog | https://hub.superfastrobotics.com/ |
| Worker | `robot-skill-hub-api` |
| Cloudflare account | `8df378989a27166c1180b588582573df` |
| API custom domain | https://api.superfastrobotics.com |
| API fallback | https://robot-skill-hub-api.superfast-robotics.workers.dev |

These are deployment targets. See `docs/verification.md` for what was actually confirmed.

## Local checks and deployment

Use Python 3.10 and Node 24. On Windows with restricted PowerShell scripts use `npm.cmd`/`npx.cmd`.

```powershell
python tools/build_catalog.py --hub-commit (git rev-parse HEAD) --base-url https://hub.superfastrobotics.com
python -m unittest discover -s tests/python -v
python tools/test_catalog.py -v
npm.cmd --prefix api ci
npm.cmd --prefix api run check
npm.cmd --prefix api test
Push-Location api
npx.cmd wrangler deploy --dry-run
# After the checks pass:
npx.cmd wrangler deploy
Pop-Location
git push origin main
```

In GitHub repository Settings → Pages → Build and deployment, select **GitHub Actions**. `Publish catalog` builds static output on main pushes and deploys it with a separate job. The build job has read-only repository access; the deployment job receives only Pages/id-token permission and does not run submitted code. PR checks receive no Worker or publication credentials. Submitted code is never run by the Worker.

Worker deployment is intentionally an explicit local operation. Catalog changes deploy automatically after maintainer merge. No Cloudflare account token is stored in GitHub Actions.

After Pages deploys, a read-only checkout job calls `tools/sync_catalog.py --hub-commit "$GITHUB_SHA"`. Its separate `CATALOG_SYNC_KEY` secret authorizes only the Worker's fixed `/internal/catalog-sync` endpoint. The helper advances bounded pages until the exact search and finding generation is active. It retries brief propagation failures without changing the expected commit; a superseded deployment cannot replace a newer generation. PR workflows receive no sync credential. For manual operation, supply the secret through the process environment rather than a command argument.

An explicit D1 daily row-write limit returns `catalog_write_limit` with a bounded `Retry-After` until the next UTC midnight. The client exits 75 as deferred without retrying or resetting staging. `Resume reviewed catalog index` runs daily at 00:15 UTC and supports manual dispatch; it shares the index concurrency group with Pages synchronization. It first pins the actually published version through a bounded credential-free read, which can differ from main after a failed deployment. Already-active matching generations require no writes. Scheduled Actions can start late. While staging, public discovery uses the complete checksum-bound static search view if it fits 2 MiB; otherwise it reports `catalog_sync_required`. All backends use basic word-prefix matching; native unicode61 accent/version behavior can still differ. A deferred sync does not establish native activation.

## Scoped GitHub bot credential

Create a fine-grained token at https://github.com/settings/personal-access-tokens/new:

- Resource owner: **Superfast-Robotics**.
- Repository access: **Only select repositories → robot-skill-hub**.
- Repository permissions: **Contents: Read and write**, **Pull requests: Read and write**. Metadata read is automatic.
- Use a reasonable expiry and rotate it before expiry. If the organization requires approval, approve the token in Organization Settings → Personal access tokens → Pending requests.

This API deliberately has no permission to change workflow files. Save the token as one line to `.local/github-bot-token.secret` (Git-ignored), or enter it into the hidden prompt of the script:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\configure-secrets.ps1
```

Use this script only for the first deployment: it stops when a local pilot token or caller registry already exists. The script validates access, uploads `GITHUB_TOKEN` into Cloudflare Worker encrypted secrets, generates a random pilot token and uploads only its SHA-256 hash in `SUBMISSION_TOKENS_JSON`. It saves the limited client token in `.local/pilot-token.secret` and writes `.local/pilot-env.ps1`. It never prints either token. The pilot token has no GitHub permission.

Load the client environment from the project directory without executing another
PowerShell script (this also works when the default script policy is restricted):

```powershell
$env:RSH_API_URL = 'https://api.superfastrobotics.com'
$env:RSH_SUBMISSION_TOKEN = (Get-Content -LiteralPath '.local\pilot-token.secret' -Raw).Trim()
```

Secrets can also be entered in Cloudflare → Workers & Pages → robot-skill-hub-api → Settings → Variables and Secrets:

```text
GITHUB_TOKEN = the repository-scoped fine-grained token
SUBMISSION_TOKENS_JSON = [{"principal_id":"pilot-1","sha256":"SHA256_OF_RANDOM_CLIENT_TOKEN"}]
```

Each caller needs a distinct principal. Set `disabled:true` on a configured token entry to revoke it. Keeping the same principal during rotation preserves ownership of its prior submissions. Keep raw tokens in private local configuration only.

### Add, rotate or revoke an allowed agent

Use `tools/manage_agent_tokens.py` for subsequent caller changes. It only changes local files, keeps all existing entries, generates a separate random 256-bit token for each caller, refuses duplicate principals unless rotating, and never prints tokens or token hashes. Registry, export and token files must remain under Git-ignored `.local/`. File permissions are owner-only on POSIX; on Windows they inherit the private workspace directory's ACL. Do not copy the directory into a public artifact.

Cloudflare cannot return an existing secret value. Establish a complete operator-held registry before adding callers. If the existing deployment has exactly the single original `pilot-1`, first verify that the pilot token still authenticates and that its principal matches a previously verified server receipt. Then adopt that known complete baseline:

```powershell
python tools/manage_agent_tokens.py adopt-pilot --receipt-file .local/live-memory-proof/stored-memory.json --confirm-complete-registry
```

The adoption command checks the receipt's hashed principal and refuses to overwrite an existing registry. The confirmation explicitly asserts that there are no other configured callers; the command cannot discover omitted callers. For an existing multi-caller deployment, obtain the complete hashed JSON array from its operator instead, save it privately, and use `import --input-json .local/complete-callers.json --confirm-complete-registry`. Do not reconstruct a partial list from the callers currently in use.

Create the next caller and a separate, immutable deployment snapshot:

```powershell
python tools/manage_agent_tokens.py add agent-2 --token-file .local/agent-2-token.secret
python tools/manage_agent_tokens.py list
python tools/manage_agent_tokens.py export --output-json .local/callers-deploy-2.json
Push-Location api
Get-Content -LiteralPath ..\.local\callers-deploy-2.json -Raw | npx.cmd wrangler secret put SUBMISSION_TOKENS_JSON
if ($LASTEXITCODE -ne 0) { throw 'Caller registry upload failed; do not distribute the new token.' }
Pop-Location
```

Use a new snapshot filename for each deployment. Verify both an existing caller and the new caller after upload, then distribute only the new caller's token through private project configuration. An upload replaces the whole secret, which is why the complete registry must be preserved. The helper does not upload anything or change `GITHUB_TOKEN`.

For rotation, run `rotate agent-2 --token-file .local/agent-2-rotated.secret`; it disables prior tokens while retaining the same principal and previous submission ownership. For revocation, run `revoke agent-2`; it disables every token for that principal. Both operations remain local until you export a new complete snapshot and upload it. Preserve the previous snapshot for rollback if a deployment fails; raw tokens are not included in the registry or snapshots. A new caller still needs explicit project sharing policy; authentication never grants public-sharing consent.

## Custom domain

`api/wrangler.jsonc` attaches `api.superfastrobotics.com` as a Worker custom domain. Cloudflare manages its DNS record and certificate when the authenticated account has Worker routing permission.

The catalog uses `hub.superfastrobotics.com`; the apex `superfastrobotics.com` belongs to the company website, hosted from the separate `superfast-robotics.github.io` repository. For a fresh catalog setup, add in Cloudflare → superfastrobotics.com → DNS → Records:

```text
Type: CNAME
Name: hub
Target: superfast-robotics.github.io
Proxy status: DNS only
```

Do not replace the company site's apex records or unrelated DNS records. Set repository Settings → Pages → Custom domain to `hub.superfastrobotics.com`, and enable **Enforce HTTPS** after GitHub issues the certificate. Set repository Settings → Secrets and variables → Actions → Variables → `SITE_BASE_URL=https://hub.superfastrobotics.com`. Re-run `Publish catalog`. Update `PUBLICATION_URL` in the Worker config to `https://hub.superfastrobotics.com/catalog/v1/publication.json`, redeploy and verify it. GitHub redirects the old github.io project URL to the catalog's canonical domain. The Worker uses the catalog manifest URL directly.

## Review and publication

Inspect draft PRs, upstream attribution, exact patch and contributor-reported evidence. The Worker accepts existing allowlisted files only and rejects operational changes, rewritten source pins and evidence escalation. Checks establish structure and API behavior; simulator evidence remains `not_run` unless a maintainer actually runs it on the documented environment. Merge only reviewed changes.

The catalog generator embeds merged submission IDs, exact record versions, upstream commits and hashes of contribution paths in per-receipt `/catalog/v2/submissions/{submission_id}.json` and `/catalog/v2/memories/{memory_id}.json` proofs. The complete legacy `catalog/v1/publication.json` remains available while it fits its byte budget. Status becomes `published` only when the live proof establishes the merged change, exact content and Git ancestry. Failed deployment never becomes a published success. Re-running the publication workflow does not create another submission.

## Free operation

Keep the Cloudflare account on the existing free plan and the GitHub repository public. This project uses no paid GPU, model API, database, queue or hosted simulator. The Worker rate limits submission to 10/minute and status reads to 60/minute per principal, caps payloads at 64 KiB, and disables application observability logs. Provider free limits still apply; exceeding them should fail rather than trigger a plan upgrade. No automatic paid plan conversion is configured.

[D1 free quotas](https://developers.cloudflare.com/d1/platform/pricing/) include 100,000 written rows per day and reset at 00:00 UTC. They apply across the account, including catalog indexing and access measurements. Measurements are best-effort and may lose events during storage failures. Stored counts are lower bounds during a known interruption; do not estimate missing accesses, reclassify unrelated traffic or replay requests to fill the gap. Reduce unnecessary catalog publications and resume the existing generation after the quota resets. No paid fallback is configured.

## CPU runtime verification

The manual `Verify pinned CPU runtime` workflow runs one named batch on the standard public Ubuntu runner, never a GPU or larger runner. `initial-two` remains the default. The other explicit batches are `panda-transport`, `panda-insertion`, `panda-tools`, `panda-stacking`, `xarm6-basic`, `xarm6-insertion` and `so100-basic`. Together these non-overlapping batches cover the 17 reviewed preparation recipes, with at most three tasks per run and seed 0. No batch starts on push or on a schedule.

Preview metadata locally with `python tools/run_runtime_verification.py --batch xarm6-basic --plan`. This creates no project and performs no download, installation or execution. An actual workflow prepares isolated environments, installs the pinned CPU dependencies, and records each selected robot/controller and actual result under the explicit 1000-step Hub horizon and 180-second task timeout. The 25-minute job limit still applies. Logs, environment and source/adapter pins are retained as artifacts for one day; preserve inspected evidence before expiry. Failed, timed-out and unexecuted tasks remain distinct from successful task completion. The harness never publishes findings or promotes catalog evidence automatically.

## Task-memory operations

Memory requests use the same repository-scoped Worker credential and caller token; no broader GitHub permission is required. `POST /v1/memories` accepts at most 16 KiB of structured JSON, checks exact historical catalog pins, and creates an internal draft PR. `GET /v1/memories/MEMORY_ID` is owner-scoped. Public API capabilities describe the current endpoints and limits.

The caller's `.robot-skill-hub.json` must separately authorize `memory.public_save_allowed` and explicit skill/kind allowlists. Existing patch-publication permission is insufficient. A configured token alone is insufficient. Clients save to their local outbox first, make at most one automatic POST when authorized, and retain failed deliveries for an explicit bounded `flush`. No background retry or polling is required.

Review a memory as contributor-reported data. Check the minimal finding, exact pins, environment, evidence and absence of private material. Do not run remembered commands as part of validation. The Worker never executes memory text. Merge only reviewed data; the publisher includes entries from main in `catalog/v1/memories.json` and records their fingerprint, exact server-file hash and pinned base in the publication manifest. `stored`, `merged` and `published` remain different states. Main publication does not promote contributor evidence to Hub runtime verification.

The machine entry contract is maintained in `docs/agent-contract.json`; the builder adds current publication metadata and serves `/agent.json` and `/.well-known/robot-skill-hub.json`. Discovery indexes may refresh automatically, while prepared project locks remain fixed. See [memory.md](memory.md) for caller policy and [verification.md](verification.md) for checks actually performed.

## Bounded catalog capacity

Complete search and finding discovery use checksum-bound v2 manifests and pages. Each manifest is at most 128 KiB; each page is at most 128 KiB and 100 records. Per-ID skill metadata and per-receipt proofs are at most 256 KiB. A separate `CATALOG` D1 database stages and atomically activates matching search/finding generations; native FTS5 and compatibility indexes answer bounded queries. Stable content hashes reuse documents across publications. See [API operations](../api/README.md) for schema, synchronization and free quotas.

The v1 full recipe/reference/memory indexes and offline snapshots are compatibility views capped at 8 MiB. If a complete view no longer fits, it explicitly reports incomplete coverage and links to its complete v2 manifest. Thin v1 search is omitted above 2 MiB and aggregate publication proof above 512 KiB; stale output files are removed. Public search never uses an incomplete view as a complete total. Source identity lookup retains checksum-bound 256 KiB shards and a 128 KiB manifest.

These finite byte, manifest and free-database limits still require monitoring and a versioned capacity migration before exhaustion. This deployment does not claim unlimited storage or an exhaustive Internet index. Builds fail before an oversized complete leaf or manifest can replace the working publication. CLI fallback reports its actual origin, commit, scope and coverage; existing project locks remain fixed.
