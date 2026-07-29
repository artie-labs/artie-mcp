import argparse
import asyncio
import json
import urllib.request
from collections import Counter

import yaml
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

_SMOKE_TOKEN = "container-smoke-test-token"
_ANNOTATION_EXTENSION = "x-artie-mcp"
_ANNOTATION_KEYS = frozenset(
    {"readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"}
)
_HTTP_METHODS = frozenset(
    {"get", "put", "post", "delete", "patch", "head", "options", "trace"}
)


def parse_arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--openapi-url", required=True)
    return parser.parse_args()


def annotation_fingerprint(annotations: dict) -> str:
    if not _ANNOTATION_KEYS.issubset(annotations):
        raise AssertionError("OpenAPI operation is missing MCP tool annotations")
    return json.dumps(
        {key: annotations[key] for key in _ANNOTATION_KEYS}, sort_keys=True
    )


def openapi_annotation_counts(openapi_url: str) -> Counter[str]:
    with urllib.request.urlopen(openapi_url, timeout=30) as response:
        spec = yaml.safe_load(response)

    annotations = Counter()
    for path_item in spec.get("paths", {}).values():
        for method, operation in path_item.items():
            if method.lower() not in _HTTP_METHODS:
                continue
            extension = operation.get(_ANNOTATION_EXTENSION)
            if not isinstance(extension, dict):
                raise AssertionError(
                    f"OpenAPI operation is missing {_ANNOTATION_EXTENSION}"
                )
            annotations[annotation_fingerprint(extension)] += 1

    return annotations


async def smoke_test(url: str, openapi_url: str):
    async with streamablehttp_client(
        url, headers={"Authorization": f"Bearer {_SMOKE_TOKEN}"}
    ) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()

    if not tools.tools:
        raise AssertionError("MCP tools/list response is empty")

    missing_annotations = [
        tool.name for tool in tools.tools if tool.annotations is None
    ]
    if missing_annotations:
        raise AssertionError(
            f"MCP tools/list response is missing annotations: {missing_annotations!r}"
        )

    rendered_annotations = Counter()
    for tool in tools.tools:
        assert tool.annotations is not None
        rendered_annotations[
            annotation_fingerprint(tool.annotations.model_dump(exclude_none=True))
        ] += 1

    expected_annotations = openapi_annotation_counts(openapi_url)
    print(
        json.dumps(
            {
                "expectedAnnotationCount": sum(expected_annotations.values()),
                "renderedAnnotationCount": sum(rendered_annotations.values()),
                "annotations": [
                    {"value": json.loads(value), "count": count}
                    for value, count in sorted(rendered_annotations.items())
                ],
            },
            sort_keys=True,
        )
    )
    if rendered_annotations != expected_annotations:
        raise AssertionError(
            "MCP tools/list annotation counts do not match the OpenAPI contract"
        )


if __name__ == "__main__":
    arguments = parse_arguments()
    asyncio.run(smoke_test(arguments.url, arguments.openapi_url))
