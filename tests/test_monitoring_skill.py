import json
import re
import unittest
from pathlib import Path


class TestMonitoringSkill(unittest.TestCase):
    def setUp(self):
        self.skill = Path("plugins/artie/skills/monitoring/SKILL.md").read_text()
        contract = json.loads(Path("contract/policy.contract.json").read_text())
        self.tools = {tool["name"]: tool for tool in contract["tools"]}

    def test_references_only_monitoring_tools_in_the_pinned_contract(self):
        referenced = set(re.findall(r"`((?:pipeline|company)_[a-z_]+)`", self.skill))
        self.assertEqual(
            {
                "company_trigger_automatic_schema_changes",
                "pipeline_backfill_tables",
                "pipeline_cancel_backfill_tables",
                "pipeline_detail",
                "pipeline_detect_schema_changes",
                "pipeline_list",
                "pipeline_start",
                "pipeline_trigger_automatic_schema_changes",
                "pipeline_update",
                "pipeline_update_status",
                "pipeline_usage",
            },
            referenced,
        )
        self.assertTrue(referenced <= self.tools.keys())

    def test_intent_matrix_marks_every_mutating_monitoring_call_for_confirmation(self):
        matrix = self.skill.split("## Intent Matrix", 1)[1].split(
            "## Reading Results", 1
        )[0]
        tool_cells = [
            line.split("|")[2]
            for line in matrix.splitlines()
            if line.startswith("|") and "`" in line
        ]
        mutating = {
            name
            for cell in tool_cells
            for name in re.findall(r"`((?:pipeline|company)_[a-z_]+)`", cell)
            if not self.tools[name]["annotations"]["readOnlyHint"]
        }
        self.assertEqual(
            {
                "company_trigger_automatic_schema_changes",
                "pipeline_backfill_tables",
                "pipeline_cancel_backfill_tables",
                "pipeline_detect_schema_changes",
                "pipeline_trigger_automatic_schema_changes",
                "pipeline_update_status",
            },
            mutating,
        )
        for name in mutating:
            row = next(line for line in matrix.splitlines() if f"`{name}`" in line)
            self.assertIn("confirm", row.lower())

    def test_skill_preserves_unavailable_tool_fallback(self):
        self.assertIn("Inspect `tools/list`", self.skill)
        self.assertIn("never invent metrics or a tool result", self.skill)


if __name__ == "__main__":
    unittest.main()
