"""釘住 0.7.0 對齊 Developer 平台的三件事,每一件的失效方式都是「不會有錯誤訊息」。

1. 建置產物不推上去——平台是**靜默丟棄**,push 的寫後回讀拿檔數比對,不先濾就假失敗
2. AI GO 容器型別契約——Developer 端全綠、按下發布才 422,而那時版本已 submitted
3. 沙箱 egress 不收憑證(domain-only)——收下永不生效的設定 = 讓人以為金鑰帶上了
"""
import json
import tempfile
import unittest
from pathlib import Path

import helpers  # noqa: F401
import common
import devportal
import normalize_meta


class TestBuildArtifacts(unittest.TestCase):
    """對齊平台 template_helpers.is_excluded_artifact(2026-08-04)。"""

    def test_flags_pycache_and_friends(self):
        for rel in ("actions/__pycache__/hello.cpython-314.pyc",
                    "__pycache__/x.pyc",
                    "src/x.pyo",
                    ".DS_Store",
                    "src/assets/.DS_Store",
                    "Thumbs.db"):
            with self.subTest(rel=rel):
                self.assertTrue(common.is_build_artifact(rel))

    def test_keeps_real_files(self):
        for rel in ("actions/hello.py", "src/App.tsx", "_template_meta.json",
                    "src/assets/logo.png", "docs/pycache-notes.md"):
            with self.subTest(rel=rel):
                self.assertFalse(common.is_build_artifact(rel))

    def test_collect_files_drops_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            template = Path(tmp)
            (template / "actions" / "__pycache__").mkdir(parents=True)
            (template / "actions" / "hello.py").write_text("def execute(ctx): pass\n",
                                                           encoding="utf-8")
            # 二進位且非 TEXT_EXT——沒有排除規則的話會以 is_binary 推上去
            (template / "actions" / "__pycache__" / "hello.pyc").write_bytes(b"\x00\x01\xff")
            (template / ".DS_Store").write_bytes(b"\x00")

            paths = {f["file_path"] for f in devportal.collect_files(template)}
        self.assertEqual(paths, {"actions/hello.py"})


class TestAigoTypeContract(unittest.TestCase):
    """對齊平台 template_helpers._AIGO_UPSERT_TYPES(2026-08-11)。"""

    def test_data_center_schema_as_list_is_rejected(self):
        # 零自建表的模板很自然會寫 [],因為 data_references_schema 就是陣列
        problems = normalize_meta.aigo_type_problems({"data_center_schema": []})
        self.assertEqual(len(problems), 1)
        self.assertIn("不要送 []", problems[0])

    def test_absent_and_none_are_fine(self):
        # 缺鍵由平台 build_publish_metadata 的 setdefault 兜住;None 不送
        self.assertEqual(normalize_meta.aigo_type_problems({}), [])
        self.assertEqual(normalize_meta.aigo_type_problems({"data_center_schema": None}), [])

    def test_container_shapes(self):
        self.assertEqual(normalize_meta.aigo_type_problems({
            "data_center_schema": {"version": 1, "tables": []},
            "data_references_schema": [],
            "setup_schema": {},
            "required_egress": {},
            "tags": ["crm"],
        }), [])
        self.assertTrue(normalize_meta.aigo_type_problems({"setup_schema": []}))
        self.assertTrue(normalize_meta.aigo_type_problems({"data_references_schema": {}}))

    def test_tags_items_must_be_strings(self):
        # AI GO 是 List[str];只驗外層會漏掉這種
        problems = normalize_meta.aigo_type_problems({"tags": ["crm", 3]})
        self.assertEqual(len(problems), 1)
        self.assertIn("每一項", problems[0])

    def test_scalars_are_not_checked(self):
        # AI GO 的 Pydantic 跑 lax mode 會隱式轉型,驗嚴了是假警報
        self.assertEqual(normalize_meta.aigo_type_problems({"sort_order": "3"}), [])

    def test_build_metadata_blocks_before_push(self):
        meta = {"name": "n", "description": "d", "category": "crm", "version": "1.0.0",
                "access_mode": "internal", "author": "a", "data_center_schema": []}
        with self.assertRaises(SystemExit) as cm:
            devportal.build_metadata(meta)
        self.assertIn("data_center_schema", str(cm.exception))

    def test_build_metadata_drops_none_and_empty(self):
        # 非 Optional 欄位顯式送 null 一樣 422(Pydantic 預設值只在缺鍵時套用)
        payload = devportal.build_metadata(
            {"name": "n", "description": "d", "author": None, "long_description": ""})
        self.assertEqual(payload, {"name": "n", "description": "d"})


class TestEgressDomainOnly(unittest.TestCase):
    """對齊平台 sandbox.upsert_egress 的 400(ADR 0010,2026-08-04)。

    e2e 的整段 main() 不好單測,這裡直接釘 --egress-file 的判定式本身——
    改動時要一起改,不能只改 e2e 那邊而讓這條靜靜過。
    """

    @staticmethod
    def stale(egress_values: dict) -> list:
        return sorted(s for s, c in egress_values.items()
                      if isinstance(c, dict)
                      and (c.get("auth_type", "none") != "none" or c.get("auth_config")))

    def test_detects_legacy_credential_config(self):
        self.assertEqual(self.stale({
            "line": {"base_url": "https://api.line.me", "auth_type": "bearer",
                     "auth_config": {"token": "x"}},
            "erp": {"base_url": "https://erp.example.com", "auth_config": {"api_key": "y"}},
        }), ["erp", "line"])

    def test_domain_only_config_passes(self):
        self.assertEqual(self.stale({
            "line": {"base_url": "https://api.line.me"},
            "wild": {"base_url": "https://x.example.com", "allow_dynamic_host": True,
                     "auth_type": "none", "timeout_ms": 15000},
        }), [])

    def test_e2e_help_does_not_advertise_auth_fields(self):
        # 文件教用戶填 auth_config,填了就是 S8 hard_fail——help 字串是唯一的教學入口
        src = (Path(__file__).resolve().parent.parent
               / "scripts" / "e2e_devportal.py").read_text(encoding="utf-8")
        help_line = next(ln for ln in src.splitlines() if "沙箱 egress 設定 JSON" in ln)
        self.assertNotIn("auth_type", help_line)
        self.assertNotIn("auth_config", help_line)


class TestScanRuleSuggestion(unittest.TestCase):
    def test_raw_http_suggestion_teaches_self_supplied_credentials(self):
        """v0.4.0–0.6.4 教「憑證不要自帶」,ADR 0010 之後那是反的。"""
        rules = json.loads((Path(__file__).resolve().parent.parent
                            / "config" / "scan_rules.json").read_text(encoding="utf-8"))
        rule = next(r for r in rules["rules"] if r["id"] == "raw_http_outbound")
        self.assertIn("ctx.secrets.get", rule["suggestion"])
        self.assertNotIn("憑證不要自帶", rule["suggestion"])


if __name__ == "__main__":
    unittest.main()
