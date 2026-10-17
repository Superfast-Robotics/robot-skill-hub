<picture>
  <source media="(prefers-color-scheme: dark)" srcset="web/brand/wordmark-dark.png">
  <img src="web/brand/wordmark-light.png" alt="Superfast Robotics" width="260">
</picture>

# Robot Skill Hub

**Reusable robot code, with the context to use it.** Find skills for your environment, inspect pinned sources and evidence, and prepare a reproducible starting point for your next experiment.

[**Catalog: hub.superfastrobotics.com →**](https://hub.superfastrobotics.com/) · [API: api.superfastrobotics.com](https://api.superfastrobotics.com/healthz)

## Use with your agent

Install the self-contained discovery skill for your agent:

```sh
# Codex
npx skills add Superfast-Robotics/robot-skill-hub --skill find-robot-skills -a codex

# Claude Code
npx skills add Superfast-Robotics/robot-skill-hub --skill find-robot-skills -a claude-code
```

Or use the tool directly from this checkout with Python 3.10+:

```sh
python skills/find-robot-skills/scripts/rsh.py find "pick cube" --runtime maniskill --robot panda --json
python skills/find-robot-skills/scripts/rsh.py inspect maniskill-panda-pick-cube --json
python skills/find-robot-skills/scripts/rsh.py prepare maniskill-panda-pick-cube --project ./experiment --download-only --plan --json
```

Use the exact ID returned by `find`. The last command previews source-only preparation without writing files, installing dependencies or running a simulator. Follow the [quickstart](docs/agent-quickstart.md) to prepare the source in a project.

| Find | Inspect | Prepare |
| :--- | :--- | :--- |
| Search by task, runtime and robot. | Check source pins, requirements, licenses and evidence. | Download verified sources and preserve a project lock. |

## Choose a ManiSkill recipe

Browse official ManiSkill motion planning recipes for **Panda**, **Panda Stick**, **xArm6 Robotiq** and **SO100**. Start with Panda **PickCube-v1** or **StackCube-v1**, then search the catalog for your task and exact robot variant.

The preparation target is Linux x86_64, Python 3.10 and ManiSkill 3.0.0b22 with state observations and CPU simulation. Each recipe specifies its robot and controller. Windows supports catalog search, inspection and source-only preparation.

Every record pins its source and recipe version. Preparation and task execution are separate steps; see [compatibility](docs/compatibility.md) for requirements and [execution evidence](docs/verification.md) for the current results.

For other runtimes, browse the [official source examples](https://hub.superfastrobotics.com/catalog/v1/references.json) and [source selection notes](docs/sample-sources.md). These references point to pinned upstream code; they are separate from the preparation recipes.

## Useful fixes, reviewed before publication

An authorized agent first keeps its useful fix locally. With explicit project sharing permission and a limited submission token, it can submit a minimal patch through the API. The Worker creates one internal draft PR in this repository. A maintainer reviews and merges it; the deployed catalog manifest confirms publication.

**Local fix → permitted submission → internal PR → review → published catalog**

[Contribution policy](docs/contributing.md) · [API operation](api/README.md) · [Deployment runbook](docs/deployment.md)

Submission and status endpoint: [`api.superfastrobotics.com`](https://api.superfastrobotics.com/healthz).

## Develop and validate

```sh
python tools/build_catalog.py --base-url https://hub.superfastrobotics.com
python -m unittest discover -s tests/python -v
python tools/test_catalog.py -v
npm --prefix api ci
npm --prefix api run check
npm --prefix api test
```

GitHub hosts source, catalog records and internal PRs. GitHub Pages serves the public catalog. Cloudflare Workers handles authenticated submissions and status queries. Robot code runs in your own environment.

---

[Superfast Robotics](https://superfastrobotics.com/) · Building toward a **Super Fast Robot Agent OS**.

Hub code is [MIT licensed](LICENSE). Upstream ManiSkill is Apache-2.0; its authorship and license references remain in every record and recipe.
