"""來源側租戶空間解析(common.aigo_base_url)。

背景(builder 1.8.0 破壞性變更,2026-08 平台硬切):AI GO 登入改走
https://{tenant}.ai-go.app,apex 回與「密碼錯」完全同形的 401(反帳號列舉設計)。
所以客戶端必須:沒有 apex 預設值、直接擋 apex 並印規則——與其讓使用者去查
一個無解的「密碼錯誤」,不如當場說清楚。
"""
import unittest

import helpers  # noqa: F401  路徑設定
import common


class TestAigoBaseUrl(unittest.TestCase):
    def test_tenant_prefix_builds_workspace_url(self):
        self.assertEqual(common.aigo_base_url({"AIGO_TENANT": "urfit"}),
                         "https://urfit.ai-go.app")

    def test_tenant_is_case_folded(self):
        self.assertEqual(common.aigo_base_url({"AIGO_TENANT": "Demo"}),
                         "https://demo.ai-go.app")

    def test_explicit_base_url_wins_over_tenant(self):
        env = {"AIGO_BASE_URL": "https://uat-ai-go.app", "AIGO_TENANT": "urfit"}
        self.assertEqual(common.aigo_base_url(env), "https://uat-ai-go.app")

    def test_apex_is_rejected_with_rule_message(self):
        """apex 的 401 與密碼錯同形——放行等於把使用者送去查無解的密碼問題。"""
        for host in ("https://ai-go.app", "https://ai-go.app/", "https://www.ai-go.app"):
            with self.assertRaises(RuntimeError) as ctx:
                common.aigo_base_url({"AIGO_BASE_URL": host})
            self.assertIn("401", str(ctx.exception))

    def test_multi_level_prefix_rejected(self):
        with self.assertRaises(RuntimeError):
            common.aigo_base_url({"AIGO_BASE_URL": "https://a.b.ai-go.app"})

    def test_non_aigo_namespaces_pass_through(self):
        # UAT 與本機不在 ai-go.app 命名空間,不套租戶前綴規則
        self.assertEqual(common.aigo_base_url({"AIGO_BASE_URL": "http://localhost:8000"}),
                         "http://localhost:8000")
        self.assertEqual(common.aigo_base_url({"AIGO_BASE_URL": "https://uat-ai-go.app"}),
                         "https://uat-ai-go.app")

    def test_missing_both_raises_with_setup_guide(self):
        with self.assertRaises(RuntimeError) as ctx:
            common.aigo_base_url({})
        msg = str(ctx.exception)
        self.assertIn("AIGO_TENANT", msg)
        self.assertIn("401", msg)

    def test_garbage_tenant_rejected(self):
        for bad in ("urfit.ai-go.app", "https://urfit", "ur fit", "-urfit"):
            with self.assertRaises(RuntimeError):
                common.aigo_base_url({"AIGO_TENANT": bad})

    def test_load_env_has_no_apex_default(self):
        """0.9.0 拿掉 apex 預設值:沒有一個對全部租戶都成立的 base_url。
        (隔離真實 .env 與環境變數,只驗 load_env 自己不再塞 apex)"""
        import os
        from pathlib import Path
        from unittest import mock
        clean = {k: v for k, v in os.environ.items()
                 if not k.startswith(("AIGO_", "DEVPORTAL_"))}
        missing = Path("Z:/__no_such_env__/.env")
        with mock.patch.dict(os.environ, clean, clear=True), \
             mock.patch.object(common, "ENV_FILE", missing), \
             mock.patch.object(common, "LEGACY_ENV_FILE", missing):
            env = common.load_env()
        self.assertNotIn("AIGO_BASE_URL", env)


if __name__ == "__main__":
    unittest.main()
