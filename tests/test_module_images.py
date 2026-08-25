"""商城展示圖(S10)的純函式:檔名解析、順序、上傳前檢查。

要釘住的行為:

1. **順序由序號決定,banner(00)必須第一張**——AI GO 是附加語意,
   上傳順序就是商城顯示順序,送錯順序封面就錯。
2. **slug 用精確比對**——架上有 food-order-pos / food-order-center /
   food-order-hub 這種相似組合,短前綴會把長的檔案搶走,傳到錯的模組上。
3. **可預見的失敗要在送出前擋掉**——上傳不能重試,錯了得整支清空重來,
   所以張數、大小、序號重複都要先驗。
"""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import helpers  # noqa: F401
import module_images as mi


def _touch(d: Path, name: str, size: int = 16) -> Path:
    p = d / name
    p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * max(0, size - 8))
    return p


class CollectTest(unittest.TestCase):
    def test_orders_by_index_with_banner_first(self):
        with TemporaryDirectory() as td:
            d = Path(td)
            _touch(d, "demo-02-列表.png")
            _touch(d, "demo-00-情境主視覺.png")
            _touch(d, "demo-01-總覽.png")
            got = [p.name for _, p in mi.collect(d, "demo")]
            self.assertEqual(got,
                             ["demo-00-情境主視覺.png", "demo-01-總覽.png", "demo-02-列表.png"])

    def test_similar_slugs_do_not_steal_each_other(self):
        """food-order 不可以撈走 food-order-pos 的檔案,反之亦然。"""
        with TemporaryDirectory() as td:
            d = Path(td)
            _touch(d, "food-order-pos-00-banner.png")
            _touch(d, "food-order-pos-01-菜單.png")
            _touch(d, "food-order-center-00-banner.png")
            _touch(d, "food-order-hub-00-banner.png")
            pos = [p.name for _, p in mi.collect(d, "food-order-pos")]
            center = [p.name for _, p in mi.collect(d, "food-order-center")]
            self.assertEqual(pos,
                             ["food-order-pos-00-banner.png", "food-order-pos-01-菜單.png"])
            self.assertEqual(center, ["food-order-center-00-banner.png"])
            # 不存在的短 slug 不該撈到任何東西
            self.assertEqual(mi.collect(d, "food-order"), [])

    def test_ignores_files_without_index(self):
        with TemporaryDirectory() as td:
            d = Path(td)
            _touch(d, "demo-00-banner.png")
            _touch(d, "demo-notes.txt")
            _touch(d, "demo-封面.png")          # 沒有兩位序號
            self.assertEqual(len(mi.collect(d, "demo")), 1)


class PreflightTest(unittest.TestCase):
    def _items(self, d, names):
        for n in names:
            _touch(d, n)
        return mi.collect(d, "demo")

    def test_ok(self):
        with TemporaryDirectory() as td:
            d = Path(td)
            items = self._items(d, ["demo-00-b.png", "demo-01-a.png", "demo-02-c.png"])
            self.assertEqual(mi.preflight(items), [])

    def test_missing_banner_is_rejected(self):
        with TemporaryDirectory() as td:
            d = Path(td)
            items = self._items(d, ["demo-01-a.png", "demo-02-c.png"])
            self.assertTrue(any("banner" in m for m in mi.preflight(items)))

    def test_empty_is_rejected(self):
        self.assertTrue(mi.preflight([]))

    def test_over_ten_images_is_rejected(self):
        with TemporaryDirectory() as td:
            d = Path(td)
            names = ["demo-%02d-x.png" % i for i in range(11)]
            items = self._items(d, names)
            self.assertTrue(any("上限" in m for m in mi.preflight(items)))

    def test_oversize_is_rejected_before_upload(self):
        """5 MiB 是可預見的 413;上傳不能重試,所以要在送出前就擋掉。"""
        with TemporaryDirectory() as td:
            d = Path(td)
            _touch(d, "demo-00-b.png")
            _touch(d, "demo-01-big.png", size=mi.MAX_BYTES + 1)
            items = mi.collect(d, "demo")
            self.assertTrue(any("5 MiB" in m for m in mi.preflight(items)))

    def test_duplicate_index_is_rejected(self):
        with TemporaryDirectory() as td:
            d = Path(td)
            _touch(d, "demo-00-b.png")
            _touch(d, "demo-01-a.png")
            _touch(d, "demo-01-b.png")
            items = mi.collect(d, "demo")
            self.assertTrue(any("序號重複" in m for m in mi.preflight(items)))


if __name__ == "__main__":
    unittest.main()
