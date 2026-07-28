import tempfile
import unittest
from pathlib import Path

import helpers  # noqa: F401
import common
from scan import scan_template


class TestScan(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.template = Path(self.tmp.name)
        (self.template / "actions").mkdir()
        self.rules = common.load_config("scan_rules.json")

    def tearDown(self):
        self.tmp.cleanup()

    def scan(self):
        return scan_template(self.template, self.rules)

    def test_hardcoded_credential_is_blocker(self):
        (self.template / "actions" / "bad.py").write_text(
            'api_key = "sk_live_abcdef123456"\n', encoding="utf-8")
        findings = self.scan()
        self.assertTrue(any(f["rule"] == "hardcoded_credentialish" and
                            f["severity"] == "blocker" for f in findings))

    def test_legacy_object_api_is_blocker(self):
        (self.template / "actions" / "old.py").write_text(
            'def execute(ctx):\n    rows = ctx.db.query_object("leads", limit=10)\n',
            encoding="utf-8")
        findings = self.scan()
        self.assertTrue(any(f["rule"] == "legacy_object_api" and
                            f["severity"] == "blocker" for f in findings))

    def test_secret_key_captured(self):
        (self.template / "actions" / "a.py").write_text(
            'def execute(ctx):\n    k = ctx.secrets.get("LINE_TOKEN")\n', encoding="utf-8")
        findings = self.scan()
        hits = [f for f in findings if f["rule"] == "secret_key_usage"]
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["captured"], "LINE_TOKEN")

    def test_uuid_in_tsx(self):
        (self.template / "src").mkdir()
        (self.template / "src" / "Page.tsx").write_text(
            'const OBJECT_ID = "123e4567-e89b-12d3-a456-426614174000"\n', encoding="utf-8")
        findings = self.scan()
        self.assertTrue(any(f["rule"] == "uuid_literal" for f in findings))

    def test_finding_id_stable_across_line_shifts(self):
        f = self.template / "actions" / "a.py"
        f.write_text('def execute(ctx):\n    k = ctx.secrets.get("X_KEY")\n', encoding="utf-8")
        id1 = [x for x in self.scan() if x["rule"] == "secret_key_usage"][0]["id"]
        # 前面插入其他行,行號位移但 id 不變
        f.write_text('import json\n\ndef execute(ctx):\n    k = ctx.secrets.get("X_KEY")\n',
                     encoding="utf-8")
        id2 = [x for x in self.scan() if x["rule"] == "secret_key_usage"][0]["id"]
        self.assertEqual(id1, id2)

    def test_extension_filter(self):
        (self.template / "notes.md").write_text(
            'api_key = "abcdef123456789"\n', encoding="utf-8")
        findings = self.scan()
        self.assertFalse(any(f["file"] == "notes.md" for f in findings))

    def test_exclude_patterns(self):
        (self.template / "src").mkdir(exist_ok=True)
        (self.template / "src" / "A.tsx").write_text(
            'const NS = "http://www.w3.org/2000/svg"\n', encoding="utf-8")
        findings = self.scan()
        self.assertFalse(any(f["rule"] == "hardcoded_url" for f in findings))


if __name__ == "__main__":
    unittest.main()
