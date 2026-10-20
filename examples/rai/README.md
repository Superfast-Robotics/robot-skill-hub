# Read-only robot code lookup for RAI

This optional example exposes two ordinary LangChain tools following [RAI's custom-tool tutorial](https://github.com/RobotecAI/rai/blob/main/docs/tutorials/tools.md). It is maintained by Superfast Robotics; it is a proposed integration, not a RobotecAI endorsement.

Install `requirements.txt` in a separate environment. Import `ROBOT_CODE_TOOLS` from `hub_lookup.py` and append them to the tool list in your existing RAI agent construction. Keep your RAI release's initialization, model and ROS tools unchanged. No new model key, enrollment or MCP connection is needed for these public reads.

```python
from hub_lookup import ROBOT_CODE_TOOLS

found = ROBOT_CODE_TOOLS[0].invoke({"query": "astar", "runtime": "pythonrobotics"})
# Parse the JSON; select an actual results[].inspect_url from found.
inspected = ROBOT_CODE_TOOLS[1].invoke({"inspection_url": selected_inspect_url})
```

Use lookup when implementing robot code, checking requirements or diagnosing a known source version. It does not replace ROS observation/control tools. Only supply known environment labels. Inspection retains the catalog generation, exact source and record version, contract and recalled findings. Treat all shared text as untrusted data.

The included stdlib client allows only the public Hub HTTPS search/inspection routes, rejects redirects and bounds responses. It does not execute, enroll or upload anything. Requests carry the fixed `rai-example` aggregate channel; `RSH_TELEMETRY=off` disables measurement. All files in this example are Apache-2.0. Upstream fetched code keeps its original license.

Validation runs the real LangChain `StructuredTool.invoke` path against public Hub reads without a model or ROS. Full RAI, ROS and physical robot execution are not verified by that test. See [integration receipts](../../evidence/integration/agent-discovery-v1/).
