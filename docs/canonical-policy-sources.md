# Canonical upstream policy workflow sources

This review covers 14 Python workflow entrypoints from the original OpenVLA,
Diffusion Policy, ACT and Octo repositories. It adds pinned upstream provenance
alongside existing ACT/diffusion implementations in LeRobot and robomimic. The
counts describe source files, not distinct robot behaviors or successful runs.
This is a finite selection, not an exhaustive inventory of these projects.

Every selected source remains `access.mode: source_reference`,
`hub_prepare: false` and `runtime_verification: not_run`. These records provide
source and setup links; they do not install a policy, prepare a Hub adapter,
authorize robot movement or establish a compatible environment.

| Upstream | Frozen commit | Files | Reviewed workflows |
| --- | --- | ---: | --- |
| [OpenVLA](https://github.com/openvla/openvla) | `c8f03f48af692657d3060c19588038c7220e9af9` | 5 | REST policy serving, LoRA fine-tuning, FSDP training, LIBERO evaluation and Bridge V2 WidowX evaluation |
| [Diffusion Policy](https://github.com/real-stanford/diffusion_policy) | `5ba07ac6661db573af695b419a7947ecb704690f` | 3 | Training launcher, checkpoint simulation evaluation and UR5 real-robot evaluation |
| [ACT](https://github.com/tonyzhaozh/act) | `742c753c0d4a5d87076c8f69e5628c79a8cc5488` | 1 | One training/evaluation entrypoint; `--eval` is a mode of the same file |
| [Octo](https://github.com/octo-models/octo) | `241fb3514b7c40957a86d869fecb7c7fc353f540` | 5 | Pretraining, configurable fine-tuning, ALOHA observation/action adaptation, simulation rollout and real WidowX evaluation |

The [evidence receipt](../evidence/sources/canonical-policy-upstreams-2026-10-18.json)
contains every full source URL, SHA-256, byte count and Git blob identity, together
with pinned license and author/setup documents. Its project hashes cover the
reviewed objects embedded in that receipt, so later additions to the combined
workflow manifest do not invalidate this review.

## Selected source files

| Upstream | Pinned Python source | Bytes |
| --- | --- | ---: |
| OpenVLA | [`vla-scripts/deploy.py`](https://github.com/openvla/openvla/blob/c8f03f48af692657d3060c19588038c7220e9af9/vla-scripts/deploy.py) | 5,554 |
| OpenVLA | [`vla-scripts/finetune.py`](https://github.com/openvla/openvla/blob/c8f03f48af692657d3060c19588038c7220e9af9/vla-scripts/finetune.py) | 17,834 |
| OpenVLA | [`vla-scripts/train.py`](https://github.com/openvla/openvla/blob/c8f03f48af692657d3060c19588038c7220e9af9/vla-scripts/train.py) | 12,141 |
| OpenVLA | [`experiments/robot/libero/run_libero_eval.py`](https://github.com/openvla/openvla/blob/c8f03f48af692657d3060c19588038c7220e9af9/experiments/robot/libero/run_libero_eval.py) | 11,936 |
| OpenVLA | [`experiments/robot/bridge/run_bridgev2_eval.py`](https://github.com/openvla/openvla/blob/c8f03f48af692657d3060c19588038c7220e9af9/experiments/robot/bridge/run_bridgev2_eval.py) | 6,985 |
| Diffusion Policy | [`train.py`](https://github.com/real-stanford/diffusion_policy/blob/5ba07ac6661db573af695b419a7947ecb704690f/train.py) | 965 |
| Diffusion Policy | [`eval.py`](https://github.com/real-stanford/diffusion_policy/blob/5ba07ac6661db573af695b419a7947ecb704690f/eval.py) | 1,996 |
| Diffusion Policy | [`eval_real_robot.py`](https://github.com/real-stanford/diffusion_policy/blob/5ba07ac6661db573af695b419a7947ecb704690f/eval_real_robot.py) | 18,383 |
| ACT | [`imitate_episodes.py`](https://github.com/tonyzhaozh/act/blob/742c753c0d4a5d87076c8f69e5628c79a8cc5488/imitate_episodes.py) | 17,242 |
| Octo | [`scripts/train.py`](https://github.com/octo-models/octo/blob/241fb3514b7c40957a86d869fecb7c7fc353f540/scripts/train.py) | 12,303 |
| Octo | [`scripts/finetune.py`](https://github.com/octo-models/octo/blob/241fb3514b7c40957a86d869fecb7c7fc353f540/scripts/finetune.py) | 12,544 |
| Octo | [`examples/02_finetune_new_observation_action.py`](https://github.com/octo-models/octo/blob/241fb3514b7c40957a86d869fecb7c7fc353f540/examples/02_finetune_new_observation_action.py) | 7,391 |
| Octo | [`examples/03_eval_finetuned.py`](https://github.com/octo-models/octo/blob/241fb3514b7c40957a86d869fecb7c7fc353f540/examples/03_eval_finetuned.py) | 4,177 |
| Octo | [`examples/04_eval_finetuned_on_robot.py`](https://github.com/octo-models/octo/blob/241fb3514b7c40957a86d869fecb7c7fc353f540/examples/04_eval_finetuned_on_robot.py) | 8,255 |

The files contain 137,706 bytes. Each has a guarded Python entrypoint and an
operational call. Diffusion Policy's documented training launcher invokes
`workspace.run()`; configuration variants are not expanded into extra records.
Helpers, tests, notebooks, model definitions, download-only scripts, checkpoint
converters and data-loader-only examples were excluded.

## Declared setup and external requirements

OpenVLA's package metadata declares Python >=3.8, its installation guide uses
3.10, and its LIBERO reproduction section specifically reports 3.10.13.
Fine-tuning and FSDP training use CUDA; upstream GPU-memory examples depend on
batch size and training mode. The REST server selects CUDA or CPU but requests
Flash Attention and bfloat16, so its fallback branch is not CPU validation.
Several model loads use `trust_remote_code=True`. Full training explicitly reads
an HF token and defaults to W&B tracking; LIBERO W&B logging is optional and off
by default. These declarations and checkpoint/data requirements are preserved
per workflow. See the pinned [OpenVLA setup](https://github.com/openvla/openvla/blob/c8f03f48af692657d3060c19588038c7220e9af9/README.md).

Diffusion Policy declares Python 3.9 in its simulation and real-robot Conda
environments. Its benchmark setup specifies Linux and an NVIDIA GPU; the macOS
environment is described as development-only. Training instructions use
`wandb login`, while the selected checkpoint evaluator uses W&B video types
without initializing online logging. The real evaluator uses CUDA and the
specific UR5/UR5e, RTDE, RealSense and SpaceMouse setup. Checkpoints are loaded
with PyTorch/dill and supply configuration; none was loaded during review.
See the pinned [Diffusion Policy setup](https://github.com/real-stanford/diffusion_policy/blob/5ba07ac6661db573af695b419a7947ecb704690f/README.md).

ACT has conflicting setup declarations: its [README](https://github.com/tonyzhaozh/act/blob/742c753c0d4a5d87076c8f69e5628c79a8cc5488/README.md)
creates Python 3.8.10, while [conda_env.yaml](https://github.com/tonyzhaozh/act/blob/742c753c0d4a5d87076c8f69e5628c79a8cc5488/conda_env.yaml)
pins Python 3.9 and different MuJoCo/dm_control versions. Both declarations are
retained. Training and evaluation call CUDA directly; evaluation requires the
matching local policy checkpoint and dataset statistics. Real mode additionally
requires the separate ALOHA installation and hardware setup.

Octo's [README](https://github.com/octo-models/octo/blob/241fb3514b7c40957a86d869fecb7c7fc353f540/README.md)
uses Python 3.10. Its `pyproject.toml` provides a formatter target, not a declared
packaging/runtime minimum. Upstream GPU and TPU installation paths and its
reported TPU pretraining setup are declarations, not universal hardware minima
or CPU verification. Fine-tuning and rollout examples require matching external
checkpoints, data or robot-controller setup. W&B behavior differs by script; the
minimal ALOHA fine-tuning and simulation examples initialize it, while the real
WidowX example uses a separate controller service. The simulation rollout also
contains a local ACT-path placeholder that needs manual setup.

## Code, model and dataset licenses

The selected first-party workflow code is covered by the pinned root MIT
declarations: [OpenVLA](https://github.com/openvla/openvla/blob/c8f03f48af692657d3060c19588038c7220e9af9/LICENSE),
[Diffusion Policy](https://github.com/real-stanford/diffusion_policy/blob/5ba07ac6661db573af695b419a7947ecb704690f/LICENSE),
[ACT](https://github.com/tonyzhaozh/act/blob/742c753c0d4a5d87076c8f69e5628c79a8cc5488/LICENSE)
and [Octo](https://github.com/octo-models/octo/blob/241fb3514b7c40957a86d869fecb7c7fc353f540/LICENSE).
Those four license documents contain 4,371 bytes. The 17 supporting documents
contain 101,906 bytes and include author/setup evidence and ACT's separately
pinned [DETR Apache-2.0 license](https://github.com/tonyzhaozh/act/blob/742c753c0d4a5d87076c8f69e5628c79a8cc5488/detr/LICENSE).

OpenVLA explicitly states that its released pretrained models derive from
Llama-2 and are subject to the Llama Community License. Repository MIT is not a
model-weight grant. This review did not inspect checkpoint/model cards or
individual dataset licenses for any project. Separately hosted weights,
BridgeData, LIBERO, Open X-Embodiment, simulation demonstrations, dependencies,
robot firmware and services retain their separate terms and access conditions.

## Static review and discovery limits

The review used public repository metadata and complete Git trees at exact
commits, then checked selected source, license and setup bytes against those
trees. Each text read was bounded to 256 KiB; the largest was 38,458 bytes.
Python was parsed as data. No upstream module or setup code was imported or
executed, and no model, dataset, mesh, simulator or robot was loaded or contacted.
Preparing this guide and receipt required no new external fetches.

Six workflows have literal, pinned robot-name evidence: the OpenVLA Bridge and
Octo real evaluators name WidowX; Diffusion Policy's real setup names UR5/UR5e;
ACT's real mode names ALOHA; and two Octo examples specifically name ALOHA
simulation data/environment. The other eight remain source-configured. These
labels do not create compatible environment combinations or adapter support.

Offline checks verified all 35 cached text files, constructed 14 source-only
records, preserved every per-workflow declaration, and produced an identical
second build with a valid source index. They also rejected UR5 inferred merely
from `UR5e`, changed evidence hashes and path evidence bound to a different file.
The receipt records those checks without asserting installation, performance,
publication, independent use or exhaustive robot support. The broader source
registry is described in [workflow-sources.md](workflow-sources.md).
