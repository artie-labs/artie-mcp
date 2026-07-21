import importlib
import sys
import unittest
from unittest.mock import patch

import httpx


class _OpenAPIResponse:
    text = """\
openapi: 3.1.0
info:
  title: Test API
  version: 1.0.0
paths:
  /status:
    get:
      operationId: getStatus
      responses:
        '200':
          description: OK
"""

    def raise_for_status(self):
        return self


class TestServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.modules.pop("server", None)
        with patch.object(httpx, "get", return_value=_OpenAPIResponse()) as get:
            cls.server = importlib.import_module("server")
        get.assert_called_once_with(cls.server._SPEC_URL)

    def test_hash_is_deterministic(self):
        self.assertEqual(
            "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
            self.server._hash("test"),
        )

    def test_strip_secrets_redacts_nested_dicts_and_lists(self):
        self.assertEqual(
            {
                "connector": {"name": "source"},
                "items": [{"id": 1}, {"nested": {"id": 2}}],
            },
            self.server._strip_secrets(
                {
                    "connector": {
                        "name": "source",
                        "sharedConfig": {"token": "secret"},
                    },
                    "items": [
                        {"id": 1, "sharedConfig": {"password": "secret"}},
                        {"nested": {"id": 2, "sharedConfig": "secret"}},
                    ],
                }
            ),
        )
