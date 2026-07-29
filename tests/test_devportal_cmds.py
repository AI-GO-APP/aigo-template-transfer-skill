"""bump / withdraw 的狀態機記帳。

這兩支的成功路徑在真平台上不好驗——bump 需要一支**已發布**版本(等於要把測試
模板推上架),withdraw 需要送審中的版本。故以 stub 掉 api() 的方式驗本地記帳:
新版本要成為 S7 的目標,且 S8/S9 必須重置(新版本沒測過,不能沿用舊綠燈)。
"""
import argparse
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import helpers  # noqa: F401
import common
import devportal


def state_with_s7(module_id="m-1", version_id="v-old"):
    state = {"slug": "t", "created_at": "2026-07-29T00:00:00", "last_hash": None,
             "stages": {s: {"status": "passed"} for s in common.STAGES}}
    state["stages"]["S7_draft"] = {"status": "passed", "module_id": module_id,
                                   "version_id": version_id, "version": "1.0.0"}
    return state


class BumpWithdrawBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.work = self.root / "work" / "t"
        self.work.mkdir(parents=True)
        common.save_state(self.work, state_with_s7())
        self._wd = mock.patch.object(common, "work_dir", lambda slug: self.work)
        self._wd.start()
        self._env = mock.patch.object(common, "load_env", lambda: {"DEVPORTAL_PAT": "x"})
        self._env.start()

    def tearDown(self):
        self._wd.stop()
        self._env.stop()
        self.tmp.cleanup()

    def state(self):
        return common.load_state(self.work)


class TestBump(BumpWithdrawBase):
    def test_new_version_becomes_target_and_resets_downstream(self):
        args = argparse.Namespace(slug="t", kind="minor", empty=False)
        with mock.patch.object(devportal, "api", return_value=(
                201, {"id": "v-new", "version": "1.1.0", "state": "draft"})):
            devportal.cmd_bump(args)
        s = self.state()
        self.assertEqual(s["stages"]["S7_draft"]["version_id"], "v-new")
        self.assertEqual(s["stages"]["S7_draft"]["version"], "1.1.0")
        self.assertEqual(s["stages"]["S7_draft"]["status"], "passed")
        # 新版本沒測過,舊的綠燈不可沿用
        self.assertEqual(s["stages"]["S8_e2e"]["status"], "pending")
        self.assertEqual(s["stages"]["S9_submit"]["status"], "pending")

    def test_sends_kind_and_copy_files(self):
        args = argparse.Namespace(slug="t", kind="major", empty=True)
        with mock.patch.object(devportal, "api", return_value=(
                201, {"id": "v2", "version": "2.0.0", "state": "draft"})) as spy:
            devportal.cmd_bump(args)
        _, method, path = spy.call_args.args
        self.assertEqual((method, path), ("POST", "/modules/m-1/versions"))
        self.assertEqual(spy.call_args.kwargs["body"],
                         {"kind": "major", "copy_files": False})

    def test_409_aborts_without_touching_state(self):
        args = argparse.Namespace(slug="t", kind="minor", empty=False)
        with mock.patch.object(devportal, "api", return_value=(409, {"detail": "已有進行中的版本"})):
            with self.assertRaises(SystemExit):
                devportal.cmd_bump(args)
        self.assertEqual(self.state()["stages"]["S7_draft"]["version_id"], "v-old")

    def test_requires_pushed_module(self):
        common.save_state(self.work, {"slug": "t", "created_at": "x", "last_hash": None,
                                      "stages": {s: {"status": "pending"} for s in common.STAGES}})
        with self.assertRaises(SystemExit):
            devportal.cmd_bump(argparse.Namespace(slug="t", kind="minor", empty=False))


class TestWithdraw(BumpWithdrawBase):
    def test_resets_s9_after_readback_confirms(self):
        common.save_state(self.work, {**self.state(),
                                      "stages": {**self.state()["stages"],
                                                 "S9_submit": {"status": "passed"}}})
        responses = [(200, {"withdrawn": True}),
                     (200, {"versions": [{"id": "v-old", "state": "draft"}]})]
        with mock.patch.object(devportal, "api", side_effect=responses):
            devportal.cmd_withdraw(argparse.Namespace(slug="t"))
        self.assertEqual(self.state()["stages"]["S9_submit"]["status"], "pending")

    def test_readback_still_submitted_is_fatal(self):
        responses = [(200, {"withdrawn": True}),
                     (200, {"versions": [{"id": "v-old", "state": "submitted"}]})]
        with mock.patch.object(devportal, "api", side_effect=responses):
            with self.assertRaises(SystemExit):
                devportal.cmd_withdraw(argparse.Namespace(slug="t"))


if __name__ == "__main__":
    unittest.main()
