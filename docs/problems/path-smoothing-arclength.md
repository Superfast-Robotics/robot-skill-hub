# Path smoothing selects the wrong arclength point

Upstream segment indexing and interpolation can select a point off the requested path segment. The Hub wrapper corrects interpolation; original source remains pinned and unchanged.

Runtime: `pythonrobotics`. Recipe: `pythonrobotics-path-smoothing`. Source revision: `cdd0cc888802b584c2d654ca85e3c5460973487d`.

[Find applicable prepared recipes](https://api.superfastrobotics.com/v1/search?q=smoothing&runtime=pythonrobotics&kind=preparation_recipe&limit=3). Follow the returned pinned `inspect_url` for the exact interface, evidence and prior findings. [Preparation and execution](https://hub.superfastrobotics.com/executable-skills.md) remain separate local operations. Source files retain their original license and authors.

## Reproduction input

Mode: `upstream_interpolation`. Reproduction recipe: `pythonrobotics-path-smoothing`.

```json
{
  "path": [
    [
      0.0,
      0.0
    ],
    [
      10.0,
      0.0
    ],
    [
      10.0,
      10.0
    ]
  ],
  "distance": 5.0,
  "expected": [
    5.0,
    0.0,
    0
  ]
}
```

## Valid adapter input

```json
{
  "path_xy": [
    [
      0,
      0
    ],
    [
      1,
      1
    ],
    [
      2,
      0
    ],
    [
      3,
      1
    ],
    [
      4,
      0
    ]
  ],
  "obstacles": [],
  "robot_radius": 0.2,
  "seed": 0
}
```

Use the `tools/verify_problem_cases.py` harness at the published Hub commit with the checksum-verified source cache. `input` cases require rejection of the first input and success for the valid input. `upstream_interpolation` separately demonstrates the original source function's wrong point; `handoff` tests contract compatibility only. Neither mode claims physical execution.

The [source and receipts](https://github.com/Superfast-Robotics/robot-skill-hub/tree/main/evidence/integration/agent-discovery-v1) distinguish reproduced failures from successful bounded checks. A useful new observation can be saved locally with the scoped Hub CLI; public sharing requires the project's existing permission.

Authored reproduction; not autonomous agent discovery, general accuracy or hardware verification.
