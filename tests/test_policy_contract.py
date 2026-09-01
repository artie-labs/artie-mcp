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

    def test_compile_policy_rejects_exposed_connector_create_credentials(self):
        spec = {
            "openapi": "3.1.0",
            "paths": {
                "/connectors": {
                    "post": {
                        "operationId": "connector_create",
                        "responses": {"200": {"description": "OK"}},
                        "x-artie-mcp": {
                            "exposure": "exposed",
                            "operationId": "connector_create",
                            "title": "Create a connector",
                            "triggerDescription": "Creates a saved connector.",
                            "readOnlyHint": False,
                            "destructiveHint": False,
                            "idempotentHint": False,
                            "openWorldHint": False,
                            "requiredScopes": ["connectors:write"],
                            "retrySemantics": "unsafe",
                            "inputSensitivity": "restricted-credentials",
                            "outputSensitivity": "restricted-credentials",
                        },
                    }
                }
            },
        }

        with self.assertRaisesRegex(
            PolicyContractError,
            "cannot expose restricted credential input or output",
        ):
            compile_policy(spec)

    def test_compile_policy_allowlists_unsaved_connector_ping_credentials(self):
        spec = {
            "openapi": "3.1.0",
            "paths": {
                "/connectors/ping": {
                    "post": {
                        "operationId": "unsaved_connector_ping",
                        "responses": {"204": {"description": "No Content"}},
                        "x-artie-mcp": {
                            "exposure": "exposed",
                            "operationId": "unsaved_connector_ping",
                            "title": "Ping a connector",
                            "triggerDescription": "Pings unsaved credentials.",
                            "readOnlyHint": True,
                            "destructiveHint": False,
                            "idempotentHint": True,
                            "openWorldHint": True,
                            "requiredScopes": ["connectors:read"],
                            "retrySemantics": "safe",
                            "inputSensitivity": "restricted-credentials",
                            "outputSensitivity": "none",
                            "bodilessSuccess": True,
                        },
                    }
                }
            },
        }

        contract = compile_policy(spec)

        self.assertEqual(
            ["unsaved_connector_ping"], [tool.name for tool in contract.tools]
        )
        self.assertEqual("restricted-credentials", contract.tools[0].input_sensitivity)
        self.assertTrue(contract.tools[0].bodiless_success)

    def test_compile_policy_allowlists_connector_detail_credentials(self):
        spec = {
            "openapi": "3.1.0",
            "paths": {
                "/connectors/{uuid}": {
                    "get": {
                        "operationId": "connector_detail",
                        "responses": {"200": {"description": "OK"}},
                        "x-artie-mcp": {
                            "exposure": "exposed",
                            "operationId": "connector_detail",
                            "title": "Get a saved connector",
                            "triggerDescription": "Returns a saved connector.",
                            "readOnlyHint": True,
                            "destructiveHint": False,
                            "idempotentHint": True,
                            "openWorldHint": False,
                            "requiredScopes": ["connectors:read"],
                            "retrySemantics": "safe",
                            "inputSensitivity": "none",
                            "outputSensitivity": "restricted-credentials",
                        },
                    }
                }
            },
        }

        contract = compile_policy(spec)

        self.assertEqual(["connector_detail"], [tool.name for tool in contract.tools])
        self.assertEqual("restricted-credentials", contract.tools[0].output_sensitivity)

    def test_compile_policy_rejects_other_exposed_credential_tools(self):
        spec = {
            "openapi": "3.1.0",
            "paths": {
                "/connectors/ping": {
                    "post": {
                        "operationId": "unsaved_connector_fetch_databases",
                        "responses": {"200": {"description": "OK"}},
                        "x-artie-mcp": {
                            "exposure": "exposed",
                            "operationId": "unsaved_connector_fetch_databases",
                            "title": "Fetch databases for an unsaved connector",
                            "triggerDescription": "Lists databases using unsaved credentials.",
                            "readOnlyHint": True,
                            "destructiveHint": False,
                            "idempotentHint": True,
                            "openWorldHint": False,
                            "requiredScopes": ["connectors:read"],
                            "retrySemantics": "safe",
                            "inputSensitivity": "restricted-credentials",
                            "outputSensitivity": "none",
                        },
                    }
                }
            },
        }

        with self.assertRaisesRegex(
            PolicyContractError,
            "cannot expose restricted credential input or output",
        ):
            compile_policy(spec)

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
                "formatVersion": 2,
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
                        "bodilessSuccess": False,
                        "inputSensitivity": "none",
                        "method": "get",
                        "name": "safe_list",
                        "outputSensitivity": "none",
                        "path": "/safe",
                        "requestSchemaSHA256": "c7c69ffea7e3e6af99994c9347a2f29c4a558bdf8854ac3b61df817cbadcd1f7",
                        "requiredScopes": ["safe:read"],
                        "retrySemantics": "safe",
                        "successSchemaSHA256": "174790542fd664f6413274045a98e94a7fa8b783dda6a2edcfde53aa196eb10a",
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

        contract = compile_policy(spec)
        tool = contract.tools[0]

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
            tool.request,
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
            list(tool.success),
        )

    @staticmethod
    def _bodiless_success_spec(responses):
        return {
            "paths": {
                "/items": {
                    "delete": {
                        "operationId": "item_delete",
                        "responses": responses,
                        "x-artie-mcp": {
                            "exposure": "exposed",
                            "operationId": "item_delete",
                            "title": "Delete item",
                            "triggerDescription": "Use when deleting an item.",
                            "readOnlyHint": False,
                            "destructiveHint": True,
                            "idempotentHint": False,
                            "openWorldHint": False,
                            "requiredScopes": ["items:write"],
                            "retrySemantics": "unsafe",
                            "inputSensitivity": "none",
                            "outputSensitivity": "none",
                            "bodilessSuccess": True,
                        },
                    }
                }
            }
        }

    def test_compile_policy_accepts_bodiless_success_for_a_bodiless_202(self):
        spec = self._bodiless_success_spec({"202": {"description": "Accepted"}})

        tool = compile_policy(spec).tools[0]

        self.assertTrue(tool.bodiless_success)
        self.assertEqual(({"status": "202"},), tool.success)

    def test_compile_policy_rejects_bodiless_success_on_a_body_bearing_status(self):
        spec = self._bodiless_success_spec({"200": {"description": "OK"}})

        with self.assertRaisesRegex(PolicyContractError, "bodilessSuccess"):
            compile_policy(spec)

    def test_compile_policy_rejects_bodiless_success_alongside_a_body_success(self):
        # A tool that sometimes returns a body cannot be described by one flag:
        # shape_response would have to decide per response, not per tool.
        spec = self._bodiless_success_spec(
            {
                "200": {
                    "description": "OK",
                    "content": {
                        "application/json": {"schema": {"type": "object"}},
                    },
                },
                "204": {"description": "No Content"},
            }
        )

        with self.assertRaisesRegex(PolicyContractError, "bodilessSuccess"):
            compile_policy(spec)


if __name__ == "__main__":
    unittest.main()
