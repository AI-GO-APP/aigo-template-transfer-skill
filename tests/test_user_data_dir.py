"""使用者資料目錄與舊版搬遷。

背景:0.6.2 之前 .env / token 快取 / work/ 都放在 skill 目錄內,
複製式安裝(`npx skills add`)更新時整個目錄被 rm -rf 重鋪 → 用戶資料無聲消失。

這裡的每個測試都必須把 USER_DIR 與 LEGACY_* 同時導到 tmpdir——
只導一半會讓 migrate_legacy_user_data() 去搬**開發者本機真實的** work/。
"""
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from importlib import reload
from pathlib import Path
from unittest import mock

import helpers  # noqa: F401
import common


class UserDataDirTestCase(unittest.TestCase):
    """把 common 的新舊路徑全部關進 tmpdir。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.user_dir = root / "home" / ".aigo-transfer"
        self.skill_dir = root / "skill"
        self.skill_dir.mkdir(parents=True)

        self.patches = mock.patch.multiple(
            common,
            USER_DIR=self.user_dir,
            ENV_FILE=self.user_dir / ".env",
            WORK_ROOT=self.user_dir / "work",
            TOKEN_CACHE_FILE=self.user_dir / "token.json",
            LEGACY_ENV_FILE=self.skill_dir / ".env",
            LEGACY_WORK_ROOT=self.skill_dir / "work",
            LEGACY_TOKEN_DIR=self.skill_dir / ".aigo",
            LEGACY_TOKEN_FILE=self.skill_dir / ".aigo" / "token.json",
        )
        self.patches.start()

    def tearDown(self):
        self.patches.stop()
        self.tmp.cleanup()

    def seed_legacy(self, *, env="DEVPORTAL_PAT=aigodev_old\n", token=True, slugs=("app_a",)):
        if env is not None:
            common.LEGACY_ENV_FILE.write_text(env, encoding="utf-8")
        if token:
            common.LEGACY_TOKEN_DIR.mkdir(parents=True, exist_ok=True)
            common.LEGACY_TOKEN_FILE.write_text(json.dumps({"access_token": "t"}), encoding="utf-8")
        for slug in slugs:
            work = common.LEGACY_WORK_ROOT / slug
            work.mkdir(parents=True, exist_ok=True)
            (work / "transfer_state.json").write_text(
                json.dumps({"slug": slug}), encoding="utf-8")


class TestResolveUserDir(unittest.TestCase):
    def test_defaults_to_home(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(common.HOME_OVERRIDE_KEY, None)
            self.assertEqual(common._resolve_user_dir(), Path.home() / ".aigo-transfer")

    def test_env_override_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {common.HOME_OVERRIDE_KEY: tmp}):
                self.assertEqual(common._resolve_user_dir(), Path(tmp).resolve())

    def test_module_constants_follow_override(self):
        """常數在 import 時算好,覆寫必須在 reload 後生效(CI 用得到)。"""
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {common.HOME_OVERRIDE_KEY: tmp}):
                mod = reload(common)
                try:
                    self.assertEqual(mod.ENV_FILE, Path(tmp).resolve() / ".env")
                    self.assertEqual(mod.WORK_ROOT, Path(tmp).resolve() / "work")
                finally:
                    reload(common)  # 還原,免得污染其他測試

    def test_user_dir_is_outside_skill_dir(self):
        """本次修復的核心不變式:使用者資料不得落在 skill 目錄內。"""
        self.assertFalse(str(common.USER_DIR).startswith(str(common.REPO_ROOT) + os.sep))
        for p in (common.ENV_FILE, common.WORK_ROOT, common.TOKEN_CACHE_FILE):
            self.assertFalse(str(p).startswith(str(common.REPO_ROOT) + os.sep), p)


class TestMigration(UserDataDirTestCase):
    def test_moves_env_token_and_work(self):
        self.seed_legacy(slugs=("app_a", "app_b"))
        notes = common.migrate_legacy_user_data()

        self.assertEqual(common.ENV_FILE.read_text(encoding="utf-8"), "DEVPORTAL_PAT=aigodev_old\n")
        self.assertTrue(common.TOKEN_CACHE_FILE.exists())
        self.assertTrue((common.WORK_ROOT / "app_a" / "transfer_state.json").exists())
        self.assertTrue((common.WORK_ROOT / "app_b" / "transfer_state.json").exists())
        # 舊路徑清空,空殼目錄收掉
        self.assertFalse(common.LEGACY_ENV_FILE.exists())
        self.assertFalse(common.LEGACY_WORK_ROOT.exists())
        self.assertFalse(common.LEGACY_TOKEN_DIR.exists())
        self.assertEqual(len(notes), 4)

    def test_idempotent(self):
        self.seed_legacy()
        common.migrate_legacy_user_data()
        self.assertEqual(common.migrate_legacy_user_data(), [])

    def test_noop_on_clean_install(self):
        self.assertEqual(common.migrate_legacy_user_data(), [])
        self.assertFalse(common.ENV_FILE.exists())

    def test_never_overwrites_existing(self):
        """新舊都有 .env 時,新的必須原封不動,舊的留在原地待用戶處置。"""
        common.ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
        common.ENV_FILE.write_text("DEVPORTAL_PAT=aigodev_new\n", encoding="utf-8")
        self.seed_legacy(token=False, slugs=())

        notes = common.migrate_legacy_user_data()

        self.assertEqual(common.ENV_FILE.read_text(encoding="utf-8"), "DEVPORTAL_PAT=aigodev_new\n")
        self.assertTrue(common.LEGACY_ENV_FILE.exists(), "衝突時不得刪除舊檔")
        self.assertTrue(any("兩份都存在" in n for n in notes))

    def test_work_slug_conflict_keeps_both(self):
        self.seed_legacy(env=None, token=False, slugs=("app_a",))
        (common.WORK_ROOT / "app_a").mkdir(parents=True)
        (common.WORK_ROOT / "app_a" / "transfer_state.json").write_text("{}", encoding="utf-8")

        notes = common.migrate_legacy_user_data()

        self.assertTrue((common.LEGACY_WORK_ROOT / "app_a").is_dir())
        self.assertTrue(any("app_a" in n and "兩份都存在" in n for n in notes))

    def test_move_failure_is_reported_not_raised(self):
        self.seed_legacy(token=False, slugs=())
        with mock.patch.object(common.shutil, "move", side_effect=OSError("跨磁碟失敗")):
            notes = common.migrate_legacy_user_data()
        self.assertTrue(any("搬移失敗" in n for n in notes))
        self.assertTrue(common.LEGACY_ENV_FILE.exists(), "搬移失敗時舊檔必須留著")


class TestFallbackReads(UserDataDirTestCase):
    """沒跑 bootstrap 就直接呼叫 API 時,仍要讀得到尚未搬遷的舊資料。"""

    def test_load_env_falls_back_to_legacy(self):
        self.seed_legacy(env="DEVPORTAL_PAT=aigodev_legacy\n", token=False, slugs=())
        self.assertEqual(common.load_env()["DEVPORTAL_PAT"], "aigodev_legacy")

    def test_load_env_prefers_new_location(self):
        self.seed_legacy(env="DEVPORTAL_PAT=aigodev_legacy\n", token=False, slugs=())
        common.ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
        common.ENV_FILE.write_text("DEVPORTAL_PAT=aigodev_new\n", encoding="utf-8")
        self.assertEqual(common.load_env()["DEVPORTAL_PAT"], "aigodev_new")

    def test_work_dir_falls_back_to_legacy(self):
        self.seed_legacy(env=None, token=False, slugs=("app_a",))
        self.assertEqual(common.work_dir("app_a"), common.LEGACY_WORK_ROOT / "app_a")

    def test_work_dir_uses_new_location_after_migration(self):
        self.seed_legacy(env=None, token=False, slugs=("app_a",))
        common.migrate_legacy_user_data()
        self.assertEqual(common.work_dir("app_a"), common.WORK_ROOT / "app_a")

    def test_work_dir_new_slug_goes_to_new_root(self):
        self.assertEqual(common.work_dir("brand_new"), common.WORK_ROOT / "brand_new")


class TestBootstrap(UserDataDirTestCase):
    def setUp(self):
        super().setUp()
        # utf8_stdout() 會把 sys.stdout 換成新的 TextIOWrapper,和 pytest 的
        # 輸出捕捉互相打架;這裡要驗的是遷移與目錄建立,編碼設定另有其職。
        self._no_utf8 = mock.patch.object(common, "utf8_stdout")
        self._no_utf8.start()

    def tearDown(self):
        self._no_utf8.stop()
        super().tearDown()

    def test_creates_dir_and_reports_to_stderr(self):
        """遷移提示不得寫進 stdout——多支 CLI 的 stdout 是給機器讀的 JSON。"""
        self.seed_legacy()
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            common.bootstrap()

        self.assertTrue(self.user_dir.is_dir())
        self.assertIn("[遷移]", err.getvalue())
        self.assertEqual(out.getvalue(), "")

    def test_quiet_on_clean_install(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            common.bootstrap()
        self.assertEqual(err.getvalue(), "")

    def test_survives_unwritable_home(self):
        with mock.patch.object(Path, "mkdir", side_effect=OSError("唯讀")), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            common.bootstrap()  # 不得拋出


class TestWriteEnv(UserDataDirTestCase):
    def test_creates_parent_dirs(self):
        common.write_env("DEVPORTAL_PAT=x\n")
        self.assertEqual(common.ENV_FILE.read_text(encoding="utf-8"), "DEVPORTAL_PAT=x\n")


if __name__ == "__main__":
    unittest.main()
