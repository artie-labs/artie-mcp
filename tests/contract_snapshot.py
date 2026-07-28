import asyncio
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def schema_sha256(schema):
    if schema is None:
        return None
    return hashlib.sha256(
        json.dumps(schema, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def render_contract_snapshot(server):
    tools = asyncio.run(server.mcp.list_tools())
    return {
        "pinnedSpec": {
            "version": server._PINNED_SPEC_VERSION,
            "sha256": server._PINNED_SPEC_SHA256,
        },
        "tools": [
            {
                "annotations": tool.annotations.model_dump(exclude_none=True)
                if tool.annotations
                else None,
                "description": tool.description,
                "inputSchemaSha256": schema_sha256(tool.parameters),
                "name": tool.name,
                "outputSchemaSha256": schema_sha256(tool.output_schema),
                "title": tool.title,
            }
            for tool in sorted(tools, key=lambda tool: tool.name)
        ],
    }


if __name__ == "__main__":
    import server

    print(json.dumps(render_contract_snapshot(server), indent=2, sort_keys=True))
