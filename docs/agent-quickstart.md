# Find and prepare robot manipulation code

Find reusable robot code for your current environment, with pinned sources and runnable examples.

Install `find-robot-skills` or use its directory in this repository. The folder includes the tool, catalog snapshot, adapter assets and contribution reference; a repository checkout is not required after installation.

Browse the public catalog at [hub.superfastrobotics.com](https://hub.superfastrobotics.com/). The examples below start with Panda; search also covers the cataloged Panda Stick, xArm6 Robotiq and SO100 recipes.

```sh
python /PATH_TO_SKILL/scripts/rsh.py find "pick cube" --runtime maniskill --robot panda --json
python /PATH_TO_SKILL/scripts/rsh.py inspect SKILL_ID --json
python /PATH_TO_SKILL/scripts/rsh.py prepare SKILL_ID --project ./experiment --json
```

Use the exact ID returned by `find`. Inspect the controller, state observation inputs, source commit, license, preparation plan, dependencies and evidence before preparing. Missing environment values stay unknown. Explicit incompatible environments produce no compatible candidates.

Preparation downloads an exact source archive, verifies its hash, creates an isolated project environment on supported systems, and records a lock. It does not run the simulator. Dependency installation is explicit because package installation can execute code. Follow the tool's returned command arrays; do not replace the project's Python environment or silently update an existing lock.

The preparation recipes target Linux x86_64/Python 3.10 and ManiSkill 3.0.0b22 state-based motion planners. Each record specifies its robot, controller and task. On Windows, search and inspect work; download-only preparation can preserve sources for a matching Linux environment. Records retain `not_run` until task execution is demonstrated. Source review, dependency installation, import success and task success are distinct evidence levels.

If a useful fix was already needed for the user's work, create a local bundle containing only that fix, exact base/source pins, environment and actual evidence. Public contribution requires both project sharing permission and a limited API token. Follow [contributing](./contributing.md) and the installed skill's reference. No sharing permission means no network submission. Submission never blocks finishing the original user task.
