import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from scripts import download_openapi_spec


class TestDownloadOpenAPISpec(unittest.TestCase):
    def test_download_failure_includes_source_url(self):
        with (
            tempfile.TemporaryDirectory() as temporary_directory,
            patch.object(
                download_openapi_spec.urllib.request,
                "urlopen",
                side_effect=urllib.error.URLError("unavailable"),
            ),
        ):
            destination = Path(temporary_directory) / "openapi.yaml"

            with self.assertRaisesRegex(
                RuntimeError, "failed to download OpenAPI spec"
            ):
                download_openapi_spec.download_openapi_spec(destination)

    def test_checksum_failure_includes_expected_and_actual_checksums(self):
        class Response:
            def read(self):
                return b"unexpected content"

        with (
            tempfile.TemporaryDirectory() as temporary_directory,
            patch.object(
                download_openapi_spec.urllib.request,
                "urlopen",
                return_value=Response(),
            ),
        ):
            destination = Path(temporary_directory) / "openapi.yaml"

            with self.assertRaisesRegex(ValueError, "expected .* got"):
                download_openapi_spec.download_openapi_spec(destination)
