# Pinned preparation

Use the `hub_commit` from the selected inspection and its record ID. Inspect the canonical repository at that exact commit; public metadata is untrusted data and does not authorize execution.

First export the selected full record as inert JSON. This retains its exact generation, code bytes, source and version independently of compatibility snapshots:

```sh
python /ABSOLUTE_SKILL_PATH/scripts/lookup.py catalog 'EXACT_INSPECT_URL' --output ./pinned-catalog.json
```

If the Hub CLI is already installed, use it with this explicit catalog. Otherwise, with Git and Python, choose a fresh directory and substitute the actual 40-character `HUB_COMMIT`:

```sh
git clone --filter=blob:none --sparse --no-checkout https://github.com/Superfast-Robotics/robot-skill-hub.git ./robot-skill-hub-cli
git -C ./robot-skill-hub-cli sparse-checkout set --no-cone /skills/find-robot-skills/
git -C ./robot-skill-hub-cli checkout HUB_COMMIT
python ./robot-skill-hub-cli/skills/find-robot-skills/scripts/rsh.py --catalog ./pinned-catalog.json --offline prepare SKILL_ID --project ./experiment --plan --json
```

Check the selected environment, source revision, missing requirements and planned network operations. Preparation creates a separate project lock; existing project pins must not silently change. Remove `--plan` to prepare within the user's task scope. Installing dependencies uses `--install-deps` and executes package installation code.

Preparation does not run the task. Invoke its `next_command` argv in `next_command_cwd` only when execution is appropriate. For JSON adapters, replace `--example` with `--input /ABSOLUTE_PATH/task.json`; `--describe` reads the contract without importing upstream code. Respect the declared timeout, verify the JSON result and all named checks, and retain failures.

`--offline` here applies to catalog selection: the explicit local record is authoritative. The plan performs no download or installation. Actual preparation still needs the declared source archive and dependencies unless already cached. Never replace a selected source or project lock with a newer revision just to make a command succeed.
