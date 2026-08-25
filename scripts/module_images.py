#!/usr/bin/env python3
"""S10:商城展示圖(banner + 介面截圖)的狀態查詢、循序上傳與回讀驗證。

    python scripts/module_images.py status --slug my_template
    python scripts/module_images.py upload --slug my_template --dir ./shots
    python scripts/module_images.py verify --slug my_template --dir ./shots
    python scripts/module_images.py clear  --slug my_template   # 互動確認

規則(見 references/marketplace-images.md):

- **順序即上傳順序**:AI GO 是附加語意,第一張是封面。banner(序號 00)必須先送。
- **★不重試**:結果不明時重打會多出一張分身圖。失敗一律停下來交給人判斷。
- **驗證不能用檔名**:AI GO 會把 key 換成雜湊,只能比對內容(HEAD 比大小)。
- **只對上架中的模組開放**:未上架一律 409。
"""
import argparse
import mimetypes
import os
import re
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common
from devportal import api

MAX_BYTES = 5 * 1024 * 1024
MAX_IMAGES = 10
BANNER_INDEX = 0
IDX_RE = re.compile(r"^(?P<idx>\d{2})-.*\.(png|jpg|jpeg|webp)$", re.I)


def module_id_for(env: dict, slug: str) -> str:
    """slug → module_id。用平台清單精確比對,不做模糊猜測。"""
    status, payload = api(env, "GET", "/modules?limit=500")
    items = payload if isinstance(payload, list) else (payload or {}).get("items") or []
    for it in items:
        if it.get("slug") == slug:
            return it["id"]
    raise SystemExit(f"[FAIL] 平台上找不到 slug={slug} 的模組")


def collect(directory: Path, slug: str) -> list[tuple[int, Path]]:
    """挑出屬於這支模組的圖,依序號排序。

    ★ slug 用最長前綴精確比對:架上有 food-order-pos / food-order-center /
    food-order-hub 這種相似組合,短的先比會把長的檔案搶走,傳到錯的模組上。
    這裡只收「檔名去掉 slug- 之後緊接兩位數序號」的檔案,等價於精確比對;
    序號之後的描述段可以含 -數字-(如 16-9、日期),不影響歸屬判定。
    """
    prefix = slug + "-"
    found: list[tuple[int, Path]] = []
    for p in sorted(directory.iterdir()):
        if not p.is_file() or not p.name.startswith(prefix):
            continue
        m = IDX_RE.match(p.name[len(prefix):])
        if not m:
            continue
        found.append((int(m.group("idx")), p))
    found.sort(key=lambda x: x[0])
    return found


def preflight(items: list[tuple[int, Path]]) -> list[str]:
    """把可預見的失敗擋在送出之前——上傳不能重試,錯了就得整支清掉重來。"""
    problems = []
    if not items:
        return ["找不到任何圖片(檔名須為 <slug>-<兩位序號>-<說明>.png)"]
    if items[0][0] != BANNER_INDEX:
        problems.append(f"第一張不是 banner(序號 00),而是 {items[0][1].name}")
    if len(items) > MAX_IMAGES:
        problems.append(f"共 {len(items)} 張,超過每模組 {MAX_IMAGES} 張上限")
    for idx, p in items:
        size = p.stat().st_size
        if size > MAX_BYTES:
            problems.append(f"{p.name} 為 {size} bytes,超過 5 MiB 上限")
    dup = [i for i, _ in items if [x for x, _ in items].count(i) > 1]
    if dup:
        problems.append(f"序號重複:{sorted(set(dup))}")
    return problems


def list_images(env: dict, module_id: str) -> list[dict]:
    status, payload = api(env, "GET", f"/modules/{module_id}/images")
    if status != 200:
        raise SystemExit(f"[FAIL] 讀取展示圖清單失敗(HTTP {status}):{payload}")
    return (payload or {}).get("images") or []


def post_image(env: dict, module_id: str, path: Path) -> tuple[bool, str]:
    """multipart 上傳單張。★ 絕不重試:結果不明時重打會多一張分身圖。"""
    ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    data = path.read_bytes()
    boundary = "----aigo" + uuid.uuid4().hex
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
        f"Content-Type: {ctype}\r\n\r\n"
    ).encode() + data + f"\r\n--{boundary}--\r\n".encode()

    url = env["DEVPORTAL_API"].rstrip("/") + f"/modules/{module_id}/images"
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Authorization", "Bearer " + env["DEVPORTAL_PAT"])
    req.add_header("Content-Type", "multipart/form-data; boundary=" + boundary)
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            resp.read()
        return True, "ok"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}:{e.read().decode()[:300]}"
    except Exception as e:                                      # noqa: BLE001
        return False, f"連線失敗(結果不明,未重試):{e}"


