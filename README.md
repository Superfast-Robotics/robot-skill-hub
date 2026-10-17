# Robot Skill Hub

Agent-readable robotics code discovery and task memory. The public Hub serves unstyled HTML, JSON and Markdown; GitHub stores pinned source records, internal PRs and reviewed findings.

- Agent contract: https://hub.superfastrobotics.com/agent.json
- Catalog: https://hub.superfastrobotics.com/catalog/v1/index.json
- Official source references: https://hub.superfastrobotics.com/catalog/v1/references.json
- Published task findings: https://hub.superfastrobotics.com/catalog/v1/memories.json
- Publication proof: https://hub.superfastrobotics.com/catalog/v1/publication.json
- API: https://api.superfastrobotics.com
- [Actual verification](docs/verification.md)

## Use the CLI

```sh
npx skills add Superfast-Robotics/robot-skill-hub --skill find-robot-skills

python /PATH_TO_SKILL/scripts/rsh.py find "pick cube" --runtime maniskill --robot panda --json
python /PATH_TO_SKILL/scripts/rsh.py inspect SKILL_ID --json
python /PATH_TO_SKILL/scripts/rsh.py memories SKILL_ID --project ./experiment --json
python /PATH_TO_SKILL/scripts/rsh.py prepare SKILL_ID --project ./experiment --plan --json
```

Discovery uses the latest available index with a local cache and bundled offline fallback. Use `--offline` for offline discovery, `--refresh` to refresh, or `--catalog FILE_OR_URL` to select a catalog explicitly. Results distinguish Hub preparation recipes from upstream source examples. Source examples have no Hub runtime adapter.

Inspect pins, license, environment and evidence before preparing. Preparation does not execute the robot task. Existing project locks stay fixed even when discovery indexes change. See the [agent quickstart](docs/agent-quickstart.md) and [compatibility contract](docs/compatibility.md).

Hub recipe version `1.1.0` uses an explicit 1000-step motion-planning budget and rejects truncated outcomes. Panda PickCube and StackCube completed seed 0 under that contract in a new CPU/state run; the other 15 recipes remain runtime-unverified. This does not establish completion within the upstream 50-step benchmark horizon. See the [verification record](docs/verification.md#bounded-hub-recipe-110-execution) for exact evidence and historical corrections.

## Remember findings from the actual task

Preserve a useful fact already observed during the user's work, using its exact recipe/source version, environment and minimal evidence:

```sh
python /PATH_TO_SKILL/scripts/rsh.py save SKILL_ID --project ./experiment --finding ./finding.json --json
```

The CLI writes a local outbox entry first. It makes one public API submission only when the project's separate memory policy already permits the skill and finding kind and a scoped token is available. Authorized scope does not need another prompt for each finding; missing scope leaves the entry local without interrupting the task. Existing patch permission does not grant memory sharing permission.

The Worker creates an internal draft PR. Maintainer review, merge and catalog publication remain separate from storage. Published findings are contributor-reported data, not executable agent instructions. Do not run extra experiments merely to create findings or let feedback delivery block the original task.

[Memory format and policy](docs/memory.md) · [Patch contributions](docs/contributing.md) · [API operations](api/README.md)

## Develop and validate

```sh
python tools/build_catalog.py --base-url https://hub.superfastrobotics.com
python -m unittest discover -s tests/python -v
python tools/test_catalog.py -v
npm --prefix api ci
npm --prefix api run check
npm --prefix api test
```

GitHub Pages serves the Hub. Cloudflare Workers handles authenticated saves, patch submissions and owner-scoped status reads. Robot code runs in the caller's environment. See the [deployment runbook](docs/deployment.md).

Hub code is [MIT licensed](LICENSE). Each source record preserves its own upstream license and attribution. The [company website](https://superfastrobotics.com/) is hosted independently.
