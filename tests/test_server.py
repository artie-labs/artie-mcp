import asyncio
import base64
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
        self.assertEqual("https://example.ngrok.app", str(authkit.base_url).rstrip("/"))
        authkit.set_mcp_path("/mcp")
        self.assertEqual(
            "https://example.ngrok.app/mcp", str(authkit._resource_url).rstrip("/")
        )
        self.assertEqual("Artie MCP", authkit.resource_name)

    def test_api_key_verifier_rejects_jwt_shaped_tokens(self):
        with patch.dict(
            "os.environ",
            {
                "WORKOS_AUTHKIT_DOMAIN": "https://example.authkit.app",
                "MCP_PUBLIC_BASE_URL": "https://example.ngrok.app",
            },
            clear=True,
        ):
            provider = self.server._build_auth_provider()

        api_key_verifier = provider.verifiers[0]
        self.assertIsNone(asyncio.run(api_key_verifier.verify_token("aaa.bbb.ccc")))
        accepted = asyncio.run(api_key_verifier.verify_token("arsk_test_key"))
        self.assertIsNotNone(accepted)
        self.assertEqual("arsk_test_key", accepted.token)

    def test_is_jwt_detects_three_segment_tokens(self):
        self.assertTrue(self.server._is_jwt("aaa.bbb.ccc"))
        self.assertFalse(self.server._is_jwt("artie-api-key"))
        self.assertFalse(self.server._is_jwt("aaa.bbb"))
        self.assertFalse(self.server._is_jwt("aaa..ccc"))
        self.assertFalse(self.server._is_jwt(""))

    def test_device_link_auth_forwards_opaque_api_keys(self):
        auth = self.server._DeviceLinkAuth()
        request = httpx.Request("GET", "https://api.artie.com/pipelines")

        with (
            patch.object(auth, "_credential") as credential,
            patch.object(self.server, "get_access_token", return_value=None),
            patch.object(
                self.server,
                "get_http_headers",
                return_value={"authorization": "Bearer artie-api-key"},
            ),
        ):
            requests = asyncio.run(_collect_auth_requests(auth, request))

        credential.assert_not_called()
        self.assertEqual("Bearer artie-api-key", requests[0].headers["Authorization"])

    def test_device_link_auth_prefers_access_token_over_headers(self):
        auth = self.server._DeviceLinkAuth()
        request = httpx.Request("GET", "https://api.artie.com/pipelines")
        access = unittest.mock.Mock(token="artie-from-access-token")

        with (
            patch.object(auth, "_credential") as credential,
            patch.object(self.server, "get_access_token", return_value=access),
            patch.object(
                self.server,
                "get_http_headers",
                return_value={"authorization": "Bearer ignored-header"},
            ),
        ):
            requests = asyncio.run(_collect_auth_requests(auth, request))

        credential.assert_not_called()
        self.assertEqual(
            "Bearer artie-from-access-token", requests[0].headers["Authorization"]
        )

    def test_device_link_auth_resolves_jwt_via_device_link(self):
        auth = self.server._DeviceLinkAuth()
        request = httpx.Request("GET", "https://api.artie.com/pipelines")
        jwt = "aaa.bbb.ccc"

        async def credential(_token: str) -> str:
            return "linked-artie-token"

        with (
            patch.object(
                auth, "_credential", side_effect=credential
            ) as credential_mock,
            patch.object(self.server, "get_access_token", return_value=None),
            patch.object(
                self.server,
                "get_http_headers",
                return_value={"authorization": f"Bearer {jwt}"},
            ),
        ):
            requests = asyncio.run(_collect_auth_requests(auth, request))

        credential_mock.assert_awaited_once_with(jwt)
        self.assertEqual(
            "Bearer linked-artie-token", requests[0].headers["Authorization"]
        )

    def test_credential_raises_authorization_required_for_new_subject(self):
        auth = self.server._DeviceLinkAuth()
        pending = self.server._PendingLink(
            device_code="amdc_devicecode",
            user_code="K7QM-3PXR",
            verification_uri="https://dash.artie.com/mcp/link",
        )

        async def device_authorize(_token: str):
            return pending

        with patch.object(
            auth, "_device_authorize", side_effect=device_authorize
        ) as device_authorize_mock:
            with self.assertRaises(RuntimeError) as ctx:
                asyncio.run(auth._credential(_encode_jwt({"sub": "acct-123"})))

        device_authorize_mock.assert_awaited_once()
        self.assertIn("K7QM-3PXR", str(ctx.exception))
        self.assertIn("https://dash.artie.com/mcp/link", str(ctx.exception))

    def test_credential_redeems_approved_device_code(self):
        auth = self.server._DeviceLinkAuth()
        token = _encode_jwt({"sub": "acct-123"})
        auth._pending["acct-123"] = self.server._PendingLink(
            device_code="amdc_devicecode",
            user_code="K7QM-3PXR",
            verification_uri="https://dash.artie.com/mcp/link",
        )

        async def poll(_device_code: str):
            return "ok", {"access_token": "amcp_credential", "expires_in": 600}

        with patch.object(auth, "_poll", side_effect=poll):
            credential = asyncio.run(auth._credential(token))

        self.assertEqual("amcp_credential", credential)
        # A cached credential is reused without polling again.
        self.assertEqual("amcp_credential", asyncio.run(auth._credential(token)))

    def test_credential_reports_pending_authorization(self):
        auth = self.server._DeviceLinkAuth()
        token = _encode_jwt({"sub": "acct-123"})
        auth._pending["acct-123"] = self.server._PendingLink(
            device_code="amdc_devicecode",
            user_code="K7QM-3PXR",
            verification_uri="https://dash.artie.com/mcp/link",
        )

        async def poll(_device_code: str):
            return "pending", {"error": "authorization_pending"}

        with patch.object(auth, "_poll", side_effect=poll):
            with self.assertRaises(RuntimeError) as ctx:
                asyncio.run(auth._credential(token))

        self.assertIn("K7QM-3PXR", str(ctx.exception))

    def test_poll_treats_slow_down_as_pending_authorization(self):
        auth = self.server._DeviceLinkAuth()
        response = httpx.Response(
            400,
            json={"error": "slow_down"},
            request=httpx.Request("POST", self.server._ARTIE_TOKEN_EXCHANGE_URL),
        )

        async def post(*_args, **_kwargs):
            return response

        with patch.object(auth._client, "post", side_effect=post):
            status, payload = asyncio.run(auth._poll("amdc_devicecode"))

        self.assertEqual("pending", status)
        self.assertEqual({"error": "slow_down"}, payload)

    def test_jwt_subject_decodes_sub_claim(self):
        self.assertEqual(
            "acct-123", self.server._jwt_subject(_encode_jwt({"sub": "acct-123"}))
        )
        # Undecodable tokens fall back to the raw value so caching still works.
        self.assertEqual("opaque", self.server._jwt_subject("opaque"))


async def _collect_auth_requests(auth, request):
    return [req async for req in auth.async_auth_flow(request)]


def _encode_jwt(claims: dict) -> str:
    """Build a JWT-shaped token whose payload segment carries the given claims."""
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=")
    return f"aaa.{payload.decode()}.ccc"


if __name__ == "__main__":
    unittest.main()
