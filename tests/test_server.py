import asyncio
import importlib
import json
import sys
import unittest
from unittest.mock import patch

import httpx


class TestServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._previous_server = sys.modules.pop("server", None)
        cls.server = importlib.import_module("server")
        cls.tools = asyncio.run(cls.server.mcp.list_tools())

    @classmethod
    def tearDownClass(cls):
        sys.modules.pop("server", None)
        if cls._previous_server is not None:
            sys.modules["server"] = cls._previous_server

    def test_server_publishes_exactly_the_policy_tools(self):
        self.assertEqual(
            {tool.name for tool in self.server.policy_contract.tools},
            {tool.name for tool in self.tools},
        )
        self.assertNotIn("unsaved_connector_ping", [tool.name for tool in self.tools])
        self.assertNotIn("Ping_a_connector", [tool.name for tool in self.tools])

    def test_generated_tools_use_policy_metadata(self):
        contracts = {tool.name: tool for tool in self.server.policy_contract.tools}
        for tool in self.tools:
            with self.subTest(tool=tool.name):
                contract = contracts[tool.name]
                self.assertEqual(contract.title, tool.title)
                self.assertEqual(contract.trigger_description, tool.description)
                self.assertEqual(
                    contract.annotations,
                    tool.annotations.model_dump(exclude_none=True),
                )

    def test_bodiless_policy_tools_publish_a_success_schema(self):
        tools = {tool.name: tool for tool in self.tools}
        for contract in self.server.policy_contract.tools:
            if contract.bodiless_success:
                with self.subTest(tool=contract.name):
                    self.assertEqual(
                        {
                            "type": "object",
                            "properties": {"success": {"const": True}},
                            "required": ["success"],
                            "additionalProperties": False,
                        },
                        tools[contract.name].output_schema,
                    )

    def test_failed_upstream_response_is_replaced_before_fastmcp_formats_it(self):
        response = httpx.Response(
            500,
            content=b'{"sharedConfig":{"password":"secret"}}',
            headers={"content-type": "application/json"},
            request=httpx.Request("GET", "https://api.artie.com/column-hashing-salts"),
        )

        asyncio.run(self.server._shape_policy_response(response))

        self.assertEqual({"error": "upstream request failed"}, response.json())

    def test_server_configures_json_observability_logging(self):
        self.assertTrue(self.server.logger.isEnabledFor(20))
        self.assertFalse(self.server.logger.propagate)
        self.assertTrue(
            any(
                handler.name == "artie-mcp-json"
                and handler.formatter._fmt == "%(message)s"
                for handler in self.server.logger.handlers
            )
        )

    def test_server_card_describes_the_authenticated_streamable_http_endpoint(self):
        response = self.server._server_card_response()

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            "application/mcp-server-card+json", response.headers["content-type"]
        )
        self.assertEqual("*", response.headers["access-control-allow-origin"])
        self.assertEqual("com.artie/mcp", json.loads(response.body)["name"])

    def test_authkit_provider_requires_both_settings(self):
        with patch.dict(
            "os.environ",
            {"WORKOS_AUTHKIT_DOMAIN": "https://example.authkit.app"},
            clear=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "must be set together"):
                self.server._build_auth_provider()

    def test_no_authkit_config_uses_api_key_only_verifier(self):
        with patch.dict("os.environ", {}, clear=True):
            provider = self.server._build_auth_provider()

        self.assertIsInstance(provider, self.server.DebugTokenVerifier)

    def test_authkit_provider_uses_public_mcp_resource_url(self):
        with patch.dict(
            "os.environ",
            {
                "WORKOS_AUTHKIT_DOMAIN": "https://example.authkit.app",
                "MCP_PUBLIC_BASE_URL": "https://example.ngrok.app/",
            },
            clear=True,
        ):
            provider = self.server._build_auth_provider()

        self.assertIsInstance(provider, self.server.MultiAuth)
        self.assertIsInstance(provider.server, self.server.AuthKitProvider)
        self.assertEqual(1, len(provider.verifiers))
        self.assertIsInstance(provider.verifiers[0], self.server.DebugTokenVerifier)

        authkit = provider.server
        self.assertEqual("https://example.authkit.app", authkit.authkit_domain)
        self.assertEqual(
            "https://example.ngrok.app", str(authkit.base_url).rstrip("/")
        )
        authkit.set_mcp_path("/mcp")
        self.assertEqual(
            "https://example.ngrok.app/mcp", str(authkit._resource_url).rstrip("/")
        )
        self.assertEqual("Artie MCP", authkit.resource_name)

    def test_is_jwt_detects_three_segment_tokens(self):
        self.assertTrue(self.server._is_jwt("aaa.bbb.ccc"))
        self.assertFalse(self.server._is_jwt("artie-api-key"))
        self.assertFalse(self.server._is_jwt("aaa.bbb"))
        self.assertFalse(self.server._is_jwt("aaa..ccc"))
        self.assertFalse(self.server._is_jwt(""))

    def test_token_exchange_auth_forwards_opaque_api_keys(self):
        auth = self.server._TokenExchangeAuth()
        request = httpx.Request("GET", "https://api.artie.com/pipelines")

        with (
            patch.object(auth, "_exchange") as exchange,
            patch.object(
                self.server,
                "get_http_headers",
                return_value={"authorization": "Bearer artie-api-key"},
            ),
        ):
            requests = asyncio.run(_collect_auth_requests(auth, request))

        exchange.assert_not_called()
        self.assertEqual("Bearer artie-api-key", requests[0].headers["Authorization"])

    def test_token_exchange_auth_exchanges_jwt_shaped_tokens(self):
        auth = self.server._TokenExchangeAuth()
        request = httpx.Request("GET", "https://api.artie.com/pipelines")
        jwt = "aaa.bbb.ccc"

        async def exchange(_token: str) -> str:
            return "exchanged-artie-token"

        with (
            patch.object(auth, "_exchange", side_effect=exchange) as exchange_mock,
            patch.object(
                self.server,
                "get_http_headers",
                return_value={"authorization": f"Bearer {jwt}"},
            ),
        ):
            requests = asyncio.run(_collect_auth_requests(auth, request))

        exchange_mock.assert_awaited_once_with(jwt)
        self.assertEqual(
            "Bearer exchanged-artie-token", requests[0].headers["Authorization"]
        )


async def _collect_auth_requests(auth, request):
    return [req async for req in auth.async_auth_flow(request)]


if __name__ == "__main__":
    unittest.main()
