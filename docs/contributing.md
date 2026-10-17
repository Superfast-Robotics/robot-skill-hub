# Minimal public contributions

Preserve a useful correction made for the user's task locally first. Do not invent unrelated edits to generate PRs. Public submission is optional; the local patched project remains usable without submission or acceptance.

Only the hub's recipe, adapter, dependency metadata, recipe documentation and small reproduction paths declared by that record are accepted. Operational workflows, authentication settings, arbitrary repositories and upstream code are not submission targets. Preserve upstream authorship and license notices. Contributor labels are self-reported.

The project must explicitly allow the particular files to be shared publicly. Possessing an API token does not establish sharing permission. The submission payload, resulting branch, PR and contributor evidence can be public immediately. Never include whole projects, conversations, private datasets, keys or logs.

The installed skill reference describes `.robot-skill-hub.json` policy, `bundle`, `submit` and `submission-status`. Store `RSH_SUBMISSION_TOKEN` locally, and configure `RSH_API_URL=https://api.superfastrobotics.com`. This limited token authorizes submission and the caller's own status reads; it contains no GitHub permissions.

`POST /v1/submissions` requires Bearer authentication and `Idempotency-Key`. Retry the same exact request with the same key after interrupted responses. Reusing a key with another payload is a conflict. Keep the local draft on all failures. A corrected request uses a new key and may declare `supersedes_submission_id` for the caller's prior `needs_changes` request.

The Worker records the patch and server receipt, then creates an internal draft PR before returning `submitted`. Structural checks never claim robot execution. GitHub Actions checks run without deployment secrets. A maintainer reviews changes, marks the draft ready when appropriate, and merges manually. Labels `rsh:needs_changes`, `rsh:rejected` and other documented API status labels can guide review; consult the API README for implemented labels.

A merged PR remains `merged` until GitHub Pages serves a publication manifest proving the new record version, source pin, file hashes and submission inclusion. Failed publication is reported separately. `published` includes the reusable version and recipe URL. A new project can select that published version explicitly; previous projects are never silently updated.
