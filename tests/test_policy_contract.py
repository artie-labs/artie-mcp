import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from policy_contract import (
    PolicyContractError,
    compile_policy,
    load_policy_bundle,
    snapshot_policy_contract,
)


class TestPolicyContract(unittest.TestCase):
    def test_compile_policy_includes_only_exposed_operations(self):
        spec = {
            "openapi": "3.1.0",
            "paths": {
                "/safe": {
                    "get": {
                        "operationId": "safe_list",
                        "responses": {"200": {"description": "OK"}},
                        "x-artie-mcp": {
                            "exposure": "exposed",
                            "operationId": "safe_list",
                            "title": "List safe resources",
                            "triggerDescription": "Use when listing safe resources.",
                            "readOnlyHint": True,
                            "destructiveHint": False,
                            "idempotentHint": True,
                            "openWorldHint": False,
                            "requiredScopes": ["safe:read"],
                            "retrySemantics": "safe",
                            "inputSensitivity": "none",
                            "outputSensitivity": "none",
                        },
                    }
                },
                "/secret": {
                    "post": {
                        "operationId": "secret_create",
                        "responses": {"200": {"description": "OK"}},
                        "x-artie-mcp": {
                            "exposure": "excluded",
                            "operationId": "secret_create",
                            "title": "Create a secret",
                            "triggerDescription": "Use when creating a secret.",
                            "readOnlyHint": False,
                            "destructiveHint": False,
                            "idempotentHint": False,
                            "openWorldHint": False,
                            "requiredScopes": ["safe:write"],
                            "retrySemantics": "unsafe",
                            "inputSensitivity": "restricted-credentials",
                            "outputSensitivity": "restricted-credentials",
                            "exclusionReason": "Returns a secret.",
                            "remediation": "Use the Dashboard.",
                        },
                    }
                },
            },
        }

        contract = compile_policy(spec)

        self.assertEqual(["safe_list"], [tool.name for tool in contract.tools])
        self.assertEqual("List safe resources", contract.tools[0].title)
        self.assertEqual(("safe:read",), contract.tools[0].required_scopes)

    def test_load_policy_bundle_rejects_checksum_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle_dir = Path(directory)
            policy_path = bundle_dir / "policy.openapi.yaml"
            policy_path.write_text("openapi: 3.1.0\npaths: {}\n")
            (bundle_dir / "policy.lock.json").write_text(
                json.dumps(
                    {
                        "formatVersion": 1,
                        "policySHA256": "0" * 64,
                        "release": {"tag": "v1.0.56", "asset": "openapi.yaml"},
                    }
                )
            )

            with self.assertRaisesRegex(PolicyContractError, "checksum"):
                load_policy_bundle(bundle_dir)

    def test_load_policy_bundle_returns_verified_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle_dir = Path(directory)
            policy_text = "openapi: 3.1.0\ninfo:\n  version: v1.0.56\npaths: {}\n"
            (bundle_dir / "policy.openapi.yaml").write_text(policy_text)
            (bundle_dir / "policy.lock.json").write_text(
                json.dumps(
                    {
                        "formatVersion": 1,
                        "policySHA256": hashlib.sha256(
                            policy_text.encode()
                        ).hexdigest(),
                        "release": {"tag": "v1.0.56", "asset": "openapi.yaml"},
                    }
                )
            )

            bundle = load_policy_bundle(bundle_dir)

        self.assertEqual("v1.0.56", bundle.release_tag)
        self.assertEqual({}, bundle.spec["paths"])

    def test_load_policy_bundle_rejects_release_version_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle_dir = Path(directory)
            policy_text = "openapi: 3.1.0\ninfo:\n  version: v1.0.55\npaths: {}\n"
            (bundle_dir / "policy.openapi.yaml").write_text(policy_text)
            (bundle_dir / "policy.lock.json").write_text(
                json.dumps(
                    {
                        "formatVersion": 1,
                        "policySHA256": hashlib.sha256(
                            policy_text.encode()
                        ).hexdigest(),
                        "release": {"tag": "v1.0.56", "asset": "openapi.yaml"},
                    }
                )
            )

            with self.assertRaisesRegex(PolicyContractError, "release tag"):
                load_policy_bundle(bundle_dir)

    def test_local_bundle_compiles_to_the_committed_snapshot(self):
        repository_root = Path(__file__).resolve().parents[1]
        bundle_dir = repository_root / "contract"
        bundle = load_policy_bundle(bundle_dir)
        policy_sha256 = hashlib.sha256(
            (bundle_dir / "policy.openapi.yaml").read_bytes()
        ).hexdigest()

        actual = snapshot_policy_contract(
            bundle.release_tag, policy_sha256, compile_policy(bundle.spec)
        )
        expected = json.loads((bundle_dir / "policy.contract.json").read_text())

        self.assertEqual("v1.0.56", bundle.release_tag)
        self.assertEqual(34, len(actual["tools"]))
        self.assertEqual(expected, actual)

    def test_policy_contract_verifier_checks_the_local_bundle_and_snapshot(self):
        repository_root = Path(__file__).resolve().parents[1]

        result = subprocess.run(
            [sys.executable, "-m", "scripts.verify_policy_contract"],
            cwd=repository_root,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("verified policy contract", result.stdout)

    def test_snapshot_is_canonical_and_includes_only_exposed_tools(self):
        contract = compile_policy(
            {
                "paths": {
                    "/safe": {
                        "get": {
                            "operationId": "safe_list",
                            "responses": {"200": {"description": "OK"}},
                            "x-artie-mcp": {
                                "exposure": "exposed",
                                "operationId": "safe_list",
                                "title": "List safe resources",
                                "triggerDescription": "Use when listing safe resources.",
                                "readOnlyHint": True,
                                "destructiveHint": False,
                                "idempotentHint": True,
                                "openWorldHint": False,
                                "requiredScopes": ["safe:read"],
                                "retrySemantics": "safe",
                                "inputSensitivity": "none",
                                "outputSensitivity": "none",
                            },
                        }
                    }
                }
            }
        )

        snapshot = snapshot_policy_contract("v1.0.56", "a" * 64, contract)

        self.assertEqual(
            {
                "formatVersion": 1,
                "policySHA256": "a" * 64,
                "releaseTag": "v1.0.56",
                "tools": [
                    {
                        "annotations": {
                            "destructiveHint": False,
                            "idempotentHint": True,
                            "openWorldHint": False,
                            "readOnlyHint": True,
                        },
                        "inputSensitivity": "none",
                        "name": "safe_list",
                        "outputSensitivity": "none",
                        "request": {"parameters": []},
                        "requiredScopes": ["safe:read"],
                        "retrySemantics": "safe",
                        "success": [{"status": "200"}],
                        "title": "List safe resources",
                        "triggerDescription": "Use when listing safe resources.",
                    }
                ],
            },
            snapshot,
        )

    def test_compile_policy_builds_request_and_success_schema_plans(self):
        spec = {
            "components": {
                "schemas": {
                    "Item": {
                        "type": "object",
                        "required": ["name"],
                        "properties": {"name": {"type": "string"}},
                    }
                }
            },
            "paths": {
                "/items/{uuid}": {
                    "post": {
                        "operationId": "item_update",
                        "parameters": [
                            {
                                "in": "path",
                                "name": "uuid",
                                "required": True,
                                "schema": {"type": "string"},
                            }
                        ],
                        "requestBody": {
                            "required": True,
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "array",
                                        "minItems": 1,
                                        "items": {"$ref": "#/components/schemas/Item"},
                                    }
                                }
                            },
                        },
                        "responses": {
                            "200": {
                                "description": "OK",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "oneOf": [
                                                {"$ref": "#/components/schemas/Item"},
                                                {"type": "null"},
                                            ]
                                        }
                                    }
                                },
                            }
                        },
                        "x-artie-mcp": {
                            "exposure": "exposed",
                            "operationId": "item_update",
                            "title": "Update item",
                            "triggerDescription": "Use when updating an item.",
                            "readOnlyHint": False,
                            "destructiveHint": False,
                            "idempotentHint": True,
                            "openWorldHint": False,
                            "requiredScopes": ["items:write"],
                            "retrySemantics": "safe",
                            "inputSensitivity": "none",
                            "outputSensitivity": "none",
                        },
                    }
                }
            },
        }

        snapshot = snapshot_policy_contract("v1.0.56", "a" * 64, compile_policy(spec))

        self.assertEqual(
            {
                "body": {
                    "contentType": "application/json",
                    "required": True,
                    "schema": {
                        "items": {
                            "$ref": "#/components/schemas/Item",
                            "schema": {
                                "properties": {"name": {"type": "string"}},
                                "required": ["name"],
                                "type": "object",
                            },
                        },
                        "minItems": 1,
                        "type": "array",
                    },
                },
                "parameters": [
                    {
                        "in": "path",
                        "name": "uuid",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ],
            },
            snapshot["tools"][0]["request"],
        )
        self.assertEqual(
            [
                {
                    "contentType": "application/json",
                    "schema": {
                        "oneOf": [
                            {
                                "$ref": "#/components/schemas/Item",
                                "schema": {
                                    "properties": {"name": {"type": "string"}},
                                    "required": ["name"],
                                    "type": "object",
                                },
                            },
                            {"type": "null"},
                        ]
                    },
                    "status": "200",
                }
            ],
            snapshot["tools"][0]["success"],
        )


if __name__ == "__main__":
    unittest.main()
