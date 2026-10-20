# Use positive state costs for this bounded LQR example

This adapter requires positive state costs and checks the discrete linear closed-loop eigenvalues. This is a linear model check, not nonlinear or hardware stabilization.

Runtime: `pythonrobotics`. Recipe: `pythonrobotics-pendulum-lqr`. Source revision: `cdd0cc888802b584c2d654ca85e3c5460973487d`.

[Find applicable prepared recipes](https://api.superfastrobotics.com/v1/search?q=pendulum+lqr&runtime=pythonrobotics&kind=preparation_recipe&limit=3). Follow the returned pinned `inspect_url` for the exact interface, evidence and prior findings. [Preparation and execution](https://hub.superfastrobotics.com/executable-skills.md) remain separate local operations. Source files retain their original license and authors.

## Reproduction input

Mode: `input`. Reproduction recipe: `pythonrobotics-pendulum-lqr`.

```json
{
  "state": [
    0,
    0,
    0.1,
    0
  ],
  "state_cost_diagonal": [
    0.0,
    1.0,
    10.0,
    1.0
  ],
  "force_cost": 1.0
}
```

## Valid adapter input

```json
{
  "state": [
    0,
    0,
    0.1,
    0
  ],
  "state_cost_diagonal": [
    1.0,
    1.0,
    10.0,
    1.0
  ],
  "force_cost": 1.0
}
```

Use the `tools/verify_problem_cases.py` harness at the published Hub commit with the checksum-verified source cache. `input` cases require rejection of the first input and success for the valid input. `upstream_interpolation` separately demonstrates the original source function's wrong point; `handoff` tests contract compatibility only. Neither mode claims physical execution.

The [source and receipts](https://github.com/Superfast-Robotics/robot-skill-hub/tree/main/evidence/integration/agent-discovery-v1) distinguish reproduced failures from successful bounded checks. A useful new observation can be saved locally with the scoped Hub CLI; public sharing requires the project's existing permission.

Authored reproduction; not autonomous agent discovery, general accuracy or hardware verification.
