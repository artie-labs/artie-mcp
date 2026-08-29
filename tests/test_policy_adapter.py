import unittest

from policy_adapter import PolicyAdapterError, SafeTrafficAdapter
from policy_contract import PolicyContract, ToolContract


class TestSafeTrafficAdapter(unittest.TestCase):
    def adapter(self, **tool_overrides):
        tool_values = {
            "name": "connector_get",
            "method": "get",
            "path": "/connectors/{uuid}",
            "title": "Get connector",
            "trigger_description": "Use when reading a connector.",
            "required_scopes": ("connectors:read",),
            "annotations": {},
            "retry_semantics": "safe",
            "input_sensitivity": "none",
            "output_sensitivity": "none",
            "request": {"parameters": []},
            "success": ({"status": "204"},),
            "bodiless_success": False,
        }
        tool_values.update(tool_overrides)
        tool = ToolContract(**tool_values)
        return SafeTrafficAdapter(PolicyContract(tools=(tool,)))

    def test_shapes_a_success_response_from_the_declared_schema(self):
        adapter = self.adapter(
            success=(
                {
                    "contentType": "application/json",
                    "schema": {
                        "allOf": [
                            {
                                "properties": {"name": {"type": "string"}},
                                "type": ["object", "null"],
                            },
                            {
                                "properties": {
                                    "tables": {
                                        "items": {
                                            "properties": {"name": {"type": "string"}},
                                            "type": "object",
                                        },
                                        "type": "array",
                                    }
                                },
                                "type": "object",
                            },
                        ]
                    },
                    "status": "200",
                },
            )
        )

        shaped = adapter.shape_response(
            "connector_get",
            200,
            "application/json",
            b'{"name":"source","sharedConfig":{"password":"secret"},"tables":[{"name":"users","sharedConfig":{"token":"secret"}}]}',
        )

        self.assertEqual({"name": "source", "tables": [{"name": "users"}]}, shaped)
        with self.assertRaisesRegex(PolicyAdapterError, "valid JSON") as error:
            adapter.shape_response(
                "connector_get",
                200,
                "application/json",
                b'{"sharedConfig":{"password":"secret"}',
            )
        self.assertNotIn("secret", str(error.exception))
        with self.assertRaisesRegex(PolicyAdapterError, "status 500") as error:
            adapter.shape_response(
                "connector_get",
                500,
                "application/json",
                b'{"sharedConfig":{"password":"secret"}}',
            )
        self.assertNotIn("secret", str(error.exception))

    def test_keeps_additional_properties_when_schema_allows_them(self):
        adapter = self.adapter(
            success=(
                {
                    "contentType": "application/json",
                    "schema": {
                        "properties": {
                            "sharedConfig": {
                                "additionalProperties": True,
                                "type": "object",
                            },
                            "uuid": {"type": "string"},
                        },
                        "type": "object",
                    },
                    "status": "200",
                },
            )
        )

        self.assertEqual(
            {
                "sharedConfig": {
                    "host": "db.example",
                    "password": "__artie__masked",
                    "user": "artie",
                },
                "uuid": "c1",
            },
            adapter.shape_response(
                "connector_get",
                200,
                "application/json",
                b'{"uuid":"c1","sharedConfig":{"host":"db.example","user":"artie","password":"__artie__masked"},"secretExtra":"drop-me"}',
            ),
        )

    def test_shapes_additional_properties_when_a_value_schema_is_declared(self):
        adapter = self.adapter(
            success=(
                {
                    "contentType": "application/json",
                    "schema": {
                        "additionalProperties": {"type": "integer"},
                        "properties": {"name": {"type": "string"}},
                        "type": "object",
                    },
                    "status": "200",
                },
            )
        )

        self.assertEqual(
            {"count": 2, "name": "source"},
            adapter.shape_response(
                "connector_get",
                200,
                "application/json",
                b'{"name":"source","count":2}',
            ),
        )

    def test_selects_the_matching_one_of_output_branch(self):
        adapter = self.adapter(
            success=(
                {
                    "contentType": "application/json",
                    "schema": {
                        "oneOf": [
                            {
                                "properties": {"id": {"type": "string"}},
                                "required": ["id"],
                                "type": "object",
                            },
                            {
                                "properties": {"error": {"type": "string"}},
                                "required": ["error"],
                                "type": "object",
                            },
                        ]
                    },
                    "status": "200",
                },
            )
        )

        self.assertEqual(
            {"error": "not found"},
            adapter.shape_response(
                "connector_get",
                200,
                "application/json",
                b'{"error":"not found","sharedConfig":{"password":"secret"}}',
            ),
        )

    def test_one_of_skips_an_optional_branch_without_matching_properties(self):
        adapter = self.adapter(
            success=(
                {
                    "contentType": "application/json",
                    "schema": {
                        "oneOf": [
                            {
                                "properties": {"id": {"type": "string"}},
                                "type": "object",
                            },
                            {
                                "properties": {"error": {"type": "string"}},
                                "required": ["error"],
                                "type": "object",
                            },
                        ]
                    },
                    "status": "200",
                },
            )
        )

        self.assertEqual(
            {"error": "not found"},
            adapter.shape_response(
                "connector_get",
                200,
                "application/json",
                b'{"error":"not found","sharedConfig":{"password":"secret"}}',
            ),
        )

    def test_prefers_a_static_route_over_a_matching_template(self):
        create = ToolContract(
            name="pipeline_create_from_source",
            method="post",
            path="/pipelines/create-from-source",
            title="Create pipeline",
            trigger_description="Use when creating a pipeline.",
            required_scopes=("pipelines:write",),
            annotations={},
            retry_semantics="unsafe",
            input_sensitivity="none",
            output_sensitivity="none",
            request={"parameters": []},
            success=({"status": "204"},),
            bodiless_success=False,
        )
        template = ToolContract(
            name="pipeline_get",
            method="post",
            path="/pipelines/{uuid}",
            title="Get pipeline",
            trigger_description="Use when reading a pipeline.",
            required_scopes=("pipelines:read",),
            annotations={},
            retry_semantics="safe",
            input_sensitivity="none",
            output_sensitivity="none",
            request={"parameters": []},
            success=({"status": "204"},),
            bodiless_success=False,
        )
        adapter = SafeTrafficAdapter(PolicyContract(tools=(template, create)))

        self.assertEqual(
            "pipeline_create_from_source",
            adapter.tool_for_route("POST", "/pipelines/create-from-source").name,
        )

    def test_returns_stable_result_for_policy_marked_bodiless_success(self):
        adapter = self.adapter(
            name="connector_delete",
            method="delete",
            bodiless_success=True,
        )

        self.assertEqual(
            {"success": True},
            adapter.shape_response("connector_delete", 204, "", b""),
        )

    def test_returns_stable_result_for_a_schema_less_accepted_response(self):
        adapter = self.adapter(
            name="pipeline_trigger_automatic_schema_changes",
            method="post",
            success=({"status": "202"},),
            bodiless_success=True,
        )

        self.assertEqual(
            {"success": True},
            adapter.shape_response(
                "pipeline_trigger_automatic_schema_changes", 202, "", b""
            ),
        )

    def test_rejects_a_bodiless_flag_that_the_contract_would_not_admit(self):
        # compile_policy cannot produce this pairing, so the tool is built directly.
        # The guard exists for a future contract relaxation, not for today's bundle.
        adapter = self.adapter(
            bodiless_success=True,
            success=(
                {
                    "contentType": "application/json",
                    "schema": {"type": "object"},
                    "status": "200",
                },
            ),
        )

        with self.assertRaisesRegex(PolicyAdapterError, "bodiless success"):
            adapter.shape_response("connector_get", 200, "application/json", b"{}")

    def test_rejects_a_body_bearing_status_that_declares_no_content(self):
        # The F1 shape: a 200 whose schema was never declared must stay an error
        # rather than be reported to the client as an empty success.
        adapter = self.adapter(success=({"status": "200"},))

        with self.assertRaisesRegex(PolicyAdapterError, "approved JSON contract"):
            adapter.shape_response("connector_get", 200, "application/json", b"{}")

    def test_resolves_a_path_template_to_its_policy_tool(self):
        adapter = self.adapter()

        self.assertEqual(
            "connector_get", adapter.tool_for_route("GET", "/connectors/123").name
        )


if __name__ == "__main__":
    unittest.main()
