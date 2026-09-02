import asyncio
import base64
import importlib
import json
import sys
import time
import unittest
from unittest.mock import AsyncMock, patch

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
        names = [tool.name for tool in self.tools]
        self.assertEqual(
            {tool.name for tool in self.server.policy_contract.tools},
            set(names),
        )
        self.assertIn("unsaved_connector_ping", names)
        self.assertIn("connector_create", names)
        self.assertIn("connector_detail", names)
        self.assertIn("pipeline_detail", names)
        self.assertIn("source_reader_detail", names)
        self.assertIn("source_reader_update", names)
        self.assertNotIn("Ping_a_connector", names)

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

    def test_upstream_client_error_message_is_passed_through(self):
        response = httpx.Response(
            400,
            content=b'{"error":"host is required","detail":{"password":"secret"}}',
            headers={"content-type": "application/json"},
            request=httpx.Request("POST", "https://api.artie.com/ssh-tunnels"),
        )

        asyncio.run(self.server._shape_policy_response(response))

        self.assertEqual({"error": "host is required"}, response.json())

    def test_upstream_error_log_records_the_message_without_sibling_fields(self):
        response = httpx.Response(
            400,
            content=b'{"error":"host is required","detail":{"password":"secret"}}',
            headers={"content-type": "application/json"},
            request=httpx.Request("POST", "https://api.artie.com/ssh-tunnels"),
        )

        with self.assertLogs(self.server.logger, level="WARNING") as logs:
            asyncio.run(self.server._shape_policy_response(response))

        record = json.loads(logs.records[0].getMessage())
        self.assertEqual("upstream_error", record["event"])
        self.assertEqual(400, record["status"])
        self.assertEqual("host is required", record["detail"])
        self.assertNotIn("secret", logs.output[0])

    def test_upstream_error_log_describes_an_unreadable_body_by_shape(self):
        response = httpx.Response(
            500,
            content=b"<html>secret internals</html>",
            headers={"content-type": "text/html; charset=utf-8"},
            request=httpx.Request("GET", "https://api.artie.com/column-hashing-salts"),
        )

        with self.assertLogs(self.server.logger, level="WARNING") as logs:
            asyncio.run(self.server._shape_policy_response(response))

        record = json.loads(logs.records[0].getMessage())
        self.assertEqual("<unparsed text/html body, 29 bytes>", record["detail"])
        self.assertNotIn("secret", logs.output[0])

    def test_upstream_client_error_without_a_message_stays_generic(self):
        response = httpx.Response(
            400,
            content=b"<html>bad request</html>",
            headers={"content-type": "text/html"},
            request=httpx.Request("POST", "https://api.artie.com/ssh-tunnels"),
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
        card = json.loads(response.body)

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            "application/mcp-server-card+json", response.headers["content-type"]
        )
        self.assertEqual("*", response.headers["access-control-allow-origin"])
        self.assertEqual("com.artie/mcp", card["name"])
        self.assertEqual(
            self.server.policy_release_tag.removeprefix("v"), card["version"]
        )
        # OAuth is primary: the card must not require a legacy API-key header.
        remote = card["remotes"][0]
        self.assertEqual("https://mcp.artie.com/mcp", remote["url"])
        self.assertNotIn("headers", remote)
        self.assertIn("OAuth", card["description"])

    def test_openai_domain_challenge_is_public_and_exact(self):
        async def get_challenge():
            transport = httpx.ASGITransport(app=self.server.app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                return await client.get("/.well-known/openai-apps-challenge")

        response = asyncio.run(get_challenge())

        self.assertEqual(200, response.status_code)
        self.assertEqual("text/plain; charset=utf-8", response.headers["content-type"])
        self.assertEqual(self.server._OPENAI_APPS_CHALLENGE_TOKEN, response.text)

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

    def test_credential_bootstraps_link_when_no_grant(self):
        auth = self.server._DeviceLinkAuth()
        pending = self.server._PendingLink(
            user_code="K7QM-3PXR",
            verification_uri="https://dash.artie.com/mcp/link",
        )

        async def exchange(_token: str):
            return "error", {"error": "authorization_required"}

        async def device_authorize(_token: str):
            return pending

        with (
            patch.object(auth, "_exchange", side_effect=exchange),
            patch.object(
                auth, "_device_authorize", side_effect=device_authorize
            ) as device_authorize_mock,
        ):
            with self.assertRaises(RuntimeError) as ctx:
                asyncio.run(auth._credential(_encode_jwt({"sub": "acct-123"})))

        device_authorize_mock.assert_awaited_once()
        self.assertIn("K7QM-3PXR", str(ctx.exception))
        self.assertIn("https://dash.artie.com/mcp/link", str(ctx.exception))

    def test_credential_exchanges_approved_grant(self):
        auth = self.server._DeviceLinkAuth()
        token = _encode_jwt({"sub": "acct-123"})

        async def exchange(_token: str):
            return "ok", {"access_token": "amcp_credential", "expires_in": 600}

        with patch.object(auth, "_exchange", side_effect=exchange) as exchange_mock:
            credential = asyncio.run(auth._credential(token))
            # A cached credential is reused without exchanging again.
            self.assertEqual("amcp_credential", asyncio.run(auth._credential(token)))

        self.assertEqual("amcp_credential", credential)
        exchange_mock.assert_awaited_once()

    def test_credential_reports_pending_with_user_code_from_response(self):
        auth = self.server._DeviceLinkAuth()
        token = _encode_jwt({"sub": "acct-123"})

        async def exchange(_token: str):
            return "pending", {
                "error": "authorization_pending",
                "user_code": "K7QM-3PXR",
                "verification_uri": "https://dash.artie.com/mcp/link",
            }

        # The user_code comes from the exchange response, so no separate device
        # authorization call is needed to surface it.
        with (
            patch.object(auth, "_exchange", side_effect=exchange),
            patch.object(auth, "_device_authorize") as device_authorize_mock,
        ):
            with self.assertRaises(RuntimeError) as ctx:
                asyncio.run(auth._credential(token))

        device_authorize_mock.assert_not_called()
        self.assertIn("K7QM-3PXR", str(ctx.exception))
        self.assertIn("https://dash.artie.com/mcp/link", str(ctx.exception))

    def test_exchange_returns_slow_down_status(self):
        auth = self.server._DeviceLinkAuth()
        response = httpx.Response(
            400,
            json={"error": "slow_down"},
            request=httpx.Request("POST", self.server._ARTIE_TOKEN_EXCHANGE_URL),
        )

        async def post(*_args, **_kwargs):
            return response

        with patch.object(auth._client, "post", side_effect=post):
            status, payload = asyncio.run(
                auth._exchange(_encode_jwt({"sub": "acct-123"}))
            )

        self.assertEqual("slow_down", status)
        self.assertEqual({"error": "slow_down"}, payload)

    def test_credential_retries_slow_down_then_succeeds(self):
        auth = self.server._DeviceLinkAuth()
        token = _encode_jwt({"sub": "acct-123"})
        exchanges = [
            ("slow_down", {"error": "slow_down"}),
            ("ok", {"access_token": "amcp_credential", "expires_in": 600}),
        ]

        async def exchange(_token: str):
            return exchanges.pop(0)

        with (
            patch.object(auth, "_exchange", side_effect=exchange) as exchange_mock,
            patch.object(auth, "_device_authorize") as device_authorize_mock,
            patch.object(
                self.server.asyncio, "sleep", new_callable=AsyncMock
            ) as sleep_mock,
        ):
            credential = asyncio.run(auth._credential(token))

        self.assertEqual("amcp_credential", credential)
        self.assertEqual(2, exchange_mock.await_count)
        sleep_mock.assert_awaited_once_with(self.server._SLOW_DOWN_SECONDS)
        device_authorize_mock.assert_not_called()

    def test_credential_slow_down_does_not_bootstrap_device_auth(self):
        auth = self.server._DeviceLinkAuth()
        token = _encode_jwt({"sub": "acct-123"})

        async def exchange(_token: str):
            return "slow_down", {"error": "slow_down"}

        with (
            patch.object(auth, "_exchange", side_effect=exchange) as exchange_mock,
            patch.object(auth, "_device_authorize") as device_authorize_mock,
            patch.object(self.server.asyncio, "sleep", new_callable=AsyncMock),
        ):
            with self.assertRaisesRegex(RuntimeError, "rate-limited"):
                asyncio.run(auth._credential(token))

        self.assertEqual(self.server._SLOW_DOWN_MAX_ATTEMPTS, exchange_mock.await_count)
        device_authorize_mock.assert_not_called()

    def test_token_key_hashes_full_bearer(self):
        token_a = _encode_jwt(
            {"sub": "acct-123", "sid": "sess-A", "client_id": "claude"}
        )
        token_b = _encode_jwt(
            {"sub": "acct-123", "sid": "sess-A", "client_id": "codex"}
        )
        # Same user+session, different client → different keys.
        self.assertNotEqual(
            self.server._token_key(token_a), self.server._token_key(token_b)
        )
        self.assertEqual(
            self.server._token_key(token_a), self.server._token_key(token_a)
        )
        self.assertEqual(64, len(self.server._token_key(token_a)))

    def test_credential_does_not_share_cache_across_clients(self):
        auth = self.server._DeviceLinkAuth()
        claude = _encode_jwt(
            {"sub": "acct-123", "sid": "sess-A", "client_id": "claude"}
        )
        codex = _encode_jwt({"sub": "acct-123", "sid": "sess-A", "client_id": "codex"})
        auth._credentials[self.server._token_key(claude)] = (
            "amcp_claude",
            time.monotonic() + 600,
        )

        async def exchange(_token: str):
            return "ok", {"access_token": "amcp_codex", "expires_in": 600}

        with patch.object(auth, "_exchange", side_effect=exchange) as exchange_mock:
            self.assertEqual("amcp_claude", asyncio.run(auth._credential(claude)))
            self.assertEqual("amcp_codex", asyncio.run(auth._credential(codex)))

        exchange_mock.assert_awaited_once_with(codex)


async def _collect_auth_requests(auth, request):
    return [req async for req in auth.async_auth_flow(request)]


def _encode_jwt(claims: dict) -> str:
    """Build a JWT-shaped token whose payload segment carries the given claims."""
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=")
    return f"aaa.{payload.decode()}.ccc"


if __name__ == "__main__":
    unittest.main()
