---
name: find-robot-skills
description: Find and prepare reusable robotics manipulation Python code for ManiSkill Panda simulation projects. Use for requests for existing grasping, pick-and-place or stacking implementations. Check exact runtime, robot, controller and observations before recommending a recipe. Excludes generic software skills and real-hardware execution.
---

Find reusable robot code for the current environment, with pinned sources and runnable examples.

Locate `scripts/rsh.py` relative to this installed skill. It uses Python 3.10+ and the bundled catalog; the repository root is unnecessary. Replace `/ABSOLUTE_SKILL_PATH` below with this skill's actual location. JSON mode never prompts; stdout contains one JSON object and progress goes to stderr.

1. Read the project's runtime/version, robot, controller and observation settings when available. Preserve unknown values. The first recipes target Linux x86_64, Python 3.10, ManiSkill 3.0.0b22, Panda, `pd_joint_pos`, privileged simulator state and the CPU backend. Source review is recorded; robot execution is **미검증 / not run** unless the record says otherwise.
2. Find up to three candidates, then inspect the useful one:

   ```sh
   python /ABSOLUTE_SKILL_PATH/scripts/rsh.py find "pick object" --runtime maniskill --runtime-version 3.0.0b22 --robot panda --controller pd_joint_pos --observation state --os linux --json
   python /ABSOLUTE_SKILL_PATH/scripts/rsh.py inspect maniskill-panda-pick-cube --json
   ```

   Explicit mismatches return no candidates. Missing environment fields produce `compatibility_status: unknown`; they do not prove compatibility. Check original authors, Apache-2.0 source license, exact commit, requirements, inputs and actual verification level. State-based planning is not equivalent to an RGB-only policy.
3. Review the preparation plan before downloads or installation. `prepare` downloads the reviewed archive, checks SHA-256 and paths, saves a project lock, and creates a separate Python environment. It never runs the robot task. Dependency installation can execute package build hooks and requires the explicit `--install-deps` option within the user's existing authorization.

   ```sh
   python /ABSOLUTE_SKILL_PATH/scripts/rsh.py prepare maniskill-panda-pick-cube --project ./experiment --plan --json
   python /ABSOLUTE_SKILL_PATH/scripts/rsh.py prepare maniskill-panda-pick-cube --project ./experiment --json
   python /ABSOLUTE_SKILL_PATH/scripts/rsh.py prepare maniskill-panda-pick-cube --project ./experiment --install-deps --json
   ```

   `--download-only` preserves verified source and recipe files on an unsupported host without creating an environment or claiming execution support. Download size is approximately 233 MiB per upstream archive. Inspect `next_command` (an argument array), `next_command_cwd`, `missing_requirements` and `reason_code`. Run the next command separately only when authorized, with the recipe timeout. Treat actual task output as evidence; preparation readiness is not task success.
4. An installed snapshot stays pinned. For an explicitly requested catalog refresh, pass `--catalog https://superfastrobotics.com/catalog/v1/index.json` to find/inspect/prepare. Existing project locks are never silently updated; choose a new project when evaluating a newer version.
5. Finish the user's task first. If that work already produced a useful reusable fix, preserve a minimal local patch, environment and true verification scope. Read [contributions.md](references/contributions.md) for `bundle`, `submit` and `submission-status`. Public sharing policy and a scoped API token are separate requirements. With no sharing permission or token, keep the draft locally and continue the user's task. Submission creates a public internal draft PR; only `published` means the new version is in the public catalog.

Do not invent robot execution results, broaden supported environments, collect session logs or research datasets, submit unrelated refactors, or send PRs to external upstream repositories through this API.
