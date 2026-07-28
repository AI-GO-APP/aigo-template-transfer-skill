"""check_update.py — Skill 自我更新檢查(設計對齊 aigo-app-builder-skill)。

比對本地 `VERSION` 與 GitHub 上的遠端 `VERSION`,有新版時提示更新指令。

設計約束(改動前請先讀):
- **零相依**:只用標準函式庫,不經 uv/httpx。SessionStart hook 會在任何專案裡跑,
  不能假設 venv 已建好。
- **永不阻斷**:網路失敗、逾時、遠端格式異常一律靜默跳過並 exit 0。
- **節流**:預設 24 小時內只檢查一次,狀態存在 `~/.aigo-transfer/update_check.json`。
- **不自動覆寫**:`--apply` 只在 skill 目錄是 git repo 時做 `pull --ff-only`;
  其餘情況只印出指令,由使用者決定。

用法:
    python scripts/check_update.py              # 檢查(含節流),有更新才輸出
    python scripts/check_update.py --force      # 忽略節流
    python scripts/check_update.py --json       # 機器可讀輸出
    python scripts/check_update.py --apply      # 檢查後嘗試就地更新(git 安裝才會實際執行)
"""
import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = "AI-GO-APP/aigo-template-transfer-skill"
RAW_BASE = f"https://raw.githubusercontent.com/{REPO}/main"
REMOTE_VERSION_URL = f"{RAW_BASE}/VERSION"
REMOTE_CHANGELOG_URL = f"{RAW_BASE}/CHANGELOG.md"

SKILL_DIR = Path(__file__).resolve().parent.parent
STATE_FILE = Path.home() / ".aigo-transfer" / "update_check.json"

FETCH_TIMEOUT = 3.0  # 秒;hook 情境下寧可放棄也不要卡住啟動
THROTTLE_SECONDS = 24 * 60 * 60
CHANGELOG_MAX_LINES = 20


def _read_local_version() -> str | None:
    try:
        text = (SKILL_DIR / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text.splitlines()[0].strip() if text else None


def _fetch(url: str) -> str | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "aigo-template-transfer-skill"})
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
            if resp.status != 200:
                return None
            return resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None


def _parse_version(v: str) -> tuple:
    """'1.2.3' → 可比較的鍵;pre-release 排在同版號正式版之前(semver 語義)。"""
    base, _, pre = v.partition("-")
    nums = tuple(int(c) if c.isdigit() else 0 for c in base.split("."))
    return (nums, 0 if pre else 1, pre)


def _is_newer(remote: str, local: str) -> bool:
    try:
        return _parse_version(remote) > _parse_version(local)
    except (ValueError, TypeError):
        return remote != local


def _throttled() -> bool:
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return time.time() - state.get("last_check", 0) < THROTTLE_SECONDS
    except (OSError, json.JSONDecodeError):
        return False


def _touch_state() -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps({"last_check": time.time()}), encoding="utf-8")
    except OSError:
        pass


def _changelog_excerpt(remote_version: str) -> str:
    text = _fetch(REMOTE_CHANGELOG_URL)
    if not text:
        return ""
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines)
                  if ln.strip().startswith("## ") and remote_version in ln), None)
    if start is None:
        return ""
    out = []
    for ln in lines[start:]:
        if len(out) >= CHANGELOG_MAX_LINES:
            break
        if out and ln.strip().startswith("## ") and remote_version not in ln:
            break
        out.append(ln)
    return "\n".join(out)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    if not args.force and not args.apply and _throttled():
        return
    _touch_state()

    local = _read_local_version()
    remote_raw = _fetch(REMOTE_VERSION_URL)
    if not local or not remote_raw:
        return  # 離線或異常:靜默
    remote = remote_raw.strip().splitlines()[0].strip()
    if not remote or not _is_newer(remote, local):
        return

    is_git = (SKILL_DIR / ".git").exists()
    update_cmd = ("git -C \"%s\" pull --ff-only" % SKILL_DIR) if is_git \
        else "npx skills update aigo-template-transfer-skill"

    if args.as_json:
        print(json.dumps({"local": local, "remote": remote, "update_cmd": update_cmd},
                         ensure_ascii=False))
        return

    print(f"[aigo-template-transfer-skill] 有新版:{local} → {remote}")
    excerpt = _changelog_excerpt(remote)
    if excerpt:
        print(excerpt)
    if args.apply and is_git:
        result = subprocess.run(["git", "-C", str(SKILL_DIR), "pull", "--ff-only"],
                                capture_output=True, text=True)
        print(result.stdout.strip() or result.stderr.strip())
    else:
        print(f"更新指令:{update_cmd}")
        print("(不會自動執行;請確認本地無未提交修改後再更新)")


if __name__ == "__main__":
    main()
