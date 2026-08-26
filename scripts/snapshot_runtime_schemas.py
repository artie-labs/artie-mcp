#!/usr/bin/env python3
"""Record the reviewed wire schemas that FastMCP publishes for policy tools."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import server


_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_SNAPSHOT_PATH = _REPOSITORY_ROOT / "contract" / "policy.contract.json"


def _canonical(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _canonical(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_canonical(item) for item in value]
    return value


def main() -> int:
    snapshot = json.loads(_SNAPSHOT_PATH.read_text())
    tools = {tool.name: tool for tool in asyncio.run(server.mcp.list_tools())}

    if {tool["name"] for tool in snapshot["tools"]} != set(tools):
        raise ValueError("runtime MCP inventory does not match the policy snapshot")

    for tool in snapshot["tools"]:
        runtime_tool = tools[tool["name"]]
        tool["inputSchema"] = _canonical(runtime_tool.parameters)
        tool["outputSchema"] = _canonical(runtime_tool.output_schema)

    snapshot["formatVersion"] = 3
    _SNAPSHOT_PATH.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
