"""S1 來源身分閘、repo URL 來源、S6 meta 人工閘。

這三者的共同點:出錯時**不會有任何錯誤訊息**——抽錯 app 會安靜地做出別人的模板、
URL 裡的 token 會安靜地留在狀態檔、AI 亂寫的門面文案會安靜地上架。故全部要有閘與測試。
"""
import io
import json
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import helpers  # noqa: F401
import acquire
import aigo_client
import common
import normalize_meta
from audit_local import audit_meta_gate

APP_INFO = {
    "id": "116832b1-528c-4f3a-8642-de8cc6a7b8fc",
    "name": "任務管理",
    "slug": "task_manager",
    "status": "published",
    "access_mode": "internal",
    "updated_at": "2026-07-28T10:00:00Z",
    "vfs_state": {"src/main.tsx": "x", "actions/send_notice.py": "y"},
}


class TestRepoUrl(unittest.TestCase):
    def test_url_forms_detected(self):
        for value in ("https://github.com/org/repo.git",
                      "http://gitlab.internal/org/repo",
                      "git@github.com:org/repo.git",
                      "ssh://git@host/org/repo.git",
                      "  https://github.com/org/repo  "):
            self.assertTrue(acquire.is_repo_url(value), value)

    def test_local_paths_not_urls(self):
        for value in ("C:/dev/repo", "/home/me/repo", "../repo", "repo", ""):
            self.assertFalse(acquire.is_repo_url(value), value)

    def test_credentials_redacted(self):
        self.assertEqual(acquire.redact("https://user:ghp_secret@github.com/org/repo.git"),
                         "https://github.com/org/repo.git")
        # 錯誤訊息裡夾帶的 URL 也要被清掉(clone 失敗時整段 stderr 會被印出來)
        self.assertNotIn("ghp_secret", acquire.redact(
            "fatal: could not read from https://x:ghp_secret@github.com/o/r.git"))

    def test_scp_form_untouched(self):
        self.assertEqual(acquire.redact("git@github.com:org/repo.git"),
                         "git@github.com:org/repo.git")

    @unittest.skipIf(shutil.which("git") is None, "需要 git")
    def test_clone_returns_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "origin"
            src.mkdir()
            run = lambda *a: subprocess.run(a, cwd=src, capture_output=True, check=True)  # noqa: E731
            run("git", "init", "-q")
            run("git", "config", "user.email", "t@example.com")
            run("git", "config", "user.name", "t")
            (src / "README.md").write_text("x", encoding="utf-8")
            run("git", "add", "-A")
            run("git", "commit", "-qm", "init")

            dest = Path(tmp) / "clone"
            with redirect_stdout(io.StringIO()):
                path, commit = acquire.clone_repo(str(src), dest, None)
            self.assertTrue((path / "README.md").exists())
            self.assertRegex(commit, r"^[0-9a-f]{12}$")

    @unittest.skipIf(shutil.which("git") is None, "需要 git")
    def test_clone_failure_is_fatal_and_redacted(self):
        with tempfile.TemporaryDirectory() as tmp:
            with redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as cm:
                    acquire.clone_repo("https://u:ghp_secret@127.0.0.1:1/o/r.git",
                                       Path(tmp) / "c", None)
            self.assertNotIn("ghp_secret", str(cm.exception))


