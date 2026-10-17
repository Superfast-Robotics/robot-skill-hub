# Deployment and operations

Repository: https://github.com/Superfast-Robotics/robot-skill-hub  
Catalog fallback: https://superfast-robotics.github.io/robot-skill-hub/  
Worker: `robot-skill-hub-api`  
Cloudflare account: `8df378989a27166c1180b588582573df`  
API custom domain: https://api.superfastrobotics.com  
API fallback: https://robot-skill-hub-api.superfast-robotics.workers.dev

These are deployment targets. See `docs/verification.md` for what was actually confirmed.

## Local checks and deployment

Use Python 3.10 and Node 24. On Windows with restricted PowerShell scripts use `npm.cmd`/`npx.cmd`.

```powershell
python tools/build_catalog.py --hub-commit (git rev-parse HEAD) --base-url https://superfast-robotics.github.io/robot-skill-hub
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

## Scoped GitHub bot credential

Create a fine-grained token at https://github.com/settings/personal-access-tokens/new:

- Resource owner: **Superfast-Robotics**.
- Repository access: **Only select repositories → robot-skill-hub**.
- Repository permissions: **Contents: Read and write**, **Pull requests: Read and write**, **Checks: Read-only**. Metadata read is automatic.
- Use a reasonable expiry and rotate it before expiry. If the organization requires approval, approve the token in Organization Settings → Personal access tokens → Pending requests.

This API deliberately has no permission to change workflow files. Save the token as one line to `.local/github-bot-token.secret` (Git-ignored), or enter it into the hidden prompt of the script:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\configure-secrets.ps1
```

The script validates access, uploads `GITHUB_TOKEN` into Cloudflare Worker encrypted secrets, generates a random pilot token and uploads only its SHA-256 hash in `SUBMISSION_TOKENS_JSON`. It saves the limited client token in `.local/pilot-token.secret` and writes `.local/pilot-env.ps1`. It never prints either token. The pilot token has no GitHub permission.

Secrets can also be entered in Cloudflare → Workers & Pages → robot-skill-hub-api → Settings → Variables and Secrets:

```text
GITHUB_TOKEN = the repository-scoped fine-grained token
SUBMISSION_TOKENS_JSON = [{"principal_id":"pilot-1","sha256":"SHA256_OF_RANDOM_CLIENT_TOKEN"}]
```

Each caller needs a distinct principal. Set `disabled:true` on a configured token entry to revoke it. Keeping the same principal during rotation preserves ownership of its prior submissions. Preserve existing entries when adding another caller; the setup script replaces the pilot configuration. Keep raw tokens in private local configuration only.

## Custom domain

`api/wrangler.jsonc` attaches `api.superfastrobotics.com` as a Worker custom domain. Cloudflare manages its DNS record and certificate when the authenticated account has Worker routing permission.

To attach the catalog to the apex, add in Cloudflare → superfastrobotics.com → DNS → Records:

```text
Type: CNAME
Name: @
Target: superfast-robotics.github.io
Proxy status: DNS only
```

Do not replace unrelated existing DNS records. Then set repository Settings → Pages → Custom domain to `superfastrobotics.com`, and enable **Enforce HTTPS** after GitHub issues the certificate. Set repository Settings → Secrets and variables → Actions → Variables → `SITE_BASE_URL=https://superfastrobotics.com`. Re-run `Publish catalog`. Update `PUBLICATION_URL` in the Worker config to `https://superfastrobotics.com/catalog/v1/publication.json`, redeploy and verify it. The github.io URL remains the initial fallback until the custom domain is confirmed.

## Review and publication

Inspect draft PRs, upstream attribution, exact patch and contributor-reported evidence. The Worker accepts existing allowlisted files only and rejects operational changes, rewritten source pins and evidence escalation. Checks establish structure and API behavior; simulator evidence remains `not_run` unless a maintainer actually runs it on the documented environment. Merge only reviewed changes.

The catalog generator embeds merged submission IDs, exact record versions, upstream commits and hashes of contribution paths in `catalog/v1/publication.json`. Status becomes `published` only when the live manifest proves the merged change is included. Failed deployment never becomes a published success. Re-running the publication workflow does not create another submission.

## Free operation

Keep the Cloudflare account on the existing free plan and the GitHub repository public. This project uses no paid GPU, model API, database, queue or hosted simulator. The Worker rate limits submission to 10/minute and status reads to 60/minute per principal, caps payloads at 64 KiB, and disables application observability logs. Provider free limits still apply; exceeding them should fail rather than trigger a plan upgrade. No automatic paid plan conversion is configured.
