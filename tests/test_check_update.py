import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import helpers  # noqa: F401  路徑設定
import check_update as cu

REMOTE_CHANGELOG = """# Changelog

## 9.9.9

- 新版重點一
- 新版重點二

## 0.1.0

- 舊版內容
"""


class TestVersionCompare(unittest.TestCase):
    def test_numeric_ordering(self):
        self.assertTrue(cu._is_newer("0.4.0", "0.3.9"))
        self.assertTrue(cu._is_newer("1.0.0", "0.9.9"))
        self.assertFalse(cu._is_newer("0.3.0", "0.3.0"))
        self.assertFalse(cu._is_newer("0.2.0", "0.3.0"))

    def test_prerelease_sorts_before_release(self):
        self.assertTrue(cu._is_newer("1.0.0", "1.0.0-rc1"))
        self.assertFalse(cu._is_newer("1.0.0-rc1", "1.0.0"))

    def test_garbage_remote_never_triggers_false_alarm(self):
        """遠端拿到非版號字串(抓到 HTML、404 頁面…)時,非數字段一律當 0
        → 比任何真實版號都舊 → 靜默不提示。寧可漏報也不要對使用者誤報更新。"""
        self.assertFalse(cu._is_newer("main", "0.1.0"))
        self.assertFalse(cu._is_newer("<!DOCTYPE html>", "0.1.0"))
        self.assertFalse(cu._is_newer("same", "same"))


