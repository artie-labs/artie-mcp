import argparse
import asyncio
import json
from collections import Counter
from pathlib import Path

import yaml
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

_SMOKE_TOKEN = "container-smoke-test-token"
_ANNOTATION_EXTENSION = "x-artie-mcp"
_HTTP_METHODS = frozenset(
    {"get", "put", "post", "delete", "patch", "head", "options", "trace"}
)


def parse_arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--openapi-path", type=Path, required=True)
    return parser.parse_args()


def annotation_fingerprint(annotations: dict) -> str:
    return json.dumps(annotations, sort_keys=True)


def openapi_annotation_counts(openapi_path: Path) -> Counter[str]:
    with openapi_path.open() as file:
        spec = yaml.safe_load(file)

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


async def smoke_test(url: str, openapi_path: Path):
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

    expected_annotations = openapi_annotation_counts(openapi_path)
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
    asyncio.run(smoke_test(arguments.url, arguments.openapi_path))
