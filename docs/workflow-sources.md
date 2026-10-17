# Official robot workflow source review

The original finite selection in [`catalog/workflow-projects.json`](../catalog/workflow-projects.json) added 56 operational Python entrypoints. The table and byte counts below preserve that historical selection. Every one has a guarded Python entrypoint and an exact source byte count and SHA-256 at a full Git commit. The importer parses source syntax; it does not import a robot library, run an upstream script, install dependencies, load a simulator, connect hardware or retrieve weights, datasets or meshes.

| Upstream | Frozen commit | Entries | Reviewed scope |
| --- | --- | ---: | --- |
| [OpenPI](https://github.com/Physical-Intelligence/openpi) | `215abfb217dbac7d5f1273282331b9b1866c0479` | 11 | Policy server, JAX/PyTorch training, normalization, ALOHA/DROID clients, LIBERO evaluation and demonstration conversion |
| [robomimic](https://github.com/ARISE-Initiative/robomimic) | `d309eaecc18acf4152a830a895a6984b8ac71b05` | 10 | Imitation training, checkpoint evaluation, trajectory playback, dataset inspection/conversion/splitting and two instructional training loops |
| [Unitree SDK2 Python](https://github.com/unitreerobotics/unitree_sdk2_python) | `814556d15970dd2ecf1c9984e845ca02ab07e206` | 18 | Model-specific locomotion, direct joint and arm control, Go2 obstacle avoidance and controller-input decoding |
| [LeRobot](https://github.com/huggingface/lerobot) | `7e241bd630a3719a56157a497ce5d08f244784f1` | 9 | Training, evaluation, real-robot rollout, recording/replay, teleoperation, calibration, motor setup and joint-limit collection CLIs |
| [Isaac Lab](https://github.com/isaac-sim/IsaacLab) | `37ddf626871758333d6ed89cf64ad702aef127d0` | 8 | Train/play pairs for RL-Games, RSL-RL, Stable Baselines3 and skrl |

LeRobot and Isaac Lab use the existing example registry's exact project revisions while selecting previously unindexed workflow scripts. OpenPI's `examples/simple_client/main.py` remains owned by the existing intake submission and is excluded from this selection. Helpers, tests, configuration expansion and download-only scripts were not selected. These counts describe reviewed files, not distinct learned behaviors, measured skill usage, supported robots or exhaustive upstream coverage.

The 56 source files contain 515,680 bytes. Applicable repository license documents contain 43,261 bytes across the five projects; their exact pins and source-only scopes are in the manifest. OpenPI and LeRobot selected sources use Apache-2.0, robomimic uses MIT, and Unitree SDK2 Python and Isaac Lab use BSD-3-Clause. The selected files' explicit license notices were checked against those identities. This review does not extend those licenses to checkpoints, third-party code, datasets, firmware, simulator components or assets.

Nineteen pinned author/setup document references contain 145,290 bytes, including package declarations, installation instructions and attribution. Project authors are recorded from those documents. Source-path labels identify ALOHA/DROID arms and the selected Unitree robot families where the source states that scope. Generic trainers, dataset tools and configurable workflows retain `source-defined` robot labels. A configured task, driver or checkpoint still needs its own compatibility review.

[`tools/import_robot_workflows.py`](../tools/import_robot_workflows.py) rebuilds these references from the frozen manifest and a populated local text cache:

```powershell
python tools/import_robot_workflows.py --check
```

An empty cache can be populated by explicitly fetching only the manifest's frozen text pins:

```powershell
python tools/import_robot_workflows.py --fetch --check
```

Neither command discovers new files or updates commits. Missing source bytes, changed hashes/sizes, changed license identifiers, missing attribution/setup anchors and duplicate immutable source ownership fail validation. Existing records owned by other registries are retained unchanged. All generated workflow records remain `source_reviewed`, `runtime_verification: not_run`, `access.mode: source_reference` and `hub_prepare: false`.

## Later robot-agent and policy sources

A later finite selection adds **47 workflow source references** alongside the original 56:

- **33 GR00T/RAI sources** cover policy training, serving/evaluation, robot clients and robot-agent workflows. See the [robot-agent/policy review](robot-agent-policy-sources.md) and [source receipt](../evidence/sources/robot-agent-policy-workflows-2026-10-18.json). NoMaD retains unresolved Apache/MIT source-notice scope as `NOASSERTION`, `verified: false`.
- **14 OpenVLA, Diffusion Policy, ACT and Octo sources** have a separate [canonical policy source review](canonical-policy-sources.md) and [receipt](../evidence/sources/canonical-policy-upstreams-2026-10-18.json).

These additions preserve their separate source/license/setup pins and per-workflow requirements. The importer checks a pinned literal console registration for NoMaD; all remaining additions have guarded Python entrypoints. Reviewed robot names remain discovery declarations, with no inferred compatibility combinations. None of the additions increases runtime verification or supplies a Hub adapter.

## xArm SDK top-level scripts

Twelve additional [xArm Python SDK](https://github.com/xArm-Developer/xArm-Python-SDK/tree/d911319cebc45142613e18086aabb8067b18ab7f) examples cover Cartesian and joint commands, velocity control, servo targets, grippers, GPIO, property access and trajectory recording. The [source receipt](../evidence/sources/xarm-sdk-2026-10-18.json) pins 22 text files totaling 374,094 bytes, including 24,212 bytes in the twelve examples. All 1,236 previously published official reference objects were preserved exactly.

These are unguarded scripts: importing them can connect and initialize control state. Property/getter examples also issue initialization commands. The importer now accepts the explicit `python_top_level_script` form, checking a reviewed literal SDK import, direct constructor binding and subsequent instance method calls in module/control-flow syntax. It excludes deferred function, class, lambda and comprehension bodies. This establishes syntactic presence only; execution, reachability and compatibility remain unverified. No upstream code was imported, installed or run during this review.

Only the three named source paths receive `xarm5`, `xarm6` and `xarm7` discovery labels; nine common examples retain unknown model scope. None of the twelve is an IK entrypoint. Source terms are BSD-3-Clause; SDK version 1.18.5, Python declarations and firmware-specific trajectory requirements remain separate upstream declarations. All records retain `source_reference`, `hub_prepare: false` and `runtime_verification: not_run`. Fetching their verified inert bytes uses `fetch-source`; it does not prepare or execute hardware control.