def head_size(url: str) -> int | None:
    req = urllib.request.Request(url, method="HEAD",
                                 headers={"User-Agent": "aigo-template-transfer"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            n = r.headers.get("Content-Length")
            return int(n) if n else None
    except Exception:                                           # noqa: BLE001
        return None


def verify(env: dict, module_id: str, items: list[tuple[int, Path]]) -> list[str]:
    """回讀驗證張數與逐張順序。

    ★ 不能用檔名驗:AI GO 會把 key 換成 templates/<slug>/<hash>.png,
    原始檔名不保留。改比對遠端大小與本地順序。
    """
    remote = list_images(env, module_id)
    if len(remote) != len(items):
        return [f"回讀 {len(remote)} 張,與本地 {len(items)} 張不符"]
    bad = []
    for i, (img, (_, path)) in enumerate(zip(remote, items)):
        want = path.stat().st_size
        got = head_size(img.get("url") or "")
        if got is None:
            bad.append(f"#{i} 取不到遠端大小")
        elif got != want:
            bad.append(f"#{i} {path.name} 期望 {want} 實得 {got}")
    return bad


def cmd_status(args) -> None:
    env = common.load_env()
    mid = module_id_for(env, args.slug)
    images = list_images(env, mid)
    print(f"{args.slug}:平台上有 {len(images)} 張展示圖")
    for i, im in enumerate(images):
        print(f"  {i:2d}  {im.get('key')}")
    if not images:
        print("→ 沒有任何展示圖,依常態規則應嘗試截圖並上傳(失敗不擋發版)")


def cmd_upload(args) -> None:
    env = common.load_env()
    directory = Path(args.dir).resolve()
    items = collect(directory, args.slug)
    problems = preflight(items)
    if problems:
        raise SystemExit("[FAIL] 上傳前檢查未過:\n  - " + "\n  - ".join(problems))

    mid = module_id_for(env, args.slug)
    existing = list_images(env, mid)
    if existing and not args.force:
        print(f"[SKIP] {args.slug} 已有 {len(existing)} 張展示圖——"
              f"常態規則是有圖就不再補傳。要重來請先 clear。")
        return

    print(f"上傳 {len(items)} 張(封面 {items[0][1].name}):")
    for idx, path in items:
        ok, msg = post_image(env, mid, path)
        if not ok:
            raise SystemExit(
                f"[FAIL] {path.name} 上傳失敗:{msg}\n"
                f"★ 上傳不重試。已送出 {items.index((idx, path))} 張,"
                f"要重來請先 `clear --slug {args.slug}` 清空再整支重傳。")
        print(f"  [OK] {idx:02d} {path.name}")

    bad = verify(env, mid, items)
    if bad:
        raise SystemExit("[FAIL] 回讀驗證未過:\n  - " + "\n  - ".join(bad))
    print(f"[OK] {len(items)} 張,順序正確(封面 {items[0][1].name})")


def cmd_verify(args) -> None:
    env = common.load_env()
    items = collect(Path(args.dir).resolve(), args.slug)
    if not items:
        raise SystemExit("[FAIL] 本地找不到圖片,無從比對")
    mid = module_id_for(env, args.slug)
    bad = verify(env, mid, items)
    if bad:
        raise SystemExit("[FAIL] 驗證未過:\n  - " + "\n  - ".join(bad))
    print(f"[OK] {args.slug}:{len(items)} 張,順序正確")


def cmd_clear(args) -> None:
    env = common.load_env()
    mid = module_id_for(env, args.slug)
    images = list_images(env, mid)
    if not images:
        print("沒有展示圖可清除")
        return
    print(f"即將刪除 {args.slug} 的 {len(images)} 張展示圖(不可復原)")
    if input("輸入 yes 確認:").strip() != "yes":
        raise SystemExit("已取消")
    for im in images:
        status, payload = api(env, "DELETE",
                              f"/modules/{mid}/images?key={im.get('key')}")
        if status not in (200, 204):
            raise SystemExit(f"[FAIL] 刪除 {im.get('key')} 失敗(HTTP {status}):{payload}")
        print(f"  [OK] 已刪除 {im.get('key')}")


def main() -> None:
    common.bootstrap()
    p = argparse.ArgumentParser(description="商城展示圖(S10)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("status", help="查平台上現有幾張")
    s.add_argument("--slug", required=True)
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("upload", help="依序上傳(banner 先)")
    s.add_argument("--slug", required=True)
    s.add_argument("--dir", required=True, help="圖片資料夾")
    s.add_argument("--force", action="store_true", help="已有圖也照傳(會附加,慎用)")
    s.set_defaults(func=cmd_upload)

    s = sub.add_parser("verify", help="回讀驗證張數與順序")
    s.add_argument("--slug", required=True)
    s.add_argument("--dir", required=True)
    s.set_defaults(func=cmd_verify)

    s = sub.add_parser("clear", help="清空該模組全部展示圖(互動確認)")
    s.add_argument("--slug", required=True)
    s.set_defaults(func=cmd_clear)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
