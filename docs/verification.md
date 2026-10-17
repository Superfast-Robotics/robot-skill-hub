# Verification record — 2026-10-17 (Asia/Seoul)

## Confirmed locally

- Python CLI and adapter tests: **22 passed**.
- Catalog integrity/publication tests: **6 passed**.
- Worker contract tests: **16 passed**; TypeScript check passed.
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
- Live health reported `submission_configured:false`. Live POST and status requests returned 503 / `service_not_configured`, preserving a clear distinction between deployed and operational submission service.
- `skills` CLI **1.7.2** installed the published GitHub skill into an isolated project for both Codex and Claude Code. The installed copies successfully ran find/inspect independently of the repository tree. No global agent installation was changed.

## Pending / unverified

- Repository-scoped Worker GitHub credential and pilot credential must be configured. Consequently **live API submission, internal PR creation, real PR merge→publication status and API-mediated corrected-version reuse are unverified**. See [deployment instructions](deployment.md) for exact permissions and input locations.
- The catalog's apex custom domain `superfastrobotics.com` needs its DNS record. The API subdomain is already connected. Until then, the catalog uses GitHub Pages' default project URL.
- ManiSkill dependency installation, successful ManiSkill import and PickCube/StackCube task completion on Linux are **not_run / 미검증**. This Windows host is not a supported simulator environment; Docker's engine was unavailable and no general WSL Linux distribution was installed. No GPU or paid execution service was provisioned.
- Unbranded agent discovery, automatic skill selection by a fresh agent, external search indexing, skills.sh search inclusion and Context7 indexing are **unverified**. A repository install test does not establish them.

The original supplied planning documents remain local and were not published. No tokens, private datasets, session transcripts or full project logs were uploaded.
