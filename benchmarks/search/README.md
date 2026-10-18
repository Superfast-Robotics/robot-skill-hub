# Authored robotics search baseline

`tasks.h15.json` contains 20 distinct engineering task intents, each with a short
query and a natural task paraphrase, plus 20 contract controls. Targets are real
H15 catalog IDs with frozen source, record-version, license and canonical-record
hashes. The set includes xArm6 and SO100 preparation recipes; UR, GO2, FR3,
Panda and Jaco source labels; MJCF/xacro models; manipulation, locomotion,
planning, state estimation, visual servoing and ROS controller implementations.
Source labels describe discovery facts and do not certify a robot/environment.

These are maintainer-authored cases, not external-user queries, a representative
language distribution or evidence of agent adoption. Short queries intentionally
contrast with natural paraphrases. Relevant labels are selected existing targets,
not exhaustive judgments: report labeled recall and hit rate, not precision or
general-population search quality. MRR is truncated at 10 results.

The runner calls the actual first-party `rshlib.core.find` without changing its
matching/ranking code. It reads a complete local publisher fixture, checks the
resource hashes and all 16 compact pages, and keeps sources in
`references.records`. The retained fixture's candidate generation is preserved;
the manifest records the equal Git tree of the actual H15 main separately.
Bundled snapshots are not used or refreshed.

```sh
python -s -B tools/evaluate_search.py \
  --site <retained-complete-H15-publisher-site> \
  --build-receipt <matching-retained-build-result.json> \
  --output-dir evidence/search/h15-baseline-01
```

Output must be fresh. The exact input cases, runner, matcher and resource hashes,
case results, raw matcher responses, retrieval metrics and separate control
outcomes are retained. Retrieval misses are measurements, not a reason to change
labels after the run. Expected-error controls preserve the actual reason code.
Network/DNS and subprocess audit events are denied in the evaluation process.
No robot source, source acquisition, dependency, native index, API/MCP request,
CLI subprocess, embedding or model runs. Evaluating the Python matcher alone
does not establish new agreement with the static server or native index.

Controls cover exact-ID priority, an explicit eight-field recipe combination,
robot/Python conflicts, unknown source compatibility, discovery-label versus
support distinctions, A*/D*/RRT* families, punctuation, embedded symbols and
generation refusal. Embedded-symbol cases test normalization only; they do not
assume the remaining ordinary word prefixes must have zero catalog matches.
