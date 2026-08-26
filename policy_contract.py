from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_MCP_POLICY_EXTENSION = "x-artie-mcp"
_HTTP_METHODS = frozenset(
    {"get", "put", "post", "delete", "patch", "head", "options", "trace"}
)
_REQUIRED_POLICY_FIELDS = frozenset(
    {
        "exposure",
        "operationId",
        "title",
        "triggerDescription",
        "readOnlyHint",
        "destructiveHint",
        "idempotentHint",
        "openWorldHint",
        "requiredScopes",
        "retrySemantics",
        "inputSensitivity",
        "outputSensitivity",
    }
)
_ALLOWED_EXPOSURES = frozenset({"exposed", "excluded"})
_ALLOWED_RETRY_SEMANTICS = frozenset({"safe", "unsafe", "safe-after-state-check"})
_ALLOWED_SENSITIVITIES = frozenset(
    {"none", "internal-identifiers", "restricted-credentials"}
)

BODILESS_SUCCESS_PLANS = (({"status": "202"},), ({"status": "204"},))


class PolicyContractError(ValueError):
    pass


@dataclass(frozen=True)
class ToolContract:
    name: str
    method: str
    path: str
    title: str
    trigger_description: str
    required_scopes: tuple[str, ...]
    annotations: dict[str, bool]
    retry_semantics: str
    input_sensitivity: str
    output_sensitivity: str
    request: dict[str, Any]
    success: tuple[dict[str, Any], ...]
    bodiless_success: bool


@dataclass(frozen=True)
class PolicyContract:
    tools: tuple[ToolContract, ...]


@dataclass(frozen=True)
class PolicyBundle:
    release_tag: str
    spec: dict[str, Any]