class TestSourceIdentityGate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.work = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_decision_blocks(self):
        with self.assertRaises(SystemExit) as cm:
            acquire.require_source_decision(self.work, "t")
        self.assertIn("confirm-source", str(cm.exception))

    def test_ai_proposed_decision_blocks(self):
        common.save_decisions(self.work, {"source_app": {
            "app_id": APP_INFO["id"], "decided_by": "proposed"}})
        with self.assertRaises(SystemExit):
            acquire.require_source_decision(self.work, "t")

    def test_user_decision_passes(self):
        common.save_decisions(self.work, {"source_app": {
            "app_id": APP_INFO["id"], "app_slug": "task_manager", "decided_by": "user"}})
        entry = acquire.require_source_decision(self.work, "t")
        acquire.verify_source_identity(entry, APP_INFO)  # 不應拋錯

    def test_confirmed_other_app_blocks(self):
        """確認過 A、卻對 B 下手——uuid 打錯的實際樣子。"""
        entry = {"app_id": "00000000-0000-0000-0000-000000000000",
                 "app_slug": "另一支", "decided_by": "user"}
        with self.assertRaises(SystemExit) as cm:
            acquire.verify_source_identity(entry, APP_INFO)
        self.assertIn("身分不符", str(cm.exception))

    def test_identity_card_shows_uuid_and_actions(self):
        card = acquire.identity_card(APP_INFO)
        self.assertIn(APP_INFO["id"], card)
        self.assertIn("task_manager", card)
        self.assertIn("send_notice", card)

    def test_list_apps_prints_rows(self):
        with mock.patch.object(aigo_client, "api", return_value=(200, [APP_INFO])):
            buf = io.StringIO()
            with redirect_stdout(buf):
                acquire.list_apps({})
        out = buf.getvalue()
        self.assertIn("task_manager", out)
        self.assertIn(APP_INFO["id"], out)

    def test_list_apps_http_error_is_fatal(self):
        with mock.patch.object(aigo_client, "api", return_value=(403, {"detail": "no"})):
            with self.assertRaises(SystemExit):
                acquire.list_apps({})


class TestBuilderAccess(unittest.TestCase):
    def test_builder_permission(self):
        self.assertTrue(aigo_client.has_builder_access({"permissions": ["builder.access"]}))

    def test_system_admin_is_master_key(self):
        # 對齊平台 require_permission:system.admin 直接放行,不可誤判成「無權限」
        self.assertTrue(aigo_client.has_builder_access({"permissions": ["system.admin"]}))

    def test_without_permission(self):
        self.assertFalse(aigo_client.has_builder_access({"permissions": ["crm.read"]}))
        self.assertFalse(aigo_client.has_builder_access({}))


class TestMetaGate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.work = Path(self.tmp.name)
        self.template = self.work / "template"
        self.template.mkdir()
        self.meta_path = self.template / "_template_meta.json"
        common.dump_json(self.meta_path, {"slug": "t", "name": "測試模板"})

    def tearDown(self):
        self.tmp.cleanup()

    def approve(self):
        common.save_decisions(self.work, {"meta": {
            "meta_hash": common.file_hash(self.meta_path), "decided_by": "user"}})

    def test_missing_meta(self):
        self.meta_path.unlink()
        self.assertTrue(any("normalize_meta" in f
                            for f in audit_meta_gate(self.work, self.template)))

    def test_unconfirmed_blocks(self):
        failures = audit_meta_gate(self.work, self.template)
        self.assertTrue(any("confirm-meta" in f for f in failures))

    def test_proposed_is_not_confirmed(self):
        normalize_meta.record_meta_proposal(self.work, self.template)
        self.assertEqual(common.load_decisions(self.work)["meta"]["decided_by"], "proposed")
        self.assertTrue(audit_meta_gate(self.work, self.template))

    def test_confirmed_passes(self):
        self.approve()
        self.assertEqual(audit_meta_gate(self.work, self.template), [])

    def test_edit_after_confirm_blocks(self):
        """確認過的必須就是要推的那一份——確認後再改一個字就要重確認。"""
        self.approve()
        meta = json.loads(self.meta_path.read_text(encoding="utf-8"))
        meta["name"] = "偷改的名字"
        common.dump_json(self.meta_path, meta)
        failures = audit_meta_gate(self.work, self.template)
        self.assertTrue(any("雜湊不符" in f for f in failures))

    def test_rerun_with_same_content_keeps_approval(self):
        self.approve()
        needs_confirm = normalize_meta.record_meta_proposal(self.work, self.template)
        self.assertFalse(needs_confirm)
        self.assertEqual(common.load_decisions(self.work)["meta"]["decided_by"], "user")
        self.assertEqual(audit_meta_gate(self.work, self.template), [])

    def test_rerun_with_changed_content_revokes_approval(self):
        self.approve()
        common.dump_json(self.meta_path, {"slug": "t", "name": "改過的模板"})
        self.assertTrue(normalize_meta.record_meta_proposal(self.work, self.template))
        self.assertEqual(common.load_decisions(self.work)["meta"]["decided_by"], "proposed")


if __name__ == "__main__":
    unittest.main()
