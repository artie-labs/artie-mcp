import argparse
import asyncio
import json
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

_SMOKE_TOKEN = "container-smoke-test-token"


def parse_arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--contract-path", required=True, type=Path)
    return parser.parse_args()


async def smoke_test(url: str, contract_path: Path):
    expected = json.loads(contract_path.read_text())["tools"]
    expected_by_name = {tool["name"]: tool for tool in expected}

    async with streamablehttp_client(
        url, headers={"Authorization": f"Bearer {_SMOKE_TOKEN}"}
    ) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()

    actual_by_name = {tool.name: tool for tool in tools.tools}
    if set(actual_by_name) != set(expected_by_name):
        unexpected = sorted(set(actual_by_name) - set(expected_by_name))
        missing = sorted(set(expected_by_name) - set(actual_by_name))
        raise AssertionError(
            "MCP tools/list inventory does not match the policy contract"
            f" (unexpected: {unexpected}, missing: {missing})"
        )
    for name, expected_tool in expected_by_name.items():
        actual = actual_by_name[name]
        if actual.annotations is None:
            raise AssertionError(f"MCP tool {name} is missing annotations")
        if actual.title != expected_tool["title"]:
            raise AssertionError(
                f"MCP tool {name} title does not match the policy contract"
            )
        if actual.description != expected_tool["triggerDescription"]:
            raise AssertionError(
                f"MCP tool {name} description does not match the policy contract"
            )
        if (
            actual.annotations.model_dump(exclude_none=True)
            != expected_tool["annotations"]
        ):
            raise AssertionError(
                f"MCP tool {name} annotations do not match the policy contract"
            )
    print(json.dumps({"toolCount": len(actual_by_name)}, sort_keys=True))


if __name__ == "__main__":
    arguments = parse_arguments()
    asyncio.run(smoke_test(arguments.url, arguments.contract_path))
