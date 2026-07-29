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

    def test_rejects_fractional_values_for_integer_schemas(self):
        adapter = self.adapter(
            request={
                "parameters": [],
                "body": {
                    "contentType": "application/json",
                    "required": True,
                    "schema": {"type": "integer"},
                },
            },
            success=(
                {
                    "contentType": "application/json",
                    "schema": {"type": "integer"},
                    "status": "200",
                },
            ),
        )

        with self.assertRaisesRegex(PolicyAdapterError, "numeric"):
            adapter.shape_request("connector_get", {"body": 1.5})
        with self.assertRaisesRegex(PolicyAdapterError, "numeric"):
            adapter.shape_response("connector_get", 200, "application/json", b"1.5")

    def test_rejects_undeclared_input_before_forwarding(self):
        adapter = self.adapter(
            name="connector_update",
            method="patch",
            request={
                "parameters": [],
                "body": {
                    "contentType": "application/json",
                    "required": True,
                    "schema": {
                        "properties": {"name": {"type": "string"}},
                        "required": ["name"],
                        "type": "object",
                    },
                },
            },
        )

        with self.assertRaisesRegex(PolicyAdapterError, "undeclared"):
            adapter.shape_request(
                "connector_update",
                {"body": {"name": "source", "sharedConfig": {"password": "secret"}}},
            )

    def test_shapes_declared_path_and_body_input(self):
        adapter = self.adapter(
            name="connector_update",
            method="patch",
            request={
                "parameters": [
                    {
                        "in": "path",
                        "name": "uuid",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ],
                "body": {
                    "contentType": "application/json",
                    "required": True,
                    "schema": {
                        "properties": {"name": {"type": "string"}},
                        "required": ["name"],
                        "type": "object",
                    },
                },
            },
        )

        self.assertEqual(
            {"path": {"uuid": "connector-123"}, "body": {"name": "source"}},
            adapter.shape_request(
                "connector_update",
                {"path": {"uuid": "connector-123"}, "body": {"name": "source"}},
            ),
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

    def test_resolves_a_path_template_to_its_policy_tool(self):
        adapter = self.adapter()

        self.assertEqual(
            "connector_get", adapter.tool_for_route("GET", "/connectors/123").name
        )


if __name__ == "__main__":
    unittest.main()
