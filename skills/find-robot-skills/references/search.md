# Search, exact selections and recipe preparation

Read this when choosing filters, following result pages, working offline or preparing a Hub recipe. Source-file retrieval is in [source-files.md](source-files.md); finding recall and saving are in [memory.md](memory.md).

## Matching and filters

Search requires every query term as a word prefix, including offline and static fallback results. Use short task terms such as `MPC path tracking` or `DWA`. Standalone `A*`, `D*` and `RRT*` become `astar`, `dstar` and `rrtstar`; `Hybrid A*` and `D* Lite` retain their other terms. Embedded identifiers and repeated stars keep ordinary tokenization; plain `RRT` remains a word-prefix query. Other punctuation separates words. Punctuation-only queries return no matches, while an empty query browses the catalog. Synonyms require reviewed metadata; matching does not stem words. Native D1 uses SQLite unicode61, whose accents and Unicode version can differ from local/static matching.

For source discovery, task text plus one known robot or framework filter can select a source-declared label. Multiple environment filters require one declared combination. Missing values remain unknown and explicit mismatches are excluded. Robot types such as `humanoid` are searchable classifications, not robot-model names. A framework, robot label or source match does not establish execution compatibility.

For an English task sentence, opt in with `find "YOUR TASK" --query-mode task --runtime KNOWN_FRAMEWORK` or API/MCP `query_mode: "task"`. This ranks lexical matches using general request-word removal, conservative prefix stemming and fixed field weights; it uses no model or inferred synonyms. Default `all_terms` matching stays unchanged. Task mode supports ASCII queries of at most 240 characters and 16 distinct content terms. It scores at most 512 records remaining **after hard filters, before text matching**. `query_too_broad` requires narrower runtime, robot or other environment filters; more query text does not reduce that bound. A query containing only request words returns no matches.

Task responses report `query_terms`, `candidate_scope: hard_filtered_records`, candidate count/limit, and each row's `query_match` score with matched/unmatched terms. These explain lexical relevance, not task success or compatibility. Repeat `query_mode` with the returned pagination arguments. Native D1, static and local task ranking use the same bounded lexical rules; task mode does not use native FTS candidate retrieval. Offline coverage remains limited to the selected snapshot.

## Coverage, pagination and command handoff

Online discovery reads a bounded search page and the selected record, with local cache and bundled offline fallback. Preserve origin, generation and coverage; an offline compatibility subset is not the complete inventory. `--offline` prevents automatic discovery reads; `--refresh` requests fresh metadata. An explicit `--catalog FILE_OR_URL` selects that catalog.

`find` returns at most three candidates per page. When `next` is present, repeat the original query, filters and catalog/offline choice with its `--offset` and `--hub-commit`. A generation change rejects the continued search instead of switching catalogs. Mixed or unknown local generations report `pagination_stability: snapshot_required`; use one explicit catalog snapshot for a stable walk.

Returned `fetch_source_args`, a plan's `fetch_args`, and recipe `prepare_args` retain an explicit `--catalog` and `--offline` choice. Local catalog paths become absolute so the next command can use a different working directory. Find-generated recipe arguments also retain explicit runtime, runtime version, robot, controller, observation, OS, Python and architecture filters; unknown fields are never inferred. Other global flags and credentials are not copied.

If `catalog_handoff` reports a credential-bearing URL selector, rerunnable acquisition arguments are omitted; reapply that original selector privately. Manifest-based finding arguments remain independent of the catalog selector and retain the source actually acquired.

## Recipe preparation

Source references have no Hub preparation adapter. Use their source-file retrieval route and upstream setup instead. For a recipe, use its returned `prepare_args` and command arrays so exact record/source checks prevent preparing a different version.

Add `--project DIR --plan --json` to inspect preparation without source downloads, dependency installation or project writes. Plan-only preparation still uses online discovery by default and can create an anonymous client-ID cache outside the project. `RSH_TELEMETRY=off` disables that identifier; `--offline` prevents automatic discovery reads.

Remove `--plan` to verify the pinned source archive and prepare an isolated project where supported. Dependency installation requires `--install-deps` within the user's existing task scope. Preparation does not run the simulator. Preserve the project lock; catalog refreshes never change its pins. Use a new project for a different recipe version. Linux/Python/runtime support is record-specific; Windows can use `--download-only` for a supported recipe archive.

## Interpret actual execution evidence

Positive stages such as `import_verified` describe checks that passed, not task completion. Optional `evidence.hub_verification.last_task_attempt` records a separate task outcome with exact source, recipe, execution and environment pins. For `status: failed`, `execution_performed: true` and `success: false`, read the reason and immutable artifacts. That observation alone does not establish universal failure or its cause.

Search, inspection and preparation plans preserve the same attempt. `status: ready` describes the inspection or preparation operation, not successful robot execution. Preserve unfamiliar attempt statuses as data without inferring success, compatibility or permission to execute.
