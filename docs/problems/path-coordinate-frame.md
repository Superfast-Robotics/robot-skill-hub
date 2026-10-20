# Reject a path handoff between different coordinate frames

The field handoff validator rejects a map path labeled as a robot-base path. Supply an explicit transform when needed; merely relabeling coordinates is not a transform.

Runtime: `pythonrobotics`. Recipe: `pythonrobotics-astar-planner`. Source revision: `cdd0cc888802b584c2d654ca85e3c5460973487d`.

[Find applicable prepared recipes](https://api.superfastrobotics.com/v1/search?q=astar+planner&runtime=pythonrobotics&kind=preparation_recipe&limit=3). Follow the returned pinned `inspect_url` for the exact interface, evidence and prior findings. [Preparation and execution](https://hub.superfastrobotics.com/executable-skills.md) remain separate local operations. Source files retain their original license and authors.

## Reproduction input

Mode: `handoff`. Reproduction recipe: `pythonrobotics-astar-planner`.

```json
{
  "path_xy": [
    [
      2.0,
      2.0
    ],
    [
      3.0,
      3.0
    ],
    [
      4.0,
      4.0
    ]
  ],
  "target_frame": "robot_base"
}
```

## Valid adapter input

```json
{
  "start": [
    2,
    2
  ],
  "goal": [
    18,
    18
  ],
  "bounds": [
    0,
    20
  ],
  "obstacles": [
    [
      10,
      1
    ],
    [
      10,
      2
    ],
    [
      10,
      3
    ],
    [
      10,
      4
    ],
    [
      10,
      5
    ],
    [
      10,
      6
    ],
    [
      10,
      7
    ],
    [
      10,
      8
    ],
    [
      10,
      9
    ],
    [
      10,
      10
    ],
    [
      10,
      11
    ],
    [
      10,
      12
    ]
  ],
  "robot_radius": 0.3
}
```

Use the `tools/verify_problem_cases.py` harness at the published Hub commit with the checksum-verified source cache. `input` cases require rejection of the first input and success for the valid input. `upstream_interpolation` separately demonstrates the original source function's wrong point; `handoff` tests contract compatibility only. Neither mode claims physical execution.

The [source and receipts](https://github.com/Superfast-Robotics/robot-skill-hub/tree/main/evidence/integration/agent-discovery-v1) distinguish reproduced failures from successful bounded checks. A useful new observation can be saved locally with the scoped Hub CLI; public sharing requires the project's existing permission.

Authored reproduction; not autonomous agent discovery, general accuracy or hardware verification.