def load_policy_bundle(bundle_dir: Path) -> PolicyBundle:
    policy_path = bundle_dir / "policy.openapi.yaml"
    lock_path = bundle_dir / "policy.lock.json"
    try:
        policy_bytes = policy_path.read_bytes()
        lock = json.loads(lock_path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise PolicyContractError(f"failed to load policy bundle: {error}") from error

    if not isinstance(lock, dict) or lock.get("formatVersion") != 1:
        raise PolicyContractError("policy lock has an unsupported format version")
    expected_sha = lock.get("policySHA256")
    if not isinstance(expected_sha, str):
        raise PolicyContractError("policy lock must define policySHA256")
    actual_sha = hashlib.sha256(policy_bytes).hexdigest()
    if actual_sha != expected_sha:
        raise PolicyContractError("policy artifact checksum does not match policy lock")

    release = lock.get("release")
    if not isinstance(release, dict) or not isinstance(release.get("tag"), str):
        raise PolicyContractError("policy lock must define a release tag")
    try:
        spec = yaml.safe_load(policy_bytes)
    except yaml.YAMLError as error:
        raise PolicyContractError(
            f"policy artifact is malformed YAML: {error}"
        ) from error
    if not isinstance(spec, dict):
        raise PolicyContractError("policy artifact must be an object")
    info = spec.get("info")
    if not isinstance(info, dict) or info.get("version") != release["tag"]:
        raise PolicyContractError(
            "policy artifact info version must match the release tag"
        )

    return PolicyBundle(release_tag=release["tag"], spec=spec)


def compile_policy(spec: dict[str, Any]) -> PolicyContract:
    paths = spec.get("paths")
    if not isinstance(paths, dict):
        raise PolicyContractError("OpenAPI paths must be an object")

    tools = []
    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            raise PolicyContractError(f"OpenAPI path {path} must be an object")
        for method, operation in path_item.items():
            if method.lower() not in _HTTP_METHODS:
                continue
            tools.extend(_compile_operation(spec, path, method, operation))

    _validate_unique_tool_names(tools)
    return PolicyContract(tools=tuple(sorted(tools, key=lambda tool: tool.name)))


def _compile_operation(
    spec: dict[str, Any], path: str, method: str, operation: Any
) -> list[ToolContract]:
    if not isinstance(operation, dict):
        raise PolicyContractError(
            f"OpenAPI operation {method.upper()} {path} must be an object"
        )

    policy = operation.get(_MCP_POLICY_EXTENSION)
    if not isinstance(policy, dict):
        raise PolicyContractError(
            f"OpenAPI operation {method.upper()} {path} must define {_MCP_POLICY_EXTENSION}"
        )
    _validate_policy(path, method, operation, policy)

    if policy["exposure"] == "excluded":
        return []

    request = _request_plan(spec, path, method, operation)
    success = _success_plan(spec, path, method, operation)
    bodiless_success = policy.get("bodilessSuccess", False)
    if bodiless_success and success not in BODILESS_SUCCESS_PLANS:
        raise PolicyContractError(
            f"OpenAPI operation {method.upper()} {path} bodilessSuccess requires a single bodyless 202 or 204 response"
        )

    return [
        ToolContract(
            name=policy["operationId"],
            method=method.lower(),
            path=path,
            title=policy["title"],
            trigger_description=policy["triggerDescription"],
            required_scopes=tuple(policy["requiredScopes"]),
            annotations={
                key: policy[key]
                for key in (
                    "readOnlyHint",
                    "destructiveHint",
                    "idempotentHint",
                    "openWorldHint",
                )
            },
            retry_semantics=policy["retrySemantics"],
            input_sensitivity=policy["inputSensitivity"],
            output_sensitivity=policy["outputSensitivity"],
            request=request,
            success=success,
            bodiless_success=bodiless_success,
        )
    ]


def _request_plan(
    spec: dict[str, Any], path: str, method: str, operation: dict[str, Any]
) -> dict[str, Any]:
    label = f"OpenAPI operation {method.upper()} {path}"
    parameters = operation.get("parameters", [])
    if not isinstance(parameters, list):
        raise PolicyContractError(f"{label} parameters must be an array")

    plan_parameters = []
    for parameter in parameters:
        if not isinstance(parameter, dict):
            raise PolicyContractError(f"{label} parameter must be an object")
        name = parameter.get("name")
        location = parameter.get("in")
        if not isinstance(name, str) or not isinstance(location, str):
            raise PolicyContractError(f"{label} parameter must define name and in")
        schema = parameter.get("schema")
        if not isinstance(schema, dict):
            raise PolicyContractError(f"{label} parameter {name} must define a schema")
        plan_parameters.append(
            {
                "in": location,
                "name": name,
                "required": bool(parameter.get("required", False)),
                "schema": _schema_signature(spec, schema),
            }
        )

    request: dict[str, Any] = {
        "parameters": sorted(plan_parameters, key=_parameter_sort_key)
    }
    request_body = operation.get("requestBody")
    if request_body is None:
        return request
    if not isinstance(request_body, dict):
        raise PolicyContractError(f"{label} requestBody must be an object")
    content = request_body.get("content")
    if not isinstance(content, dict) or not content:
        raise PolicyContractError(f"{label} requestBody must define content")
    content_type, media = _single_json_media(label, content, "requestBody")
    schema = media.get("schema")
    if not isinstance(schema, dict):
        raise PolicyContractError(
            f"{label} requestBody {content_type} must define a schema"
        )
    request["body"] = {
        "contentType": content_type,
        "required": bool(request_body.get("required", False)),
        "schema": _schema_signature(spec, schema),
    }
    return request


def _success_plan(
    spec: dict[str, Any], path: str, method: str, operation: dict[str, Any]
) -> tuple[dict[str, Any], ...]:
    label = f"OpenAPI operation {method.upper()} {path}"
    responses = operation.get("responses")
    if not isinstance(responses, dict):
        raise PolicyContractError(f"{label} responses must be an object")

    success = []
    for status, response in responses.items():
        if not isinstance(status, str) or not status.startswith("2"):
            continue
        if not isinstance(response, dict):
            raise PolicyContractError(f"{label} response {status} must be an object")
        content = response.get("content")
        if content is None:
            success.append({"status": status})
            continue
        if not isinstance(content, dict) or not content:
            raise PolicyContractError(f"{label} response {status} has invalid content")
        content_type, media = _single_json_media(label, content, f"response {status}")
        schema = media.get("schema")
        if not isinstance(schema, dict):
            raise PolicyContractError(
                f"{label} response {status} {content_type} must define a schema"
            )
        success.append(
            {
                "contentType": content_type,
                "schema": _schema_signature(spec, schema),
                "status": status,
            }
        )
    if not success:
        raise PolicyContractError(f"{label} must define a successful response")
    return tuple(sorted(success, key=lambda response: response["status"]))


def _single_json_media(
    label: str, content: dict[str, Any], subject: str
) -> tuple[str, dict[str, Any]]:
    json_media = [
        (content_type, media)
        for content_type, media in content.items()
        if content_type == "application/json"
    ]
    if len(json_media) != 1 or not isinstance(json_media[0][1], dict):
        raise PolicyContractError(
            f"{label} {subject} must define application/json content"
        )
    return json_media[0]


def _parameter_sort_key(parameter: dict[str, Any]) -> tuple[str, str]:
    return parameter["in"], parameter["name"]


def _schema_signature(
    spec: dict[str, Any],
    schema: dict[str, Any],
    seen_refs: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    ref = schema.get("$ref")
    if ref is not None:
        if not isinstance(ref, str) or not ref.startswith("#/components/schemas/"):
            raise PolicyContractError(
                "schema references must be local component schemas"
            )
        if ref in seen_refs:
            return {"$ref": ref, "recursive": True}
        target = _resolve_schema_ref(spec, ref)
        return {
            "$ref": ref,
            "schema": _schema_signature(spec, target, seen_refs | {ref}),
        }

    signature = {}
    for key in (
        "type",
        "format",
        "enum",
        "const",
        "required",
        "pattern",
        "minLength",
        "maxLength",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minItems",
        "maxItems",
        "uniqueItems",
        "minProperties",
        "maxProperties",
    ):
        if key in schema:
            signature[key] = schema[key]
    if "properties" in schema:
        properties = schema["properties"]
        if not isinstance(properties, dict):
            raise PolicyContractError("schema properties must be an object")
        signature["properties"] = {
            name: _schema_signature(spec, value, seen_refs)
            for name, value in sorted(properties.items())
            if isinstance(name, str) and isinstance(value, dict)
        }
        if len(signature["properties"]) != len(properties):
            raise PolicyContractError("schema properties must map strings to schemas")
    if "items" in schema:
        items = schema["items"]
        if not isinstance(items, dict):
            raise PolicyContractError("schema items must be a schema")
        signature["items"] = _schema_signature(spec, items, seen_refs)
    for key in ("allOf", "anyOf", "oneOf"):
        if key in schema:
            branches = schema[key]
            if not isinstance(branches, list) or not all(
                isinstance(branch, dict) for branch in branches
            ):
                raise PolicyContractError(f"schema {key} must be an array of schemas")
            signature[key] = [
                _schema_signature(spec, branch, seen_refs) for branch in branches
            ]
    if "additionalProperties" in schema:
        additional_properties = schema["additionalProperties"]
        if isinstance(additional_properties, bool):
            signature["additionalProperties"] = additional_properties
        elif isinstance(additional_properties, dict):
            signature["additionalProperties"] = _schema_signature(
                spec, additional_properties, seen_refs
            )
        else:
            raise PolicyContractError(
                "schema additionalProperties must be a boolean or schema"
            )
    return signature


def _resolve_schema_ref(spec: dict[str, Any], ref: str) -> dict[str, Any]:
    schema_name = ref.removeprefix("#/components/schemas/")
    components = spec.get("components")
    schemas = components.get("schemas") if isinstance(components, dict) else None
    target = schemas.get(schema_name) if isinstance(schemas, dict) else None
    if not isinstance(target, dict):
        raise PolicyContractError(f"schema reference does not exist: {ref}")
    return target


def _validate_policy(
    path: str, method: str, operation: dict[str, Any], policy: dict[str, Any]
) -> None:
    label = f"OpenAPI operation {method.upper()} {path}"
    missing = _REQUIRED_POLICY_FIELDS - policy.keys()
    if missing:
        raise PolicyContractError(
            f"{label} policy is missing fields: {sorted(missing)}"
        )

    exposure = policy["exposure"]
    if exposure not in _ALLOWED_EXPOSURES:
        raise PolicyContractError(f"{label} has invalid exposure")

    operation_id = operation.get("operationId")
    if not isinstance(operation_id, str) or not operation_id:
        raise PolicyContractError(f"{label} must define operationId")
    if policy["operationId"] != operation_id:
        raise PolicyContractError(f"{label} policy operationId must match operationId")
    if len(operation_id) > 64:
        raise PolicyContractError(f"{label} operationId exceeds 64 characters")

    for field in ("title", "triggerDescription"):
        if not isinstance(policy[field], str) or not policy[field]:
            raise PolicyContractError(
                f"{label} policy {field} must be a non-empty string"
            )
    for field in (
        "readOnlyHint",
        "destructiveHint",
        "idempotentHint",
        "openWorldHint",
    ):
        if type(policy[field]) is not bool:
            raise PolicyContractError(f"{label} policy {field} must be a boolean")

    scopes = policy["requiredScopes"]
    if (
        not isinstance(scopes, list)
        or not scopes
        or any(not isinstance(scope, str) or not scope for scope in scopes)
    ):
        raise PolicyContractError(
            f"{label} policy requiredScopes must be non-empty strings"
        )
    if policy["retrySemantics"] not in _ALLOWED_RETRY_SEMANTICS:
        raise PolicyContractError(f"{label} has invalid retrySemantics")
    for field in ("inputSensitivity", "outputSensitivity"):
        if policy[field] not in _ALLOWED_SENSITIVITIES:
            raise PolicyContractError(f"{label} has invalid {field}")

    bodiless_success = policy.get("bodilessSuccess", False)
    if type(bodiless_success) is not bool:
        raise PolicyContractError(f"{label} policy bodilessSuccess must be a boolean")

    if exposure == "excluded":
        for field in ("exclusionReason", "remediation"):
            if not isinstance(policy.get(field), str) or not policy[field]:
                raise PolicyContractError(
                    f"{label} excluded policy must define {field}"
                )
    elif "restricted-credentials" in {
        policy["inputSensitivity"],
        policy["outputSensitivity"],
    }:
        raise PolicyContractError(
            f"{label} cannot expose restricted credential input or output"
        )


def _validate_unique_tool_names(tools: list[ToolContract]) -> None:
    names = [tool.name for tool in tools]
    if len(names) != len(set(names)):
        raise PolicyContractError("Exposed MCP operationIds must be unique")


def _canonical_sha256(value: Any) -> str:
    canonical_value = json.dumps(value, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical_value.encode()).hexdigest()


def _canonical(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _canonical(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_canonical(item) for item in value]
    return value


def validate_policy_snapshot(
    release_tag: str,
    policy_sha256: str,
    contract: PolicyContract,
    snapshot: dict[str, Any],
) -> None:
    expected_tools = {
        tool["name"]: tool
        for tool in snapshot_policy_contract(release_tag, policy_sha256, contract)[
            "tools"
        ]
    }
    if snapshot.get("formatVersion") not in {2, 3}:
        raise PolicyContractError("policy snapshot has an unsupported format version")
    actual_tools = snapshot.get("tools")
    if not isinstance(actual_tools, list):
        raise PolicyContractError("policy contract snapshot tools must be an array")
    for tool in actual_tools:
        if not isinstance(tool, dict):
            raise PolicyContractError("policy contract snapshot tool must be an object")
        expected_tool = expected_tools.get(tool.get("name"))
        if expected_tool is None:
            raise PolicyContractError(
                "policy contract snapshot includes an unknown tool"
            )
        if any(tool.get(key) != value for key, value in expected_tool.items()):
            raise PolicyContractError(
                "policy contract snapshot does not match the local policy bundle"
            )
        if snapshot["formatVersion"] == 3 and (
            not isinstance(tool.get("inputSchema"), dict)
            or not isinstance(tool.get("outputSchema"), dict)
        ):
            raise PolicyContractError(
                "policy contract snapshot is missing runtime tool schemas"
            )
    if len(actual_tools) != len(expected_tools):
        raise PolicyContractError("policy contract snapshot is missing a policy tool")


def snapshot_policy_contract(
    release_tag: str, policy_sha256: str, contract: PolicyContract
) -> dict[str, Any]:
    return {
        "formatVersion": 2,
        "policySHA256": policy_sha256,
        "releaseTag": release_tag,
        "tools": [
            {
                "annotations": dict(sorted(tool.annotations.items())),
                "bodilessSuccess": tool.bodiless_success,
                "inputSensitivity": tool.input_sensitivity,
                "method": tool.method,
                "name": tool.name,
                "outputSensitivity": tool.output_sensitivity,
                "path": tool.path,
                "requestSchemaSHA256": _canonical_sha256(tool.request),
                "requiredScopes": list(tool.required_scopes),
                "retrySemantics": tool.retry_semantics,
                "successSchemaSHA256": _canonical_sha256(tool.success),
                "title": tool.title,
                "triggerDescription": tool.trigger_description,
            }
            for tool in contract.tools
        ],
    }
