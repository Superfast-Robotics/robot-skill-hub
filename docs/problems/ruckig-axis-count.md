# Ruckig state and limit vectors must share an axis count

Position, velocity, acceleration and all limits must describe the same ordered axes. Match vector lengths and coordinate_type explicitly.

Runtime: `ruckig`. Recipe: `ruckig-online-trajectory`. Source revision: `a8db97a4e9c55e5160a3855f739fa3b270df8e4c`.

[Find applicable prepared recipes](https://api.superfastrobotics.com/v1/search?q=trajectory&runtime=ruckig&kind=preparation_recipe&limit=3). Follow the returned pinned `inspect_url` for the exact interface, evidence and prior findings. [Preparation and execution](https://hub.superfastrobotics.com/executable-skills.md) remain separate local operations. Source files retain their original license and authors.

## Reproduction input

Mode: `input`. Reproduction recipe: `ruckig-online-trajectory`.

```json
{
  "current_position": [
    0,
    0,
    0.5
  ],
  "current_velocity": [
    0.0,
    0.0
  ],
  "current_acceleration": [
    0,
    0,
    0
  ],
  "target_position": [
    1,
    -0.5,
    0.25
  ],
  "target_velocity": [
    0,
    0,
    0
  ],
  "target_acceleration": [
    0,
    0,
    0
  ],
  "max_velocity": [
    1,
    1,
    1
  ],
  "max_acceleration": [
    2,
    2,
    2
  ],
  "max_jerk": [
    4,
    4,
    4
  ],
  "dt": 0.01,
  "coordinate_type": "revolute_rad"
}
```

## Valid adapter input

```json
{
  "current_position": [
    0,
    0,
    0.5
  ],
  "current_velocity": [
    0,
    0,
    0
  ],
  "current_acceleration": [
    0,
    0,
    0
  ],
  "target_position": [
    1,
    -0.5,
    0.25
  ],
  "target_velocity": [
    0,
    0,
    0
  ],
  "target_acceleration": [
    0,
    0,
    0
  ],
  "max_velocity": [
    1,
    1,
    1
  ],
  "max_acceleration": [
    2,
    2,
    2
  ],
  "max_jerk": [
    4,
    4,
    4
  ],
  "dt": 0.01,
  "coordinate_type": "revolute_rad"
}
```

Use the `tools/verify_problem_cases.py` harness at the published Hub commit with the checksum-verified source cache. `input` cases require rejection of the first input and success for the valid input. `upstream_interpolation` separately demonstrates the original source function's wrong point; `handoff` tests contract compatibility only. Neither mode claims physical execution.

The [source and receipts](https://github.com/Superfast-Robotics/robot-skill-hub/tree/main/evidence/integration/agent-discovery-v1) distinguish reproduced failures from successful bounded checks. A useful new observation can be saved locally with the scoped Hub CLI; public sharing requires the project's existing permission.

Authored reproduction; not autonomous agent discovery, general accuracy or hardware verification.
