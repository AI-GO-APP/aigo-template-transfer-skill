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

    def test_egress_slug_from_module_constant(self):
        """slug 放常數是很自然的寫法,漏掉的話 required_egress 就少宣告——
        租戶安裝不會被提示授權該服務,裝完 action 一律連不出去。
        2026-08-12 在白老鼠身上實際踩到。"""
        (self.template / "actions" / "call_ext.py").write_text(
            'OPENAI_EGRESS = "openai"\n'
            'OPENAI_PATH = "/v1/responses"\n\n'
            'def execute(ctx):\n'
            '    ctx.http.call(OPENAI_EGRESS, OPENAI_PATH, method="POST")\n',
            encoding="utf-8")
        inv = build_inventory(self.template, {}, None)
        self.assertEqual(inv["egress_slugs"], ["openai"])

    def test_egress_slug_mixed_literal_and_constant(self):
        (self.template / "actions" / "a.py").write_text(
            'SVC = "erp"\ndef execute(ctx):\n    ctx.http.fetch(SVC, "https://x/y")\n',
            encoding="utf-8")
        (self.template / "actions" / "b.py").write_text(
            'def execute(ctx):\n    ctx.http.call("line", "/v2/push")\n', encoding="utf-8")
        inv = build_inventory(self.template, {}, None)
        self.assertEqual(inv["egress_slugs"], ["erp", "line"])

    def test_unresolvable_variable_is_not_guessed(self):
        """解不出來就不報——誤報會讓租戶被要求授權一個根本用不到的服務。
        跨檔 import 的常數也刻意不追(要追就得做真的符號解析)。"""
        (self.template / "actions" / "call_ext.py").write_text(
            'def execute(ctx):\n'
            '    slug = ctx.params.get("svc")\n'
            '    ctx.http.call(slug, "/x")\n', encoding="utf-8")
        inv = build_inventory(self.template, {}, None)
        self.assertEqual(inv["egress_slugs"], [])


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

    def test_egress_slug_is_what_the_tenant_must_create(self):
        """slug 才是 ctx.http.call 解析服務的鍵。只印網域的話,租戶會建出一個
        名字不對的服務,action 依然連不出去——而錯誤訊息說的是「service 未註冊」,
        對不上清單裡那條「加入網域」。"""
        common.dump_json(self.work / "inventory.json", {
            "egress_slugs": ["openai"],
            "egress_domains": ["api.openai.com"],
        })
        text = build_post_install_checklist(self.work, {})
        self.assertIn("`openai`", text)
        self.assertIn("完全相同的 slug", text)
        self.assertIn("api.openai.com", text)      # 仍列出,供填 base_url 參考
        self.assertIn("不要填在服務上", text)        # domain-only:金鑰歸安裝表單

    def test_domains_only_falls_back_to_whitelist_wording(self):
        # 沒有 ctx.http.call(例如只有前端打外部 URL)時維持舊措辭
        common.dump_json(self.work / "inventory.json",
                         {"egress_slugs": [], "egress_domains": ["api.line.me"]})
        text = build_post_install_checklist(self.work, {})
        self.assertIn("Egress 白名單", text)
        self.assertIn("api.line.me", text)


if __name__ == "__main__":
    unittest.main()
