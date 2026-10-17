# Verification record — 2026-10-17 (Asia/Seoul)

## Confirmed locally

- Python CLI and adapter tests: **22 passed**.
- Catalog integrity/publication tests: **6 passed**.
- Worker contract tests: **20 passed**; real workerd transport tests: **3 passed**; TypeScript check passed. All 51 automated tests passed across Python, catalog and API checks.
- Skill frontmatter validator and Python compile checks passed.
- Wrangler production dry-run passed; bundle about 34 KiB (10 KiB gzip).
- Exact upstream archive `33967b9e3ead1f841eec57cc9f31d0d8b8cf0907` downloaded, SHA-256 `d194e39e4f86063f7ea49f25c918ca7474d088ad8d5abdc37573daf4672f86d4` verified and 1,824 members extracted safely.
- Two clean projects preserved source pins, recipe files and project locks. The corrected adapter explicitly disables the renderer. Windows source-only preparation returned `needs_configuration`, created no simulation environment and did not install dependencies or execute a robot task.
- Independent installed-skill review rejected the actual Windows/Python 3.10 project for Linux simulation while preserving existing project files. Unknown environment values stayed unknown; explicit unsupported combinations returned no candidates.
- Desktop/mobile browser checks: stacking search returned one recipe; wrong runtime version and UR5 returned none; detail route opened; no console errors; 390px viewport had no horizontal overflow after correction.
- Actual missing-distribution execution of both wrappers returned failure JSON and exit 1. Wrapper mocks also checked false success, wrong version, solver failure and cleanup. These are **not** successful ManiSkill imports or robot task runs.
- Fake GitHub adapter tests verified concurrent submissions produce one PR; same-key conflicts; branch-only recovery; ownership; path/base/source rejection; review states; publication proof; failed publication; superseding requests. The real Python catalog builder round-tripped a fake accepted change and receipt. These are **local contract tests**, not live GitHub PR creation.

## Confirmed external operations

- Public GitHub repository created and implementation pushed: https://github.com/Superfast-Robotics/robot-skill-hub.
- `Checks` workflow completed successfully on the pushed implementation.
- GitHub Pages publication completed successfully after enabling the repository's Pages source. The catalog root, PickCube detail, catalog JSON, publication manifest, quickstart, sitemap and llms.txt all returned HTTP 200. The live manifest contained the actual deployed hub commit and both records.
- The CLI fetched the live published catalog and selected StackCube for the full documented Linux/Python/architecture/runtime/robot/controller/observation combination, with no missing requirements and evidence still `source_reviewed`.
- Cloudflare Worker `robot-skill-hub-api` deployed to the specified account without a paid-plan change.
- HTTPS health requests returned 200 on both https://api.superfastrobotics.com/healthz and https://robot-skill-hub-api.superfast-robotics.workers.dev/healthz.
- A repository-scoped token with Contents/Pull requests read-write and no Checks permission was configured through Worker secrets. Live health now reports `submission_configured:true`. Public check-run reads require no additional token permission.
- `skills` CLI **1.7.2** installed the published GitHub skill into an isolated project for both Codex and Claude Code. The installed copies successfully ran find/inspect independently of the repository tree. No global agent installation was changed.

## Live contribution and domain verification

- Canonical catalog https://superfastrobotics.com/ and API https://api.superfastrobotics.com/healthz both returned HTTP 200 with valid HTTPS. GitHub Pages HTTPS enforcement is enabled; the old github.io project URL redirects to the custom domain.
- Real `POST /v1/submissions` returned **201** and created exactly one internal draft [PR #1](https://github.com/Superfast-Robotics/robot-skill-hub/pull/1). The change documents the actually verified Windows source-only preparation command and its non-execution outcome.
- Two concurrent replays returned **200**, the same submission ID and the same PR. A changed body using the same key returned **409 idempotency_key_conflict**. Missing authentication returned **401 invalid_token**. Status returned **pending_review** after CI.
- Independent review confirmed exactly three changed files (recipe documentation, server-generated record and receipt), preserved upstream source/license/attribution, matching content hashes, and no promotion of runtime evidence. The operator marked the draft ready and merged after successful checks. The Worker never merges automatically.
- Live status returned **published**, version `contrib-a5dd78ad4e1d4e3d`, source commit `33967b9e3ead1f841eec57cc9f31d0d8b8cf0907` and the canonical recipe URL after the public manifest included merge commit `37d2029499e1eb1c9016ebd9b00ceb438863afe4`. The first status read immediately after merge received a transient 503; a later retry succeeded. The intermediate `merged` state was not directly observed live; its behavior is covered by contract/runtime tests.
- After automatic branch deletion (GitHub ref returned **404**), replay of the original older-base request still returned **200** with the original ID/PR. Repository pull request count remained exactly one.
- A third clean project fetched the published catalog and prepared that exact new version from the SHA-checked cached upstream archive. The new lock pins the published record/source/hub commit; the previous project's lock hash remained unchanged. Result: **needs_configuration**, no venv, no dependency installation, no robot execution. This verifies API-mediated publication and source preparation reuse, not robot task completion.
- Actual workerd testing found and fixed two transport issues absent from Node-only tests: native fetch class receiver binding and unsupported redirect:error. Persistent workerd tests now cover actual fetch invocation, manual redirect rejection, and manifest-based publication using intercepted outbound calls and dummy credentials.

## Pending / unverified

- ManiSkill dependency installation, successful ManiSkill import and PickCube/StackCube task completion on Linux are **not_run / 미검증**. This Windows host is not a supported simulator environment; Docker's engine was unavailable and no general WSL Linux distribution was installed. No GPU or paid execution service was provisioned.
- Unbranded agent discovery, automatic skill selection by a fresh agent, external search indexing, skills.sh search inclusion and Context7 indexing are **unverified**. A repository install test does not establish them.

The original supplied planning documents remain local and were not published. No tokens, private datasets, session transcripts or full project logs were uploaded.
