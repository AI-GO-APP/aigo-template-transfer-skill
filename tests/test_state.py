import json
import tempfile
import unittest
from pathlib import Path

import helpers  # noqa: F401
import common
from common import STAGES


def fresh_state(slug="t"):
    return {
        "slug": slug,
        "created_at": "2026-07-28T00:00:00",
        "last_hash": None,
        "stages": {s: {"status": "pending"} for s in STAGES},
    }


class TestStateMachine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.work = Path(self.tmp.name)
        common.save_state(self.work, fresh_state())

    def tearDown(self):
        self.tmp.cleanup()

    def test_stage_order_enforced(self):
        with self.assertRaises(SystemExit):
            common.require_stage(self.work, "S2_scan")

    def test_first_stage_allowed(self):
        state = common.require_stage(self.work, "S0_candidate")
        self.assertEqual(state["slug"], "t")

    def test_passed_predecessors_allow_next(self):
        state = common.load_state(self.work)
        common.mark_stage(self.work, state, "S0_candidate", "passed")
        state = common.require_stage(self.work, "S1_acquire")
        common.mark_stage(self.work, state, "S1_acquire", "passed")
        common.require_stage(self.work, "S2_scan")  # 不應拋錯

    def test_optional_skipped_stage(self):
        state = common.load_state(self.work)
        for stage in STAGES[:5]:
            common.mark_stage(self.work, state, stage, "passed")
        common.mark_stage(self.work, state, "S5_demo_data", "skipped")
        common.require_stage(self.work, "S6_audit", optional_ok=("S5_demo_data",))
        with self.assertRaises(SystemExit):
            common.require_stage(self.work, "S6_audit")  # 未宣告 optional 則擋

    def test_content_hash_gate(self):
        template = self.work / "template"
        template.mkdir()
        (template / "a.txt").write_text("v1", encoding="utf-8")
        state = common.load_state(self.work)
        common.mark_stage(self.work, state, "S0_candidate", "passed")
        # 閘外改動內容
        (template / "a.txt").write_text("v2", encoding="utf-8")
        with self.assertRaises(SystemExit):
            common.require_stage(self.work, "S1_acquire")

    def test_hash_updates_on_pass(self):
        template = self.work / "template"
        template.mkdir()
        (template / "a.txt").write_text("v1", encoding="utf-8")
        state = common.load_state(self.work)
        common.mark_stage(self.work, state, "S0_candidate", "passed")
        h1 = common.load_state(self.work)["last_hash"]
        (template / "a.txt").write_text("v2", encoding="utf-8")
        # 經閘內流程改動後 mark 會重新記錄
        state = common.load_state(self.work)
        common.mark_stage(self.work, state, "S1_acquire", "passed")
        h2 = common.load_state(self.work)["last_hash"]
        self.assertNotEqual(h1, h2)
        common.require_stage(self.work, "S2_scan")  # 不應拋錯

    def test_user_decision_gate(self):
        with self.assertRaises(SystemExit):
            common.require_user_decision({}, "candidate", "候選判定")
        with self.assertRaises(SystemExit):
            common.require_user_decision(
                {"candidate": {"decision": "new", "decided_by": "proposed"}},
                "candidate", "候選判定")
        entry = common.require_user_decision(
            {"candidate": {"decision": "new", "decided_by": "user"}},
            "candidate", "候選判定")
        self.assertEqual(entry["decision"], "new")


if __name__ == "__main__":
    unittest.main()
