import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HINTS = ("readOnlyHint", "destructiveHint", "openWorldHint")


class TestChatGPTAppSubmission(unittest.TestCase):
    def test_tools_match_policy_contract(self):
        contract = json.loads((ROOT / "contract/policy.contract.json").read_text())
        submission = json.loads((ROOT / "chatgpt-app-submission.json").read_text())
        expected = {
            tool["name"]: {hint: tool["annotations"][hint] for hint in HINTS}
            for tool in contract["tools"]
        }
        actual = {
            name: tool["annotations"] for name, tool in submission["tools"].items()
        }
        self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
