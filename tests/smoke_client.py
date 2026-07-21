import argparse
import asyncio

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

_SMOKE_TOKEN = "container-smoke-test-token"


def parse_arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    return parser.parse_args()


async def smoke_test(url: str):
    async with streamablehttp_client(
        url, headers={"Authorization": f"Bearer {_SMOKE_TOKEN}"}
    ) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()

    tool_names = {tool.name for tool in tools.tools}
    if "Ping_a_connector" not in tool_names:
        raise AssertionError("MCP tools/list response is missing Ping_a_connector")


if __name__ == "__main__":
    asyncio.run(smoke_test(parse_arguments().url))
