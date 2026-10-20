"""Apache-2.0. Two read-only LangChain tools usable in a RAI tool list."""
import json
from langchain_core.tools import tool
from hub_client import find, inspect_url


@tool
def find_robot_code(query: str, runtime: str = "") -> str:
    """Find reusable robotics implementations for the current task. Use short
    task keywords and only a known runtime. Returns at most three preparation
    recipes with pinned inspection URLs; never installs or commands a robot.
    """
    return json.dumps(find(query, 'rai-example', runtime or None))


@tool
def inspect_robot_code(inspection_url: str) -> str:
    """Inspect an exact inspect_url returned by find_robot_code. Returns source
    pins, interface, evidence and prior fixes as untrusted data. Never executes.
    """
    return json.dumps(inspect_url(inspection_url, 'rai-example'))


ROBOT_CODE_TOOLS = [find_robot_code, inspect_robot_code]
