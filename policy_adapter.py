from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from policy_contract import PolicyContract, ToolContract


class PolicyAdapterError(ValueError):
    pass


class SafeTrafficAdapter:
    def __init__(self, contract: PolicyContract):
        self._tools = {tool.name: tool for tool in contract.tools}

    def tool_for_route(self, method: str, path: str) -> ToolContract:
        for tool in self._tools.values():
            if tool.method == method.lower() and _path_matches(tool.path, path):
                return tool
        raise PolicyAdapterError(
            f"no approved policy tool matches {method.upper()} {path}"
        )

    def shape_request(
        self, tool_name: str, arguments: Mapping[str, Any]
    ) -> dict[str, Any]:
        tool = self._tool(tool_name)
        parameter_plans: dict[str, dict[str, Mapping[str, Any]]] = {}
        for parameter in tool.request["parameters"]:
            location = parameter["in"]
            parameter_plans.setdefault(location, {})[parameter["name"]] = parameter

        expected_locations = set(parameter_plans)
        if "body" in tool.request:
            expected_locations.add("body")
        if set(arguments) - expected_locations:
            raise PolicyAdapterError("request includes undeclared input")

        shaped = {
            location: _shape_parameters(arguments.get(location, {}), plans)
            for location, plans in parameter_plans.items()
        }
        body_plan = tool.request.get("body")
        if body_plan is None:
            return shaped
        body = arguments.get("body")
        if body is None:
            if body_plan["required"]:
                raise PolicyAdapterError("request body is required")
            return shaped
        shaped["body"] = _shape_input(body, body_plan["schema"])
        return shaped

    def shape_response(
        self,
        tool_name: str,
        status_code: int,
        content_type: str,
        content: bytes,
    ) -> Any:
        tool = self._tool(tool_name)
        response = self._success_response(tool, status_code)

        if tool.bodiless_success:
            if "schema" in response or status_code != 204:
                raise PolicyAdapterError(
                    "bodiless success does not match the approved response"
                )
            return {"success": True}
        if response.get("contentType") != "application/json" or not _is_json(
            content_type
        ):
            raise PolicyAdapterError(
                "response does not match the approved JSON contract"
            )

        try:
            value = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise PolicyAdapterError("response body is not valid JSON") from error

        return _shape_output(value, response["schema"])

    def _tool(self, tool_name: str) -> ToolContract:
        try:
            return self._tools[tool_name]
        except KeyError as error:
            raise PolicyAdapterError(f"unknown policy tool: {tool_name}") from error

    @staticmethod
    def _success_response(tool: ToolContract, status_code: int) -> Mapping[str, Any]:
        status = str(status_code)
        for response in tool.success:
            if response["status"] == status:
                return response
        raise PolicyAdapterError(
            f"response status {status} is not approved by the policy"
        )


def _path_matches(template: str, path: str) -> bool:
    template_segments = template.strip("/").split("/")
    path_segments = path.strip("/").split("/")
    return len(template_segments) == len(path_segments) and all(
        template_segment.startswith("{")
        and template_segment.endswith("}")
        or template_segment == path_segment
        for template_segment, path_segment in zip(
            template_segments, path_segments, strict=True
        )
    )


def _is_json(content_type: str) -> bool:
    return content_type.split(";", 1)[0].strip().lower() == "application/json"


