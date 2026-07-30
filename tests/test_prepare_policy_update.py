import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import prepare_policy_update


class _Response:
    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self) -> bytes:
        return self._body


class TestPreparePolicyUpdate(unittest.TestCase):
    def test_prepare_writes_lock_and_snapshot_for_released_policy(self):
        policy_bytes = _policy_bytes("v1.2.3")

        with tempfile.TemporaryDirectory() as directory:
            bundle_dir = Path(directory)
            with patch.object(
                prepare_policy_update.urllib.request,
                "urlopen",
                return_value=_Response(policy_bytes),
            ) as urlopen:
                result = prepare_policy_update.prepare_policy_update(
                    "v1.2.3", bundle_dir
                )

            lock = json.loads((bundle_dir / "policy.lock.json").read_text())
            snapshot = json.loads((bundle_dir / "policy.contract.json").read_text())

        self.assertTrue(result.changed)
        self.assertEqual(
            "https://github.com/artie-labs/artie-api-spec/releases/download/v1.2.3/openapi.yaml",
            urlopen.call_args.args[0],
        )
        self.assertEqual("v1.2.3", lock["release"]["tag"])
        self.assertEqual("openapi.yaml", lock["release"]["asset"])
        self.assertEqual(hashlib.sha256(policy_bytes).hexdigest(), lock["policySHA256"])
        self.assertEqual("v1.2.3", snapshot["releaseTag"])
        self.assertEqual(["safe_list"], [tool["name"] for tool in snapshot["tools"]])

    def test_prepare_is_idempotent_when_lock_and_snapshot_are_current(self):
        policy_bytes = _policy_bytes("v1.2.3")

        with tempfile.TemporaryDirectory() as directory:
            bundle_dir = Path(directory)
            with patch.object(
                prepare_policy_update.urllib.request,
                "urlopen",
                return_value=_Response(policy_bytes),
            ):
                prepare_policy_update.prepare_policy_update("v1.2.3", bundle_dir)
                result = prepare_policy_update.prepare_policy_update(
                    "v1.2.3", bundle_dir
                )

        self.assertFalse(result.changed)

    def test_prepare_rejects_invalid_policy_without_writing_files(self):
        policy_bytes = b"""openapi: 3.1.0
info:
  version: v1.2.3
paths:
  /unsafe:
    get:
      operationId: unsafe_list
      responses:
        "200":
          description: OK
"""

        with tempfile.TemporaryDirectory() as directory:
            bundle_dir = Path(directory)
            lock_path = bundle_dir / "policy.lock.json"
            snapshot_path = bundle_dir / "policy.contract.json"
            lock_path.write_text("existing lock")
            snapshot_path.write_text("existing snapshot")
            with patch.object(
                prepare_policy_update.urllib.request,
                "urlopen",
                return_value=_Response(policy_bytes),
            ):
                with self.assertRaisesRegex(
                    prepare_policy_update.PolicyContractError, "x-artie-mcp"
                ):
                    prepare_policy_update.prepare_policy_update("v1.2.3", bundle_dir)

            self.assertEqual("existing lock", lock_path.read_text())
            self.assertEqual("existing snapshot", snapshot_path.read_text())

    def test_prepare_rejects_invalid_release_tag_before_download(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(
                prepare_policy_update.urllib.request, "urlopen"
            ) as urlopen:
                with self.assertRaisesRegex(
                    prepare_policy_update.PolicyContractError, "release tag"
                ):
                    prepare_policy_update.prepare_policy_update("main", Path(directory))

        urlopen.assert_not_called()


def _policy_bytes(version: str) -> bytes:
    return f"""openapi: 3.1.0
info:
  version: {version}
paths:
  /safe:
    get:
      operationId: safe_list
      responses:
        "200":
          description: OK
      x-artie-mcp:
        exposure: exposed
        operationId: safe_list
        title: List safe resources
        triggerDescription: Use when listing safe resources.
        readOnlyHint: true
        destructiveHint: false
        idempotentHint: true
        openWorldHint: false
        requiredScopes:
          - safe:read
        retrySemantics: safe
        inputSensitivity: none
        outputSensitivity: none
""".encode()
