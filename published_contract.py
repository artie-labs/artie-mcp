from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any


class PublishedContractError(ValueError):
    pass


def policy_snapshot_without_published_schema_signatures(
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    tools = snapshot.get("tools")
    if not isinstance(tools, list) or not all(isinstance(tool, dict) for tool in tools):
        return snapshot
    policy_snapshot = dict(snapshot)
    policy_snapshot["tools"] = [
        {
            key: value
            for key, value in tool.items()
            if key not in {"publishedInputSchemaSHA256", "publishedOutputSchemaSHA256"}
        }
        for tool in tools
    ]
    return policy_snapshot


def tool_schema_signatures(tools: Iterable[Any]) -> dict[str, dict[str, str]]:
    signatures = {}
    for tool in tools:
        name = getattr(tool, "name", None)
        parameters = getattr(tool, "parameters", None)
        if parameters is None:
            parameters = getattr(tool, "inputSchema", None)
        output_schema = getattr(tool, "output_schema", None)
        if output_schema is None:
            output_schema = getattr(tool, "outputSchema", None)
        if not isinstance(name, str) or not isinstance(parameters, dict):
            raise PublishedContractError(
                "published tool has an invalid name or input schema"
            )
        if output_schema is not None and not isinstance(output_schema, dict):
            raise PublishedContractError("published tool has an invalid output schema")
        if name in signatures:
            raise PublishedContractError(f"published tool name is duplicated: {name}")
        signatures[name] = {
            "publishedInputSchemaSHA256": _canonical_sha256(parameters),
            "publishedOutputSchemaSHA256": _canonical_sha256(output_schema),
        }
    return dict(sorted(signatures.items()))


def add_published_schema_signatures(
    snapshot: dict[str, Any], signatures: dict[str, dict[str, str]]
) -> dict[str, Any]:
    tools = snapshot.get("tools")
    if not isinstance(tools, list):
        raise PublishedContractError("policy contract snapshot must define tools")

    snapshot_names = {tool.get("name") for tool in tools if isinstance(tool, dict)}
    if len(snapshot_names) != len(tools) or not all(
        isinstance(name, str) for name in snapshot_names
    ):
        raise PublishedContractError("policy contract snapshot has invalid tool names")
    if snapshot_names != set(signatures):
        raise PublishedContractError("published tools do not match the policy contract")

    updated_snapshot = dict(snapshot)
    updated_tools = []
    for tool in tools:
        updated_tool = dict(tool)
        updated_tool.update(signatures[updated_tool["name"]])
        updated_tools.append(updated_tool)
    updated_snapshot["tools"] = updated_tools
    return updated_snapshot


def verify_published_schema_signatures(
    snapshot: dict[str, Any], signatures: dict[str, dict[str, str]]
) -> None:
    tools = snapshot.get("tools")
    if not isinstance(tools, list):
        raise PublishedContractError("policy contract snapshot must define tools")

    expected = {}
    for tool in tools:
        if not isinstance(tool, dict) or not isinstance(tool.get("name"), str):
            raise PublishedContractError(
                "policy contract snapshot has invalid tool names"
            )
        name = tool["name"]
        input_signature = tool.get("publishedInputSchemaSHA256")
        output_signature = tool.get("publishedOutputSchemaSHA256")
        if not isinstance(input_signature, str) or not isinstance(
            output_signature, str
        ):
            raise PublishedContractError(
                f"policy contract snapshot is missing published schema signatures for {name}"
            )
        expected[name] = {
            "publishedInputSchemaSHA256": input_signature,
            "publishedOutputSchemaSHA256": output_signature,
        }

    if expected != signatures:
        raise PublishedContractError(
            "published tool schemas do not match the policy contract snapshot"
        )


def _canonical_sha256(value: Any) -> str:
    canonical_value = json.dumps(value, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical_value.encode()).hexdigest()
