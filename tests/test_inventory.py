import json
import tempfile
import unittest
from pathlib import Path

import helpers
import common
from acquire import build_inventory
from normalize_meta import build_post_install_checklist


class TestInventory(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.template = helpers.make_minimal_template(Path(self.tmp.name) / "template")
        self.work = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_webhook_and_egress_and_legacy_detected(self):
        (self.template / "actions" / "manifest.json").write_text(json.dumps({
            "receive_webhook": {"description": "hook", "webhook": True},
            "sync_orders": {"description": "sync"},
        }), encoding="utf-8")
        (self.template / "actions" / "receive_webhook.py").write_text(
            'import httpx\n\ndef execute(ctx):\n'
            '    httpx.post("https://api.line.me/v2/push", timeout=30)\n'
            '    ctx.db.query_object("orders")\n', encoding="utf-8")
        (self.template / "actions" / "sync_orders.py").write_text(
            "def execute(ctx):\n    ctx.db.insert('x', {})\n", encoding="utf-8")

        inv = build_inventory(self.template, {}, None)
        self.assertEqual(inv["webhooks"], ["receive_webhook"])
        self.assertIn("api.line.me", inv["egress_domains"])
        self.assertTrue(any("query_object" in x for x in inv["legacy_usage"]))
        self.assertIn("repo 來源", inv["crons_note"])

    def test_clean_template_empty_inventory(self):
        inv = build_inventory(self.template, {}, None)
        self.assertEqual(inv["webhooks"], [])
        self.assertEqual(inv["egress_domains"], [])
        self.assertEqual(inv["egress_slugs"], [])
        self.assertEqual(inv["legacy_usage"], [])

    def test_egress_slug_captured(self):
        (self.template / "actions" / "call_ext.py").write_text(
            'def execute(ctx):\n    ctx.http.call("twse-mops", "/api/x")\n', encoding="utf-8")
        inv = build_inventory(self.template, {}, None)
        self.assertEqual(inv["egress_slugs"], ["twse-mops"])


class TestPostInstallChecklist(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.work = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_checklist_from_inventory(self):
        common.dump_json(self.work / "inventory.json", {
            "webhooks": ["receive_webhook"],
            "egress_domains": ["api.line.me"],
            "crons": [{"name": "daily_sync", "cron": "0 9 * * *"}],
        })
        meta = {"setup_schema": {"LINE_CHANNEL_ACCESS_TOKEN": {"type": "secret"}}}
        text = build_post_install_checklist(self.work, meta)
        self.assertIn("## 安裝後設定", text)
        self.assertIn("LINE_CHANNEL_ACCESS_TOKEN", text)
        self.assertIn("api.line.me", text)
        self.assertIn("receive_webhook", text)
        self.assertIn("daily_sync", text)
        self.assertIn("/dashboard/settings/integrations", text)

    def test_no_inventory_no_secrets_empty(self):
        self.assertEqual(build_post_install_checklist(self.work, {}), "")


if __name__ == "__main__":
    unittest.main()