class TestBomTolerance(unittest.TestCase):
    """Windows PowerShell 的 `Set-Content -Encoding utf8` / `Out-File` 預設寫 BOM。

    誰用它 bump 一次 VERSION,BOM 就會讓主版號被判成非數字而歸零
    (`1.0.0` → `(0,0,0)`),於是所有安裝者的自動更新從此靜靜地不再提示。
    2026-08-12 在模擬安裝者時實際踩到(`"local": "﻿0.6.4"`)。
    """

    def test_clean_version_strips_bom(self):
        self.assertEqual(cu._clean_version("﻿0.6.4\n"), "0.6.4")
        self.assertEqual(cu._clean_version("0.7.0\n"), "0.7.0")
        self.assertIsNone(cu._clean_version("﻿\n"))
        self.assertIsNone(cu._clean_version(""))

    def test_bom_does_not_zero_the_major(self):
        # 修好之前:_parse_version("﻿1.0.0") → (0,0,0),比 0.7.0 還舊
        self.assertTrue(cu._is_newer(cu._clean_version("﻿1.0.0"), "0.7.0"))

    def test_local_version_file_with_bom(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = Path(tmp)
            (skill / "VERSION").write_text("1.2.3\n", encoding="utf-8-sig")
            with mock.patch.object(cu, "SKILL_DIR", skill):
                self.assertEqual(cu._read_local_version(), "1.2.3")

    def test_remote_version_with_bom(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = Path(tmp)
            (skill / "VERSION").write_text("0.7.0\n", encoding="utf-8")
            with mock.patch.object(cu, "SKILL_DIR", skill), \
                 mock.patch.object(cu, "STATE_FILE", Path(tmp) / "s.json"), \
                 mock.patch.object(cu, "_fetch", return_value="﻿1.0.0\n"):
                result = cu.check(force=True)
        self.assertEqual(result["status"], "outdated")
        self.assertEqual(result["remote"], "1.0.0")


class TestChangelogExcerpt(unittest.TestCase):
    def test_extracts_only_target_section(self):
        with mock.patch.object(cu, "_fetch", return_value=REMOTE_CHANGELOG):
            text = cu._changelog_excerpt("9.9.9")
        self.assertIn("新版重點一", text)
        self.assertIn("新版重點二", text)
        self.assertNotIn("舊版內容", text)

    def test_missing_section_returns_none(self):
        with mock.patch.object(cu, "_fetch", return_value=REMOTE_CHANGELOG):
            self.assertIsNone(cu._changelog_excerpt("5.5.5"))

    def test_fetch_failure_returns_none(self):
        with mock.patch.object(cu, "_fetch", return_value=None):
            self.assertIsNone(cu._changelog_excerpt("9.9.9"))


class TestCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / "update_check.json"
        self._patch = mock.patch.object(cu, "STATE_FILE", self.state)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self.tmp.cleanup()

    def test_current_when_versions_match(self):
        with mock.patch.object(cu, "_read_local_version", return_value="1.0.0"), \
             mock.patch.object(cu, "_fetch", return_value="1.0.0\n"):
            result = cu.check(force=True)
        self.assertEqual(result["status"], "current")

    def test_outdated_reports_update_command(self):
        with mock.patch.object(cu, "_read_local_version", return_value="1.0.0"), \
             mock.patch.object(cu, "_fetch", side_effect=["2.0.0\n", REMOTE_CHANGELOG]):
            result = cu.check(force=True)
        self.assertEqual(result["status"], "outdated")
        self.assertEqual(result["remote"], "2.0.0")
        self.assertIn("update_command", result)

    def test_offline_does_not_burn_throttle(self):
        """離線那次不可寫 last_check——否則斷網一次要等 24h 才會再檢查。"""
        with mock.patch.object(cu, "_read_local_version", return_value="1.0.0"), \
             mock.patch.object(cu, "_fetch", return_value=None):
            result = cu.check(force=True)
        self.assertEqual(result["status"], "unknown")
        self.assertFalse(self.state.exists(), "離線時不應寫入節流狀態")

    def test_successful_check_writes_throttle(self):
        with mock.patch.object(cu, "_read_local_version", return_value="1.0.0"), \
             mock.patch.object(cu, "_fetch", return_value="1.0.0\n"):
            cu.check(force=True)
        self.assertTrue(self.state.exists())
        self.assertIn("last_check", json.loads(self.state.read_text(encoding="utf-8")))

    def test_throttled_skips_without_network(self):
        self.state.write_text(json.dumps({"last_check": time.time()}), encoding="utf-8")
        fetch = mock.Mock()
        with mock.patch.object(cu, "_read_local_version", return_value="1.0.0"), \
             mock.patch.object(cu, "_fetch", fetch):
            result = cu.check(force=False)
        self.assertEqual(result["status"], "skipped")
        fetch.assert_not_called()

    def test_stale_state_allows_check(self):
        old = time.time() - (cu.THROTTLE_SECONDS + 60)
        self.state.write_text(json.dumps({"last_check": old}), encoding="utf-8")
        with mock.patch.object(cu, "_read_local_version", return_value="1.0.0"), \
             mock.patch.object(cu, "_fetch", return_value="1.0.0\n"):
            result = cu.check(force=False)
        self.assertEqual(result["status"], "current")

    def test_corrupt_state_is_not_fatal(self):
        self.state.write_text("{ not json", encoding="utf-8")
        with mock.patch.object(cu, "_read_local_version", return_value="1.0.0"), \
             mock.patch.object(cu, "_fetch", return_value="1.0.0\n"):
            result = cu.check(force=False)
        self.assertEqual(result["status"], "current")

    def test_missing_local_version_is_unknown(self):
        with mock.patch.object(cu, "_read_local_version", return_value=None):
            result = cu.check(force=True)
        self.assertEqual(result["status"], "unknown")


class TestUpdateCommand(unittest.TestCase):
    def test_git_install_uses_pull_ff_only(self):
        with mock.patch.object(cu, "_install_method", return_value="git"):
            self.assertIn("pull --ff-only", cu._update_command("git"))

    def test_copy_install_uses_skills_cli(self):
        self.assertIn("npx skills update", cu._update_command("copy"))

    def test_apply_on_copy_install_refuses(self):
        ok, msg = cu._apply_update("copy")
        self.assertFalse(ok)
        self.assertIn("npx skills update", msg)


class TestRepoWiring(unittest.TestCase):
    """腳本指向的必須是本 repo,且 VERSION 檔真的讀得到(vendor 自 builder 時最易漏改)。"""

    def test_repo_is_this_skill(self):
        self.assertEqual(cu.REPO, "AI-GO-APP/aigo-template-transfer-skill")

    def test_local_version_readable(self):
        self.assertIsNotNone(cu._read_local_version())


if __name__ == "__main__":
    unittest.main()
