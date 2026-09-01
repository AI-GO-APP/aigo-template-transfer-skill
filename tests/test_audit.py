import json
import tempfile
import unittest
from pathlib import Path

import helpers
import common
from audit_core import run_audit
from audit_local import (audit_dsl, audit_legacy, audit_manifest,
                         audit_reserved_table_names, audit_secrets, audit_shape)


class TestAudit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.template = helpers.make_minimal_template(Path(self.tmp.name))
        self.rules = common.load_config("audit_rules.json")

    def tearDown(self):
        self.tmp.cleanup()

    def all_results(self):
        results = dict(run_audit(self.template, self.rules))
        results["shape"] = audit_shape(self.template, self.rules["shape"])
        results["manifest"] = audit_manifest(self.template)
        results["secrets"], _ = audit_secrets(self.template)
        results["dsl"], _ = audit_dsl(self.template, None)
        results["legacy"] = audit_legacy(self.template, self.rules["legacy"])
        results["reserved"] = audit_reserved_table_names(self.template)
        return results

    def _write_meta_with_tables(self, *keys: str) -> None:
        meta = dict(helpers.MINIMAL_META)
        meta["data_center_schema"] = {"version": 1, "tables": [
            {"key": k, "display_name": k,
             "fields": [{"key": "note", "display_name": "備註", "type": "text"}]}
            for k in keys
        ]}
        (self.template / "_template_meta.json").write_text(
            json.dumps(meta, ensure_ascii=False), encoding="utf-8")

    def test_reserved_table_names_blocked_per_source(self):
        """三個來源各取一名:users(平台地板)、select(SQL 保留字)、
        hr_employees(ERP per-tenant)——安裝當下會 409,S6 要前置攔下。"""
        self._write_meta_with_tables("users", "select", "hr_employees", "csd_tickets")
        failures = audit_reserved_table_names(self.template)
        self.assertEqual(len(failures), 3, failures)
        text = "\n".join(failures)
        self.assertIn("users", text)
        self.assertIn("平台保留表名", text)
        self.assertIn("SQL 保留字", text)
        self.assertIn("ERP", text)
        self.assertNotIn("csd_tickets", text)

    def test_reserved_check_prefers_erp_message(self):
        """hr_payroll_slips 同時在 ERP 與地板兩份清單——訊息採 ERP(對齊平台 classify
        優先序:對租戶而言「與系統內建表名衝突」比「平台保留」更能指向怎麼改)。"""
        self._write_meta_with_tables("hr_payroll_slips")
        failures = audit_reserved_table_names(self.template)
        self.assertEqual(len(failures), 1)
        self.assertIn("ERP", failures[0])

    def test_reserved_check_passes_clean_names(self):
        self._write_meta_with_tables("csd_tickets", "order_notes")
        self.assertEqual(audit_reserved_table_names(self.template), [])

    def test_minimal_template_passes_all(self):
        for name, failures in self.all_results().items():
            self.assertEqual(failures, [], f"{name} 不應有失敗:{failures}")

    def test_missing_entry(self):
        (self.template / "src" / "main.tsx").unlink()
        (self.template / "src" / "App.tsx").unlink()
        failures = audit_shape(self.template, self.rules["shape"])
        self.assertTrue(any("entry" in f for f in failures))

    def test_nonempty_stub_fails(self):
        (self.template / "src" / "data.json").write_text('{"leads": {"id": "x"}}',
                                                         encoding="utf-8")
        failures = audit_shape(self.template, self.rules["shape"])
        self.assertTrue(any("空殼" in f for f in failures))

    def test_unknown_bare_import(self):
        (self.template / "src" / "Bad.tsx").write_text(
            'import axios from "axios"\n', encoding="utf-8")
        failures = audit_shape(self.template, self.rules["shape"])
        self.assertTrue(any("axios" in f for f in failures))

    def test_shared_module_exempt_from_execute(self):
        shared = self.template / "actions" / "_shared"
        shared.mkdir()
        (shared / "money.py").write_text(
            "def fmt(n):\n    return f'{n:,.0f}'\n", encoding="utf-8")
        results = run_audit(self.template, self.rules)
        self.assertEqual(results["Action 結構"], [])

    def test_shared_module_still_checked_for_hardcoded_keys(self):
        shared = self.template / "actions" / "_shared"
        shared.mkdir()
        (shared / "cfg.py").write_text(
            'api_key = "sk_live_abcdef1234"\n', encoding="utf-8")
        results = run_audit(self.template, self.rules)
        self.assertTrue(any("硬編碼" in f for f in results["Action 結構"]))

    def test_manifest_mismatch(self):
        (self.template / "actions" / "orphan.py").write_text(
            "def execute(ctx):\n    return None\n", encoding="utf-8")
        failures = audit_manifest(self.template)
        self.assertTrue(any("orphan" in f for f in failures))

    def test_manifest_declared_missing_file(self):
        manifest = {"check_status": {}, "ghost": {}}
        (self.template / "actions" / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8")
        failures = audit_manifest(self.template)
        self.assertTrue(any("ghost" in f for f in failures))

    def test_undeclared_secret_fails(self):
        (self.template / "actions" / "check_status.py").write_text(
            'def execute(ctx):\n    ctx.secrets.get("UNDECLARED")\n', encoding="utf-8")
        failures, _ = audit_secrets(self.template)
        self.assertTrue(any("UNDECLARED" in f for f in failures))

    def test_legacy_meta_key_fails(self):
        meta = json.loads((self.template / "_template_meta.json").read_text(encoding="utf-8"))
        meta["custom_objects_schema"] = [{"name": "舊"}]
        (self.template / "_template_meta.json").write_text(
            json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        failures = audit_legacy(self.template, self.rules["legacy"])
        self.assertTrue(any("custom_objects_schema" in f for f in failures))

    def test_legacy_api_fails(self):
        (self.template / "actions" / "check_status.py").write_text(
            'def execute(ctx):\n    ctx.secrets.get("API_KEY")\n'
            '    ctx.db.query_object("leads")\n', encoding="utf-8")
        failures = audit_legacy(self.template, self.rules["legacy"])
        self.assertTrue(any("舊制" in f for f in failures))

    def test_dsl_in_meta_validated(self):
        meta = json.loads((self.template / "_template_meta.json").read_text(encoding="utf-8"))
        meta["data_center_schema"] = {"version": 1, "tables": [
            {"key": "t", "display_name": "T", "fields": [
                {"key": "id", "display_name": "ID", "type": "text"}]}]}
        (self.template / "_template_meta.json").write_text(
            json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        failures, by = audit_dsl(self.template, None)
        self.assertEqual(by, "local")
        self.assertTrue(any("系統欄名" in f for f in failures))

    def test_forbidden_string(self):
        (self.template / "src" / "App.tsx").write_text(
            "// TODO_REMOVE\nexport default function App() { return null }\n",
            encoding="utf-8")
        results = run_audit(self.template, self.rules)
        self.assertTrue(results["禁止字串掃描"])

    def test_emoji_in_tsx(self):
        (self.template / "src" / "App.tsx").write_text(
            'export default function App() { return <div>🚀</div> }\n', encoding="utf-8")
        results = run_audit(self.template, self.rules)
        self.assertTrue(results["Emoji 限制"])


if __name__ == "__main__":
    unittest.main()
