# EKF covariance must be symmetric positive definite

A zero/negative initial covariance eigenvalue violates this adapter precondition. The valid example uses a positive diagonal covariance; choose values justified by the actual model.

Runtime: `pythonrobotics`. Recipe: `pythonrobotics-ekf-update`. Source revision: `cdd0cc888802b584c2d654ca85e3c5460973487d`.

[Find applicable prepared recipes](https://api.superfastrobotics.com/v1/search?q=ekf&runtime=pythonrobotics&kind=preparation_recipe&limit=3). Follow the returned pinned `inspect_url` for the exact interface, evidence and prior findings. [Preparation and execution](https://hub.superfastrobotics.com/executable-skills.md) remain separate local operations. Source files retain their original license and authors.

## Reproduction input

Mode: `input`. Reproduction recipe: `pythonrobotics-ekf-update`.

```json
{
  "state": [
    0,
    0,
    0,
    1
  ],
  "covariance": [
    [
      -0.1,
      0.0,
      0.0,
      0.0
    ],
    [
      0.0,
      0.1,
      0.0,
      0.0
    ],
    [
      0.0,
      0.0,
      0.1,
      0.0
    ],
    [
      0.0,
      0.0,
      0.0,
      0.1
    ]
  ],
  "measurement_xy": [
    0.15,
    0.02
  ],
  "control_v_yawrate": [
    1,
    0.1
  ]
}
```

## Valid adapter input

```json
{
  "state": [
    0,
    0,
    0,
    1
  ],
  "covariance": [
    [
      0.1,
      0.0,
      0.0,
      0.0
    ],
    [
      0.0,
      0.1,
      0.0,
      0.0
    ],
    [
      0.0,
      0.0,
      0.1,
      0.0
    ],
    [
      0.0,
      0.0,
      0.0,
      0.1
    ]
  ],
  "measurement_xy": [
    0.15,
    0.02
  ],
  "control_v_yawrate": [
    1,
    0.1
  ]
}
```

Use the `tools/verify_problem_cases.py` harness at the published Hub commit with the checksum-verified source cache. `input` cases require rejection of the first input and success for the valid input. `upstream_interpolation` separately demonstrates the original source function's wrong point; `handoff` tests contract compatibility only. Neither mode claims physical execution.

The [source and receipts](https://github.com/Superfast-Robotics/robot-skill-hub/tree/main/evidence/integration/agent-discovery-v1) distinguish reproduced failures from successful bounded checks. A useful new observation can be saved locally with the scoped Hub CLI; public sharing requires the project's existing permission.

Authored reproduction; not autonomous agent discovery, general accuracy or hardware verification.
