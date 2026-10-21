---
title: Robot Skill Hub
emoji: 🤖
colorFrom: blue
colorTo: blue
sdk: static
app_file: index.html
pinned: false
license: apache-2.0
tags:
- robotics
- agents
- mcp
- motion-planning
---

# Robot Skill Hub: reusable robot code for coding agents

Official Superfast Robotics discovery entry. Search pinned implementations, inspect I/O and coordinate contracts, recall exact-source findings, then prepare supported recipes in a local project. Public reads need no account, installation or GPU.

- [Search A* planning](https://api.superfastrobotics.com/v1/search?q=astar&runtime=pythonrobotics&kind=preparation_recipe&limit=3)
- [Search inverse kinematics](https://api.superfastrobotics.com/v1/search?q=inverse%20kinematics&runtime=pybullet&kind=preparation_recipe&limit=3)
- [Search trajectories](https://api.superfastrobotics.com/v1/search?q=trajectory&runtime=ruckig&kind=preparation_recipe&limit=3)
- [Agent contract](https://hub.superfastrobotics.com/agent.json)
- [Reproducible problem cases](https://hub.superfastrobotics.com/problems/)
- [Canonical source](https://github.com/Superfast-Robotics/robot-skill-hub)
- Read-only MCP: `https://api.superfastrobotics.com/mcp`

The static Space does not host an MCP transport or run a model. Add the remote MCP endpoint explicitly if your agent supports it. This is not automatic availability in every agent.

Install only the task entrypoint you need:

```sh
npx skills add https://hub.superfastrobotics.com --skill robot-motion-planning
npx skills add https://hub.superfastrobotics.com --skill robot-kinematics
npx skills add https://hub.superfastrobotics.com --skill robot-trajectory
```

Prepared adapters distinguish numerical checks, simulation and real interfaces. A catalog match does not establish robot compatibility or hardware success. Follow exact pins, license and evidence. Public findings remain contributor-reported data; sharing uses the project's existing explicit scope.

This static discovery card uses no compute, analytics script, cookie or background API request. API calls support `DNT: 1` or `X-RSH-Telemetry: off`.

## Robot coding reuse experiment

[Read the short GPT-6 Luna article and all 30 productivity trials](https://huggingface.co/datasets/Superfast-BS/robot-skill-hub-luna-reuse). Direct implementation versus required skill reuse, with measured time, success, retries and total tokens.
