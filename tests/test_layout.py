import tempfile
import unittest
from pathlib import Path

import helpers  # noqa: F401
import common
from acquire import detect_layout


def make_vfs(root: Path):
    (root / "src").mkdir(parents=True)
    (root / "src" / "main.tsx").write_text("//", encoding="utf-8")


class TestLayoutDetection(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.cfg = common.load_config("layout_profiles.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_root_layout(self):
        make_vfs(self.repo)
        root, name = detect_layout(self.repo, self.cfg, None)
        self.assertEqual(name, "root")
        self.assertEqual(root, self.repo)

    def test_app_subdir_layout(self):
        make_vfs(self.repo / "app")
        root, name = detect_layout(self.repo, self.cfg, None)
        self.assertEqual(name, "app")

    def test_aigo_layout(self):
        make_vfs(self.repo / "aigo")
        _, name = detect_layout(self.repo, self.cfg, None)
        self.assertEqual(name, "aigo")

    def test_vfs_single_layout(self):
        make_vfs(self.repo / "vfs")
        _, name = detect_layout(self.repo, self.cfg, None)
        self.assertEqual(name, "vfs")

    def test_vfs_multi_requires_subdir(self):
        make_vfs(self.repo / "vfs" / "admin")
        make_vfs(self.repo / "vfs" / "portal")
        with self.assertRaises(SystemExit):
            detect_layout(self.repo, self.cfg, None)
        root, name = detect_layout(self.repo, self.cfg, "admin")
        self.assertEqual(name, "vfs-multi:admin")
        self.assertEqual(root.name, "admin")

    def test_undetectable_layout(self):
        (self.repo / "whatever").mkdir()
        with self.assertRaises(SystemExit):
            detect_layout(self.repo, self.cfg, None)


if __name__ == "__main__":
    unittest.main()
