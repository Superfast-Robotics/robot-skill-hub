# Robot Skill Hub

Find reusable robot code for your current environment, with pinned sources and runnable examples.

Public catalog: **https://superfast-robotics.github.io/robot-skill-hub/**  
Submission API: **https://api.superfastrobotics.com** (also `https://robot-skill-hub-api.superfast-robotics.workers.dev`)

This preview starts with official ManiSkill Panda **PickCube-v1** and **StackCube-v1** motion planning recipes. The intended simulation environment is Linux x86_64, Python 3.10, ManiSkill 3.0.0b22, state observations and CPU simulation. Sources and recipe versions are pinned. Simulator execution is **not_run / 미검증** until a matching machine actually completes the task. Windows supports catalog search and source preparation; it is not a supported simulator target.

```powershell
python skills/find-robot-skills/scripts/rsh.py find "pick cube" --runtime maniskill --robot panda --json
python skills/find-robot-skills/scripts/rsh.py inspect maniskill-panda-pick-cube --json
```

Use the IDs returned by `find`. Read [agent quickstart](docs/agent-quickstart.md) for preparation and [compatibility](docs/compatibility.md) for the exact limits.

Install just the self-contained discovery skill:

```sh
npx skills add Superfast-Robotics/robot-skill-hub --skill find-robot-skills -a codex
npx skills add Superfast-Robotics/robot-skill-hub --skill find-robot-skills -a claude-code
```

Repository discovery, CLI installation, automatic agent selection, search engine indexing and simulator completion are separate checks; none is implied by publishing this repository.

Agents preserve useful fixes locally first. When the project explicitly permits public contribution, a limited submission token can submit a minimal patch to the Worker. The Worker opens one internal draft PR. A maintainer reviews and merges it; publication is confirmed from the deployed catalog manifest. Read [contribution policy](docs/contributing.md), [API operation](api/README.md) and [deployment runbook](docs/deployment.md).

Local validation:

```sh
python tools/build_catalog.py --hub-commit HEAD --base-url https://superfast-robotics.github.io/robot-skill-hub
python -m unittest discover -s tests/python -v
python tools/test_catalog.py -v
npm --prefix api ci
npm --prefix api run check
npm --prefix api test
```

GitHub hosts the source, catalog records and internal PRs; GitHub Pages serves public static files; Cloudflare Workers handles authenticated submission and status only. There is no hosted simulator, model service, database, user account UI or payment flow. Deployment does not upgrade any plan.

Hub code is MIT licensed. Upstream ManiSkill is Apache-2.0 and retains its authorship and license references in every record and recipe.
