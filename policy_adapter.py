from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from policy_contract import BODILESS_SUCCESS_PLANS, PolicyContract, ToolContract


class PolicyAdapterError(ValueError):
    pass


class SafeTrafficAdapter:
    def __init__(self, contract: PolicyContract):
        self._tools = {tool.name: tool for tool in contract.tools}

    def tool_for_route(self, method: str, path: str) -> ToolContract:
        matches = [
            tool
            for tool in self._tools.values()
            if tool.method == method.lower() and _path_matches(tool.path, path)
        ]
        if not matches:
            raise PolicyAdapterError(
                f"no approved policy tool matches {method.upper()} {path}"
            )
        matches.sort(key=_route_specificity, reverse=True)
        if len(matches) > 1 and _route_specificity(matches[0]) == _route_specificity(
            matches[1]
        ):
            raise PolicyAdapterError(
                f"ambiguous policy tools match {method.upper()} {path}"
            )
        return matches[0]

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
            if tool.success not in BODILESS_SUCCESS_PLANS:
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


def _route_specificity(tool: ToolContract) -> int:
    return sum(
        not (segment.startswith("{") and segment.endswith("}"))
        for segment in tool.path.strip("/").split("/")
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


def _shape_output(value: Any, schema: Mapping[str, Any]) -> Any:
    if "$ref" in schema:
        return _shape_output(value, _nested_schema(schema))
    if "allOf" in schema:
        return _shape_output(value, _merge_all_of(schema))
    if "oneOf" in schema or "anyOf" in schema:
        branches = schema.get("oneOf", schema.get("anyOf"))
        return _shape_output(value, _select_schema_branch(value, branches, "response"))

    schema_type = _schema_type(schema, value, "response")
    if schema_type == "object":
        if not isinstance(value, Mapping):
            raise PolicyAdapterError(
                "response does not match the approved object schema"
            )
        properties = schema.get("properties", {})
        required = set(schema.get("required", []))
        if missing := required - set(value):
            raise PolicyAdapterError(
                f"response is missing required output: {sorted(missing)}"
            )
        shaped = {
            name: _shape_output(value[name], property_schema)
            for name, property_schema in properties.items()
            if name in value
        }
        extra = schema.get("additionalProperties")
        if extra is True or extra == {}:
            for name, item in value.items():
                if name not in properties:
                    shaped[name] = item
        elif isinstance(extra, Mapping):
            for name, item in value.items():
                if name not in properties:
                    shaped[name] = _shape_output(item, extra)
        return shaped
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
    if schema_type == "integer" and not _is_integer(value):
        raise PolicyAdapterError("response does not match the approved numeric schema")
    if schema_type == "number" and not _is_number(value):
        raise PolicyAdapterError("response does not match the approved numeric schema")
    if schema_type == "null" and value is not None:
        raise PolicyAdapterError("response does not match the approved null schema")
    return value


def _select_schema_branch(value: Any, branches: Any, subject: str) -> Mapping[str, Any]:
    if not isinstance(branches, list):
        raise PolicyAdapterError(f"{subject} schema branches must be an array")

    matches = []
    for branch in branches:
        if not isinstance(branch, Mapping):
            raise PolicyAdapterError(f"{subject} schema branch must be an object")
        try:
            matches.append((_branch_specificity(value, branch, subject), branch))
        except PolicyAdapterError:
            continue
    if not matches:
        raise PolicyAdapterError(f"{subject} does not match an approved schema branch")

    matches.sort(key=lambda match: match[0], reverse=True)
    if len(matches) > 1 and matches[0][0] == matches[1][0]:
        raise PolicyAdapterError(f"{subject} matches multiple schema branches")
    return matches[0][1]


def _branch_specificity(value: Any, schema: Mapping[str, Any], subject: str) -> int:
    if "$ref" in schema:
        schema = _nested_schema(schema)
    if "allOf" in schema:
        schema = _merge_all_of(schema)
    schema_type = _schema_type(schema, value, subject)
    if schema_type == "object":
        if not isinstance(value, Mapping):
            raise PolicyAdapterError(
                f"{subject} does not match an approved object schema"
            )
        properties = schema.get("properties", {})
        if not isinstance(properties, Mapping):
            raise PolicyAdapterError(f"{subject} object properties must be an object")
        required = set(schema.get("required", []))
        if missing := required - set(value):
            raise PolicyAdapterError(
                f"{subject} is missing required fields: {sorted(missing)}"
            )
        matched = len(set(value) & set(properties))
        if properties and not matched:
            raise PolicyAdapterError(f"{subject} has no matching object properties")
        return matched
    if schema_type == "array" and not isinstance(value, list):
        raise PolicyAdapterError(f"{subject} does not match an approved array schema")
    if schema_type == "string" and not isinstance(value, str):
        raise PolicyAdapterError(f"{subject} does not match an approved string schema")
    if schema_type == "boolean" and not isinstance(value, bool):
        raise PolicyAdapterError(f"{subject} does not match an approved boolean schema")
    if schema_type == "integer" and not _is_integer(value):
        raise PolicyAdapterError(f"{subject} does not match an approved numeric schema")
    if schema_type == "number" and not _is_number(value):
        raise PolicyAdapterError(f"{subject} does not match an approved numeric schema")
    if schema_type == "null" and value is not None:
        raise PolicyAdapterError(f"{subject} does not match an approved null schema")
    return 1


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_integer(value: Any) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        or (isinstance(value, float) and value.is_integer())
    )


def _schema_type(schema: Mapping[str, Any], value: Any, subject: str) -> str:
    type_spec = schema.get("type")
    if isinstance(type_spec, str):
        return type_spec
    if not isinstance(type_spec, list) or not all(
        isinstance(schema_type, str) for schema_type in type_spec
    ):
        raise PolicyAdapterError(f"{subject} schema must declare a type")
    if value is None and "null" in type_spec:
        return "null"
    concrete_types = [schema_type for schema_type in type_spec if schema_type != "null"]
    if len(concrete_types) == 1:
        return concrete_types[0]
    raise PolicyAdapterError(f"{subject} schema has ambiguous types")


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
        if _schema_type(branch, {}, "allOf") != "object":
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