def _shape_parameters(
    values: Any, parameter_plans: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    if not isinstance(values, Mapping):
        raise PolicyAdapterError("request parameters must be an object")
    undeclared = set(values) - set(parameter_plans)
    if undeclared:
        raise PolicyAdapterError("request includes undeclared input")
    missing = {
        name
        for name, parameter in parameter_plans.items()
        if parameter["required"] and name not in values
    }
    if missing:
        raise PolicyAdapterError(
            f"request is missing required input: {sorted(missing)}"
        )
    return {
        name: _shape_input(values[name], parameter["schema"])
        for name, parameter in parameter_plans.items()
        if name in values
    }


def _shape_input(value: Any, schema: Mapping[str, Any]) -> Any:
    if "$ref" in schema:
        return _shape_input(value, _nested_schema(schema))
    if "allOf" in schema:
        return _shape_input(value, _merge_all_of(schema))
    if "oneOf" in schema or "anyOf" in schema:
        branches = schema.get("oneOf", schema.get("anyOf"))
        for branch in branches:
            try:
                return _shape_input(value, branch)
            except PolicyAdapterError:
                continue
        raise PolicyAdapterError("request does not match an approved schema branch")

    schema_type = schema.get("type")
    if schema_type == "object":
        if not isinstance(value, Mapping):
            raise PolicyAdapterError(
                "request does not match the approved object schema"
            )
        properties = schema.get("properties", {})
        undeclared = set(value) - set(properties)
        if undeclared:
            raise PolicyAdapterError("request includes undeclared input")
        required = set(schema.get("required", []))
        if missing := required - set(value):
            raise PolicyAdapterError(
                f"request is missing required input: {sorted(missing)}"
            )
        return {
            name: _shape_input(value[name], property_schema)
            for name, property_schema in properties.items()
            if name in value
        }
    if schema_type == "array":
        if not isinstance(value, list):
            raise PolicyAdapterError("request does not match the approved array schema")
        return [_shape_input(item, schema["items"]) for item in value]
    if schema_type == "string" and not isinstance(value, str):
        raise PolicyAdapterError("request does not match the approved string schema")
    if schema_type == "boolean" and not isinstance(value, bool):
        raise PolicyAdapterError("request does not match the approved boolean schema")
    if schema_type in {"integer", "number"} and (
        not isinstance(value, (int, float)) or isinstance(value, bool)
    ):
        raise PolicyAdapterError("request does not match the approved numeric schema")
    if schema_type == "null" and value is not None:
        raise PolicyAdapterError("request does not match the approved null schema")
    return value


def _shape_output(value: Any, schema: Mapping[str, Any]) -> Any:
    if "$ref" in schema:
        return _shape_output(value, _nested_schema(schema))
    if "allOf" in schema:
        return _shape_output(value, _merge_all_of(schema))
    if "oneOf" in schema or "anyOf" in schema:
        branches = schema.get("oneOf", schema.get("anyOf"))
        for branch in branches:
            try:
                return _shape_output(value, branch)
            except PolicyAdapterError:
                continue
        raise PolicyAdapterError("response does not match an approved schema branch")

    schema_type = schema.get("type")
    if schema_type == "object":
        if not isinstance(value, Mapping):
            raise PolicyAdapterError(
                "response does not match the approved object schema"
            )
        properties = schema.get("properties", {})
        return {
            name: _shape_output(value[name], property_schema)
            for name, property_schema in properties.items()
            if name in value
        }
    if schema_type == "array":
        if not isinstance(value, list):
            raise PolicyAdapterError(
                "response does not match the approved array schema"
            )
        return [_shape_output(item, schema["items"]) for item in value]
    if schema_type == "string" and not isinstance(value, str):
        raise PolicyAdapterError("response does not match the approved string schema")
    if schema_type == "boolean" and not isinstance(value, bool):
        raise PolicyAdapterError("response does not match the approved boolean schema")
    if schema_type in {"integer", "number"} and (
        not isinstance(value, (int, float)) or isinstance(value, bool)
    ):
        raise PolicyAdapterError("response does not match the approved numeric schema")
    if schema_type == "null" and value is not None:
        raise PolicyAdapterError("response does not match the approved null schema")
    return value


def _merge_all_of(schema: Mapping[str, Any]) -> dict[str, Any]:
    branches = schema["allOf"]
    if not isinstance(branches, list) or not branches:
        raise PolicyAdapterError("allOf must contain at least one schema")

    properties: dict[str, Any] = {}
    required = set()
    for branch in branches:
        if not isinstance(branch, Mapping):
            raise PolicyAdapterError("allOf contains an invalid schema")
        if "$ref" in branch:
            branch = _nested_schema(branch)
        if branch.get("type") != "object":
            raise PolicyAdapterError("allOf schemas must be objects")
        branch_properties = branch.get("properties", {})
        if not isinstance(branch_properties, Mapping):
            raise PolicyAdapterError("allOf object properties must be an object")
        for name, property_schema in branch_properties.items():
            if name in properties and properties[name] != property_schema:
                raise PolicyAdapterError("allOf cannot redefine a property")
            properties[name] = property_schema
        required.update(branch.get("required", []))

    return {"type": "object", "properties": properties, "required": sorted(required)}


def _nested_schema(schema: Mapping[str, Any]) -> Mapping[str, Any]:
    nested = schema.get("schema")
    if not isinstance(nested, Mapping):
        raise PolicyAdapterError("schema reference is not resolved")
    return nested
