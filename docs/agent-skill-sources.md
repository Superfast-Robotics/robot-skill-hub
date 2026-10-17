# Robot-agent instruction source review

The [frozen upstream README](https://github.com/graph-robots/open-robot-skills/blob/752dfbd96968d4d08379f8111765efbf6457800b/README.md) describes `open-robot-skills` as a library of manipulation and tool bundles for the GaP runtime. This Hub selection indexes 43 `SKILL.md` entry documents at commit `752dfbd96968d4d08379f8111765efbf6457800b`: 33 skill contracts, 8 tool contracts and 2 policy contracts. It is a finite source snapshot, not a count of installed capabilities, tested behaviors or all robot skills on the internet.

The selection covers instruction contracts for perception, grasp proposal/selection, grasping, held-object motion, feature mating, placement, cable manipulation and outcome checks. Tool documents describe cuRobo, curve/geometry processing, Grounding DINO, SAM3, Gemini Robotics-ER, Molmo and VLM interfaces. The two policy documents describe MolmoAct LIBERO and OpenPI pi05 LIBERO checkpoint integration. These are upstream descriptions; the Hub inspected their text rather than those implementations, services or checkpoints.

[`catalog/agent-skill-projects.json`](../catalog/agent-skill-projects.json) fixes every instruction path, byte count, SHA-256, bundle kind and parsed declaration. Its SHA-256 at this review is `980017c848b56e2180d98dd2adf9f3deb37b1edb3310dcbd65d76fc75fd7b747`. The [sanitized review evidence](../evidence/sources/agent-instructions-2026-10-18.json) lists all 43 exact public source URLs and hashes, together with the checks and license dispositions. The instruction documents total 263,283 bytes. Four provenance documents total another 41,125 bytes:

| Pinned provenance document | Bytes | SHA-256 |
| --- | ---: | --- |
| [Repository license](https://github.com/graph-robots/open-robot-skills/blob/752dfbd96968d4d08379f8111765efbf6457800b/LICENSE) | 11,358 | `cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30` |
| [README](https://github.com/graph-robots/open-robot-skills/blob/752dfbd96968d4d08379f8111765efbf6457800b/README.md) | 22,918 | `4fc2f3b7c0f59e40b032d3ad1f646474763e74a9e7497cbf52ea481c9ab50ee1` |
| [Package declarations](https://github.com/graph-robots/open-robot-skills/blob/752dfbd96968d4d08379f8111765efbf6457800b/pyproject.toml) | 5,620 | `2b61f5b3abb7918e9e2d24cb3ec01233fd01ecbeae5a764e8fa47b20f465df12` |
| [TrackDLO attribution/license notice](https://github.com/graph-robots/open-robot-skills/blob/752dfbd96968d4d08379f8111765efbf6457800b/tools/curve/LICENSE.trackdlo) | 1,229 | `a1d45e46d4733cc4a8b954814510338bac728161c05a3b59f181325f0c11caef` |

The root `LICENSE` and package declaration identify Apache-2.0. Instruction frontmatter declares Apache-2.0 in 22 files, MIT in 11 files, and no license in 10 files. The importer retains the 11 differing declarations as unresolved: `license.spdx: NOASSERTION`, `license.verified: false`, and `review_status: conflicting_upstream_declarations`. Their MIT declaration and the pinned Apache-2.0 repository declaration are recorded separately. They remain source links and carry no asserted redistribution or preparation grant.

The 11 conflicts are the four `perceiving-next-item`, `perceiving-object-parts`, `perceiving-objects-oneshot` and `perceiving-objects` skill documents, and the seven `curobo`, `gemini-er`, `geometry`, `grounding-dino`, `molmo`, `sam3` and `vlm` tool documents. The other 32 records use the repository's Apache-2.0 declaration; for 10 of those, frontmatter supplies no separate license. Their `verified: true` records the source-text consistency check, not a review of all downstream code or terms. The separate TrackDLO MIT notice concerns vendored code described by the curve bundle and does not resolve the 11 instruction-license conflicts. Referenced code, models, weights, datasets, services and dependencies retain their own terms.

[`tools/import_agent_skill_sources.py`](../tools/import_agent_skill_sources.py) reads bounded text, checks byte identities and inspects selected frontmatter fields as inert data. No instruction in an upstream `SKILL.md` was adopted or followed. No dependency or connector was installed, no referenced code was imported or executed, no paid service was called, and no model, weight, dataset, mesh, simulator or robot was loaded or contacted.

The five frontmatter GPU requirements, four weight requirements and public environment-variable names are declarations only. Undeclared fields remain `unknown`; an omitted GPU declaration does not verify CPU operation. Instructions about inputs, connectors, camera calibration, exit states, checkpoints or robot motion describe what upstream expects. They do not establish that a device, runtime, policy or hardware configuration is compatible, available or successful. Discovery tags and bundle names likewise describe source text rather than executed capabilities.

Every indexed document remains `source_reviewed`, `runtime_verification: not_run`, `access.mode: source_reference` and `hub_prepare: false`. It is not an installed agent skill or a runnable Hub adapter. With the frozen text cache already populated, the offline check is:

```powershell
python tools/import_agent_skill_sources.py --check
```

Adding `--fetch` explicitly retrieves only the manifest's pinned text documents before checking them. Neither mode executes the instructions, follows linked setup commands or changes upstream revisions.
