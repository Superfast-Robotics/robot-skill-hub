# Verification record — 2026-10-17 to 2026-10-18 (Asia/Seoul)

## Confirmed locally

- Python CLI, adapter and operator tests: **67 passed** on Linux, including the real symlink regression. Windows passed the other 66 and skipped that one privilege-dependent case.
- Catalog integrity/publication tests: **13 passed**.
- Worker contract tests: **39 passed**; real workerd transport tests: **5 passed**; TypeScript check passed. All **124 automated tests** passed without skips in Linux Checks run [39042244895](https://github.com/Superfast-Robotics/robot-skill-hub/actions/runs/39042244895).
- Agent-first update: 17 preparation recipes and 40 official source references pass validation. All generated HTML has no CSS or client-side JavaScript; JSON, Markdown, robots, sitemap and full-text discovery files are generated together.
- The 15 added adapters preserve exact robot/task/controller contracts in dependency-mocked tests. DrawSVG source-only preparation in another clean Windows project verified the real pinned archive, recipe files and lock without creating an environment, installing dependencies or executing a simulator.
- Official MuJoCo, Bullet and robosuite reference files were fetched at exact release commits and hashed; entrypoints, imports and licenses were inspected. They are discovery references without Hub preparation adapters. Repository stars are a dated interest proxy, not usage counts.
- The earlier live publication manifest was captured before English documentation edits, and every original contribution-path hash matched the deployed Git commit. Its original receipt and archived record stay immutable. Historical status tests require the exact original receipt, hashes, version, source and both merge/deployment ancestry links.
- Skill frontmatter validator and Python compile checks passed.
- Wrangler production dry-run passed; current Worker bundle **54.90 KiB** (**14.43 KiB gzip**).
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
- Cloudflare Worker `robot-skill-hub-api` version `cb17a842-5ae1-4057-a0f2-4adc9bf549a2` deployed to the specified account without a paid-plan change.
- HTTPS health requests returned 200 on both https://api.superfastrobotics.com/healthz and https://robot-skill-hub-api.superfast-robotics.workers.dev/healthz.
- A repository-scoped token with Contents/Pull requests read-write and no Checks permission was configured through Worker secrets. Live health now reports `submission_configured:true`. Public check-run reads require no additional token permission.
- `skills` CLI **1.7.2** installed the published GitHub skill into an isolated project for both Codex and Claude Code. The installed copies successfully ran find/inspect independently of the repository tree. No global agent installation was changed.

## Live contribution and domain verification

- At the initial deployment, the catalog at its then-canonical apex domain, `superfastrobotics.com`, and API https://api.superfastrobotics.com/healthz both returned HTTP 200 with valid HTTPS. GitHub Pages HTTPS enforcement was enabled and the old github.io project URL redirected to that catalog domain. The catalog's new deployment target is https://hub.superfastrobotics.com/; the apex is reserved for the company website.
- Real `POST /v1/submissions` returned **201** and created exactly one internal draft [PR #1](https://github.com/Superfast-Robotics/robot-skill-hub/pull/1). The change documents the actually verified Windows source-only preparation command and its non-execution outcome.
- Two concurrent replays returned **200**, the same submission ID and the same PR. A changed body using the same key returned **409 idempotency_key_conflict**. Missing authentication returned **401 invalid_token**. Status returned **pending_review** after CI.
- Independent review confirmed exactly three changed files (recipe documentation, server-generated record and receipt), preserved upstream source/license/attribution, matching content hashes, and no promotion of runtime evidence. The operator marked the draft ready and merged after successful checks. The Worker never merges automatically.
- Live status returned **published**, version `contrib-a5dd78ad4e1d4e3d`, source commit `33967b9e3ead1f841eec57cc9f31d0d8b8cf0907` and the canonical recipe URL after the public manifest included merge commit `37d2029499e1eb1c9016ebd9b00ceb438863afe4`. The first status read immediately after merge received a transient 503; a later retry succeeded. The intermediate `merged` state was not directly observed live; its behavior is covered by contract/runtime tests.
- After automatic branch deletion (GitHub ref returned **404**), replay of the original older-base request still returned **200** with the original ID/PR. Repository pull request count remained exactly one.
- A third clean project fetched the published catalog and prepared that exact new version from the SHA-checked cached upstream archive. The new lock pins the published record/source/hub commit; the previous project's lock hash remained unchanged. Result: **needs_configuration**, no venv, no dependency installation, no robot execution. This verifies API-mediated publication and source preparation reuse, not robot task completion.
- Actual workerd testing found and fixed two transport issues absent from Node-only tests: native fetch class receiver binding and unsupported redirect:error. Persistent workerd tests now cover actual fetch invocation, manual redirect rejection, and manifest-based publication using intercepted outbound calls and dummy credentials.

## Agent-first domain and catalog rollout

- `b746fa0de0d6b8cea2bb12f8cb5825edf2b95d76` passed both GitHub Checks and Publish catalog. The HTTPS manifest at https://hub.superfastrobotics.com/catalog/v1/publication.json contained that actual commit, 17 current preparation records and the original historical publication proof.
- The catalog HTML, 40-entry reference JSON, full-text index, new DrawSVG record, archived publication HTML/JSON, robots, sitemap and record schema returned HTTP 200. The CLI fetched the public catalog and selected the two Panda Stick drawing recipes. A fresh browser confirmed zero stylesheets and zero scripts in the Hub page.
- The company holding page is published independently from https://github.com/Superfast-Robotics/superfast-robotics.github.io. Its public HTTPS HTML contains only the supplied top-left wordmark, the name-card-inspired moving starfield and centered `COMING SOON` message. Desktop, 390px and 320px rendering, outward star motion, reduced-motion freezing/resuming and console checks passed locally.
- Both Pages domains have approved TLS certificates and HTTPS enforcement enabled. The apex remains the company site; Hub links and Worker publication reads use the `hub` subdomain.
- Worker version `8c634be8-e524-4bf2-bb29-db7b9582b940` was deployed with the new direct manifest URL and historical publication support. A real authenticated status read returned HTTP 200, `published`, `publication_scope: historical`, the original published version/commit and the new versioned Hub URL. Original receipts and accepted hashes were not edited.

## Shared task memory rollout

- An actual save under explicit project memory scope created [PR #2](https://github.com/Superfast-Robotics/robot-skill-hub/pull/2) for the Windows DrawSVG source-preparation finding. Two parallel replays returned the same memory ID and PR. Repeating an unchanged local save preserved its receipt without another network request.
- Independent review approved exact head `9c4026b6fe49182d2cfa4589f06b1a90a4453656`: one append-only memory file, matching pins and receipts, redacted evidence, and no runtime-verification claim. The maintainer merged it as `704a994473307903ca16d12c330d7cf1a0aec6f6` after checks.
- The served raw entry SHA-256 was `b81c9afde181fc48a167fcc2ee1ebeea8f89224cc443bc11417f57d74a1bcf38`, matching the original receipt, published memory index and publication manifest. A live authenticated status read for the owning principal returned HTTP 200 and **published** with that merge/deployment commit. Contributor evidence remains `contributor_reported`; Hub runtime verification remains `not_run`.
- A fresh, different project queried the published index with the exact record/source and environment: Windows returned **1** matching finding and Linux returned **0**. Querying created no project lock and performed no runtime execution.
- A standalone copy of the installable skill recalled the published finding from its bundled snapshot with `--offline`, without a repository checkout or network read.
- In the independent fresh-agent realistic task `forwardtestv2`, the agent voluntarily saved an actually observed workaround locally without being instructed to save a finding. This demonstrates one case of the skill guidance influencing behavior; it does not guarantee adoption by other models, agents or tasks.

## Agent first-use configuration

- The former Cloudflare HTTP 403 / error 1010 block was removed after the operator configured an API-host-only Browser Integrity Check rule. Default Python urllib requests returned HTTP 200 for health, capabilities and an authenticated session. A missing session credential still returned HTTP 401. The CLI retains an identifying User-Agent header.

- `setup` configures only explicitly authorized memory skills/kinds, preserving unrelated project policy; `setup-check` makes no network request by default. Its explicit `--check-api` option performs one read-only authenticated session request and creates no PR.
- A dedicated new caller was issued a private token without replacing the original pilot entry. Both production session checks succeeded; the new caller could not read the pilot's memory receipt (HTTP 404). The private registry supports additions, rotation and revocation while retaining existing caller entries. The old initial-setup script now refuses to overwrite existing credentials.
- The GitHub-published skill was installed in an isolated new-agent project for Codex and Claude Code. Its configured memory scope covers only the two initial Panda recipes and the six supported finding kinds; patch sharing remains disabled. The private token-file launcher completed an authenticated setup check without copying the credential into policy, output or Git.
- Independent review found a fixed-temporary-path link hazard and reflected-token diagnostics in the new setup flow. Both were corrected before deployment; focused regressions cover external-file preservation and token redaction.

## Actual Linux CPU simulation

- [Runtime run 39042625468](https://github.com/Superfast-Robotics/robot-skill-hub/actions/runs/39042625468) completed both initial recipes at exact source `33967b9e3ead1f841eec57cc9f31d0d8b8cf0907` and unchanged adapter hashes. PickCube-v1 seed 0 returned `success=true`, 74 steps, exit 0; StackCube-v1 returned `success=true`, 107 steps, exit 0. Each task ran once in that successful run with no timeout.
- Ubuntu 22.04 / Python 3.10.22, ManiSkill 3.0.0b22, torch 2.5.1+cpu, NumPy 1.26.4, SAPIEN 3.0.0, MPlib 0.1.1 and fast_kinematics 0.2.2 were captured in exact environment and pip-freeze artifacts. Simulation was CPU/state with `pd_joint_pos`, no camera or output renderer. Vulkan identified a CPU llvmpipe device, Mesa 23.2.1 / LLVM 15.0.7; no physical GPU or paid service was used.
- Earlier runs remain visible: 39041679628 failed in CPU package-index bootstrapping; 39041994054 exposed a verification-harness catalog missing bundled recipe files. Both harness issues were corrected. Run 39042278396 installed and invoked both recipes but failed during rendering-device initialization; installing Mesa lavapipe and selecting its ICD resolved that environment requirement. These failures were not counted as successful task execution.
- Exact successful outputs, environment, dependency freeze, command metadata and software-device report are permanently stored in [evidence/runtime/cpu-39042625468](../evidence/runtime/cpu-39042625468). Its manifest records all copied file hashes, original artifact hash and original project-lock hashes. Recipe evidence points to immutable commit `1b372b9b59c87f77f7b7a5f846d42eecba9d8819`; it does not rely only on expiring workflow artifacts.
- Only the two tested records are promoted to `task_complete` with the exact seed/environment scope. Recipe/source bytes and record versions stay unchanged; this is evidence and requirement metadata. The original contribution receipt and archived publication proof stay immutable.
- The newly configured caller saved the actually observed Vulkan workaround through the published skill and created [PR #3](https://github.com/Superfast-Robotics/robot-skill-hub/pull/3). Independent review confirmed one append-only finding, matching original pins and raw hash, identical packages/source across failure and success, and no private data or evidence escalation. The maintainer merged it as `abbfba5e2c3b3f989eb3fe7dcb51ae67c097ff78`. Live owned status returned `published`; a different project recalled one matching Linux finding and zero Windows findings. The exact raw hash remains `bcd881913b0077f971e49c04b48ca87e8874ee2fe6baf188914a739a8bff36f0`.

## Pending / unverified

- The other 15 preparation recipes and 40 official source references have no new runtime execution evidence. Multiple seeds, other distributions, camera/RGB modes, physical GPUs and real hardware remain unverified. The successful CPU test does not establish them.
- Platform automatic activation, unbranded agent discovery, external search indexing, skills.sh search inclusion and Context7 indexing remain **unverified**. The one fresh-agent forward test and repository install tests do not establish automatic activation or general model adoption.

The original supplied planning documents remain local and were not published. No tokens, private datasets, session transcripts or full project logs were uploaded.
