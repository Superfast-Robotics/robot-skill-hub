# Robot-agent and policy workflow source review

This finite selection adds **33 source entrypoints**: 12 from NVIDIA Isaac GR00T and 21 from RobotecAI RAI. It covers policy training/serving/evaluation, named robot clients, agent workflows, perception and speech services, mapping and data preparation. Counts describe reviewed source files, not learned behaviors, installed capabilities or measured robot success.

| Upstream | Exact commit | Sources | Source bytes |
| --- | --- | ---: | ---: |
| [NVIDIA Isaac GR00T](https://github.com/NVIDIA/Isaac-GR00T/tree/dac54b313160c201c450f97df0fd74ebd379c892) | `dac54b313160c201c450f97df0fd74ebd379c892` | 12 | 200,867 |
| [RobotecAI RAI](https://github.com/RobotecAI/rai/tree/b018729833742c6f71e1e9f332ee2b435676fb4f) | `b018729833742c6f71e1e9f332ee2b435676fb4f` | 21 | 116,685 |

The [sanitized source receipt](../evidence/sources/robot-agent-policy-workflows-2026-10-18.json) lists every exact source URL, SHA-256, byte count, author attribution, applicable license scope and declared requirements. It binds this 33-file source pin set independently of later changes to the shared [workflow manifest](../catalog/workflow-projects.json). The review inspected 93 bounded text files totaling 1,700,546 bytes: 317,552 selected-source bytes and 1,382,994 bytes of supporting license, attribution, setup and inspection text. All match the frozen Git trees and byte hashes. No helpers or test fixtures are counted as distinct skills.

## GR00T scope and requirements

The twelve GR00T sources include two training/fine-tuning launchers, a policy server, open-loop and simulation evaluation, standalone inference and benchmarking, a TensorRT deployment pipeline, three robot clients, and LeRobot dataset conversion. The server also has a dataset-replay alternative; its existence does not establish learned-policy inference.

Each selected source explicitly declares Apache-2.0 and NVIDIA copyright. The [pinned license section](https://github.com/NVIDIA/Isaac-GR00T/blob/dac54b313160c201c450f97df0fd74ebd379c892/README.md#license) distinguishes code under Apache-2.0 from model weights under the NVIDIA Open Model License. This source review does not resolve checkpoint terms or access, despite broader Apache wording elsewhere in that README. Third-party notices and the DROID source's OpenPI adaptation notice remain applicable.

The [hardware guide](https://github.com/NVIDIA/Isaac-GR00T/blob/dac54b313160c201c450f97df0fd74ebd379c892/getting_started/hardware_recommendation.md) declares inference starting at a 16 GB+ VRAM GPU and fine-tuning at a 40 GB+ VRAM GPU, with configuration-dependent increases. These are upstream declarations; no capacity, throughput or operating configuration was verified. Model-server robot clients delegate model compute rather than establishing a local GPU requirement.

The root package declares Python `>=3.12,<3.13`. The dedicated conversion package declares `>=3.10,<3.12` and uses a separate environment. SO100 and reBot client packages declare `>=3.10`, while their setup also installs root code; a compatible combined environment was not resolved. These differences remain per-workflow requirements. The conversion CLI can retrieve datasets and overwrite their local representation when run upstream; this review obtained no dataset.

## RAI scope and limits

The RAI selection contains seven robot-agent examples, three agent evaluations, two speech examples, a conversation example, NoMaD navigation inference, perception services, semantic mapping/navigation collection, embodiment preparation/serving, document retrieval and a data-preparation CLI. Mock tasks, helper classes, deprecated forwarding launchers and duplicate benchmark orchestration are excluded from the count.

The selected first-party source declares Apache-2.0. [NoMaD's source](https://github.com/RobotecAI/rai/blob/b018729833742c6f71e1e9f332ee2b435676fb4f/src/rai_extensions/rai_nomad/rai_nomad/nomad.py) also includes an MIT notice for incorporated visualnav-transformer/fork code and names its original authors. Exact incorporated-code boundaries and notice completeness were not cleared. This record therefore retains **`NOASSERTION`, `verified: false`**, with both pinned declaration scopes preserved. The root/package Apache declaration does not erase that notice or establish model-weight terms.

NoMaD is a console entrypoint backed by the literal `nomad = rai_nomad.nomad:main` registration in [pinned setup metadata](https://github.com/RobotecAI/rai/blob/b018729833742c6f71e1e9f332ee2b435676fb4f/src/rai_extensions/rai_nomad/setup.py). It is not mislabeled as a main-guard script. Registration was checked as syntax only; setup and source were never executed. Missing checkpoints can trigger a download upstream, and the node can publish velocity commands after its start service is called. Neither occurred during review.

The [data module README](https://github.com/RobotecAI/rai/blob/b018729833742c6f71e1e9f332ee2b435676fb4f/src/rai_finetune/README.md) describes trainers, mergers and exporters as future additions. Only its current dataset-preparation CLI is included. Its advertised LangSmith extraction branch imports a module absent from this exact tree and is not represented as working. Langfuse access and caller-provided observation formatting have separate requirements.

Root/core-related packages declare Python `>=3.10,<3.13`; standalone data preparation declares `>=3.10,<3.12`. Perception README prose says Python 3.8+, while its stricter package declaration says `>=3.10,<3.13`; no dependency environment was resolved. The TTS example initializes Kokoro before checking its OpenTTS alternative, so that choice does not establish avoidance of Kokoro assets or initialization.

Hosted LLM choices need their own access and credentials; local models, perception and speech choices require separate assets, servers and hardware. Missing-weight retrieval, optional provider use and GPU/CPU choices are source declarations, not tested capabilities. No paid provider call or model generation was performed. The semantic observation collector sends Nav2 goals when used upstream and is not merely a passive dataset reader.

## Evidence boundary

Thirty-two selected files have main guards; NoMaD has its separately checked console registration. Python AST parsing, license/notice inspection and byte verification do not execute code. Upstream prompts, instruction text and setup commands were treated as inert source data.

Seven records carry narrow, checksum-backed discovery names: the three GR00T SO100/SO101, DROID and reBot clients, plus RAI's two Panda manipulation demos, ROSbot XL demo and simulated-tractor demo. The other 26 remain unnamed at the robot level. Names and source/setup quotes are discovery metadata; no robot/runtime compatibility combination is inferred.

All 33 remain `source_reviewed`, `runtime_verification: not_run`, `access.mode: source_reference` and `hub_prepare: false`. No upstream module or installation command was run, no package installed, no checkpoint/dataset/mesh retrieved, and no simulator, robot or model endpoint contacted. Source terms do not relicense downstream models, dependencies, services, firmware or assets. Coverage is finite and does not claim all upstream entrypoints or all robot skills on the internet.
