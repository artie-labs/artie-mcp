import argparse
import asyncio
import json

import httpx

_SMOKE_TOKEN = "container-smoke-test-token"


def parse_arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    return parser.parse_args()


async def smoke_test(url: str):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            url,
            headers={
                "Accept": "application/json, text/event-stream",
                "Authorization": f"Bearer {_SMOKE_TOKEN}",
                "Content-Type": "application/json",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "capabilities": {},
                    "clientInfo": {"name": "artie-mcp-smoke", "version": "0"},
                    "protocolVersion": "2025-03-26",
                },
            },
        )

    if response.status_code != 401:
        raise AssertionError(
            "opaque API key must be rejected"
            f" (status: {response.status_code}, body: {response.text[:200]!r})"
        )
    print(json.dumps({"rejectedOpaqueToken": True, "status": 401}, sort_keys=True))


if __name__ == "__main__":
    arguments = parse_arguments()
    asyncio.run(smoke_test(arguments.url))
