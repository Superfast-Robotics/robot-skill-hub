# Coverage and license boundaries

The main catalog and coverage.html show deterministic tables generated from the complete current catalog. The same report is available at catalog/v1/coverage.json and GET https://api.superfastrobotics.com/v1/coverage. The API binds bytes to the current publication checksum and rejects a mismatched optional hub_commit. The report does not execute code, query external telemetry or estimate general accuracy.

Completed recipes require retained evidence matching the current adapter bytes, source, version and, for the finite conversion cohort, frozen inputs, source guards, model, interface and measured package versions. A retained failed task attempt is counted separately. Missing or stale evidence is unbound; an installation/import check alone is not a task run. Current records are not promoted by older versions' attempts. Source references keep their own execution evidence.

Rows count recipes, not unique robots. Numerical operations, synthetic simulation operations and robot tasks remain distinct. Tested environments are explicit version/OS/model combinations. Physical robot completions are reported separately. Case totals include retained platform-specific runs for current recipes; historical repetitions, invalid-input checks and composition checks are not silently added to those case totals.

Each reference is counted once in its framework. Robot labels, runtime labels, robot types and capability tags can overlap; they describe declared source coverage. Missing or generic labels are preserved rather than inferred from names, paths or prose. Model assets, policy weights, datasets and hardware drivers do not become executable skills merely because a source is indexed.

Platform code uses Apache-2.0. Hub-authored execution adapters and their source templates use the directory-specific MIT license; prepared recipes receive that text separately from the upstream checkout. Original upstream licenses and notices remain applicable. See LICENSE_SCOPE.md and license-policy.json for the full component policy. The change does not revoke permissions on earlier MIT releases.
