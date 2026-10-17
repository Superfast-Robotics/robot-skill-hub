# Minimal contributions

Only preserve a reusable fix already made during the user's work. The API accepts changes to existing hub-owned recipe adapters, dependency/compatibility metadata, recipe docs and small reproduction tests within each record's `contribution.allowed_paths`. The pilot limits requests to 64 KiB and accepts text modifications only, not file creation, deletion or renaming. Upstream source changes stay local unless they can be expressed as a hub adapter. Never bundle a whole project, conversation, private research data or credentials.

The project policy file is `.robot-skill-hub.json` (or explicit `--policy FILE`). The user must already have authorized this scope. A token never substitutes for public sharing permission. An allowed policy can be as narrow as:

```json
{
  "publication": {
    "public_submission_allowed": true,
    "allowed_skill_ids": ["maniskill-panda-pick-cube"],
    "allowed_paths": ["recipes/maniskill-panda-pick-cube/*", "docs/recipes/maniskill-panda-pick-cube.md"]
  }
}
```

Prepare a real unified diff in `fix.patch`. Supply only its metadata in `fix-metadata.json`, for example a documentation-only correction:

```json
{
  "change_kind": "docs_fix",
  "summary": "Explain a reproduction failure observed in this project.",
  "environment": {"runtime": "unknown", "robot": "unknown"},
  "evidence": {
    "level": "not_run",
    "command": null,
    "result": "Documentation change only; robot execution was not performed.",
    "reported_by": "submitter"
  },
  "attribution": {
    "contributor_label": "project contributor",
    "preserve_upstream_attribution": true
  }
}
```

Use `contributor_reported` for actual submitter-run results, with the real command and result. This does not establish hub verification or verified author identity. Allowed change kinds are `dependency_fix`, `invocation_fix`, `docs_fix`, `compatibility_fix`, `test_fix`.

```sh
python /ABSOLUTE_SKILL_PATH/scripts/rsh.py bundle maniskill-panda-pick-cube --project ./experiment --patch ./fix.patch --metadata ./fix-metadata.json --output ./contribution.json --json
python /ABSOLUTE_SKILL_PATH/scripts/rsh.py submit ./contribution.json --project ./experiment --json
python /ABSOLUTE_SKILL_PATH/scripts/rsh.py submission-status SUBMISSION_ID --json
```

The bundle pins `base.hub_commit`, `base.record_version` and `base.source_commit` from the prepared project lock or selected snapshot. A GitHub-installed skill's bundled snapshot may predate the deployed catalog. For a new contribution, explicitly inspect the current published catalog with `--catalog https://superfastrobotics.com/catalog/v1/index.json`. If a server reports a stale base, preserve the old bundle, rebase and verify the real patch against the current hub commit, then make a new bundle with `--hub-commit` for that verified base and a new key. Existing project locks are never silently changed. If the snapshot lacks a commit, provide the exact original hub commit; never substitute latest blindly. Empty changes return `no_changes`. Missing sharing scope leaves a local bundle with `sharing_not_allowed` and performs no network request.

Set `RSH_API_URL` to the deployed API base and `RSH_SUBMISSION_TOKEN` to an operator-issued pilot token in the local process environment. Tokens authorize submission and only that principal's status reads. Do not store tokens in skill files, patches, catalogs or logs. The client checks sharing policy again at submission and will not follow API redirects with credentials.

`submit` uses a stable SHA-256 derived Idempotency-Key unless explicitly provided. It writes a local `contribution.receipt.json` before transmission so lost responses can be retried with the same body/key. Preserve the bundle and retry identity after errors. A different body needs a new key. The client performs no background retries or polling.

The server returns 201 only after a persistent internal PR exists. Distinguish `submitted`, `checking`, `needs_changes`, `pending_review`, `merged`, `published`, `rejected`, `publish_failed` and `superseded`. A merged PR can still fail publication. For `needs_changes`, preserve the old request and submit the correction with a fresh key and `supersedes_submission_id` in metadata. The server supersedes the old request only after the new PR is durable.

On 401/403 configure the pilot token; on 409 inspect the base or key conflict; on 413 shrink the minimal patch; on 422 correct the named field/path; on 429 respect `Retry-After`; on 503 retry the same body/key a limited number of times when requested. Never let submission failure block the user's research task. After publication inspect the returned `published_version`, `source_commit`, `compatibility` and `recipe_url`; use the new version explicitly in a clean project. Existing locks remain fixed.
