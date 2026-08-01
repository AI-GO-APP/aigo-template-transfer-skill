"""共用基礎:UTF-8 輸出、.env 讀取、HTTP、狀態機、工作區與裁決檔。

使用者資料(憑證、token 快取、轉換工作區)一律放在 skill 目錄**之外**的
`~/.aigo-transfer/`,原因見 USER_DIR 附近註解——複製式安裝更新時會清空 skill 目錄。

狀態機是整個 skill 的「嚴謹每階段判斷」承載體:
- 階段順序固定(STAGES);跑 S(n) 前,S(0)..S(n-1) 必須全部 passed(選配階段除外)。
- 每個會改動/依賴 template/ 內容的階段,pass 時記錄當下內容雜湊到 state["last_hash"]。
  跑下一階段時雜湊不符 → 代表有人在閘外改了內容,一律擋下要求從變動點重跑。
- 人工閘 = decisions.json 必須有 decided_by=="user" 的明確裁決;腳本絕不代填。
"""
import hashlib
import io
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "config"

# ── 使用者資料目錄 ──────────────────────────────────────────────
# 憑證、token 快取、轉換工作區都放在 skill 目錄外。**不要搬回去**:
# 複製式安裝(`npx skills add`)的更新會把整個 skill 目錄 rm -rf 再重鋪
# (vercel-labs/skills `installer.ts` 的 cleanAndCreateDirectory),
# 放在裡面的 .env / token / work/ 會被無聲清光。git 安裝雖然 pull 不碰
# 未追蹤檔案,但仍共用同一條路徑規則,避免兩種安裝法行為分岔。
# 與 check_update.py 的節流狀態同一個家目錄。
HOME_OVERRIDE_KEY = "AIGO_TRANSFER_HOME"


def _resolve_user_dir() -> Path:
    override = os.environ.get(HOME_OVERRIDE_KEY)
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / ".aigo-transfer"


USER_DIR = _resolve_user_dir()
ENV_FILE = USER_DIR / ".env"
WORK_ROOT = USER_DIR / "work"
TOKEN_CACHE_FILE = USER_DIR / "token.json"

# 舊版(<= 0.6.1)放在 skill 目錄內的位置;bootstrap() 會搬遷過來
LEGACY_ENV_FILE = REPO_ROOT / ".env"
LEGACY_WORK_ROOT = REPO_ROOT / "work"
LEGACY_TOKEN_DIR = REPO_ROOT / ".aigo"
LEGACY_TOKEN_FILE = LEGACY_TOKEN_DIR / "token.json"

DEVPORTAL_DEFAULT_API = "https://developer.ai-go.app/api/v1"
AIGO_DEFAULT_BASE = "https://ai-go.app"

STAGES = [
    "S0_candidate",   # 候選判定(人工閘)
    "S1_acquire",     # 抽取正規化
    "S2_scan",        # 污染掃描
    "S3_detenant",    # 去租戶化(人工逐條裁決 + 腳本套用)
    "S4_dc_schema",   # Data Center schema(人工挑表)
    "S5_demo_data",   # demo 資料(人工閘)
    "S6_audit",       # 本地 audit 硬閘
    "S7_draft",       # Developer 平台建 module + draft
    "S8_e2e",         # Developer 沙箱端到端測試
    "S9_submit",      # 送審(人工閘)
]

# 內容雜湊追蹤的根:template/ 之外,dc_schema 草稿也算轉換產物
TRACKED_SUBDIRS = ["template", "dc_schema.json"]

PROTECTED_SDK_FILES = {"src/api.ts", "src/db.ts", "src/action.ts"}
INJECTED_FILES = {"src/data.json", "src/db.json", "src/actions.json"}

# 與 ai-go-developer/scripts/import_aigo_templates.py 的 TEXT_EXT 一致
TEXT_EXT = {
    ".ts", ".tsx", ".js", ".jsx", ".json", ".css", ".html", ".md", ".txt", ".svg",
    ".yml", ".yaml", ".py", ".sql", ".toml", ".cfg", ".ini", ".env", ".sh",
}


def utf8_stdout() -> None:
    """Windows 主控台預設 cp950,強制 UTF-8 避免中文輸出崩潰。"""
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


def _migrate_one(src: Path, dst: Path, label: str, notes: list[str]) -> None:
    """搬一個路徑到新家。目標已存在一律不覆蓋,只回報衝突讓用戶自己決定。"""
    if not src.exists():
        return
    if dst.exists():
        notes.append(
            f"[!] {label} 新舊兩份都存在:實際生效的是 {dst};"
            f"舊的 {src} 未被搬移,若確認不需要請自行刪除"
            f"(它在複製式安裝更新時會被清掉)。"
        )
        return
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
    except OSError as exc:
        notes.append(f"[!] {label} 搬移失敗({src} → {dst}):{exc}。"
                     f"舊路徑仍可用,但複製式安裝更新時會被清掉,請手動搬移。")
        return
    notes.append(f"[遷移] {label}:{src} → {dst}")


def migrate_legacy_user_data() -> list[str]:
    """把舊版(<= 0.6.1)留在 skill 目錄內的憑證/快取/工作區搬到 USER_DIR。

    冪等:搬完舊路徑就不存在,再跑一次是零成本的 exists() 檢查。
    永不覆蓋既有檔案、永不刪除資料——最壞情況是回報衝突後什麼都不做。
    """
    notes: list[str] = []
    _migrate_one(LEGACY_ENV_FILE, ENV_FILE, ".env 憑證", notes)
    _migrate_one(LEGACY_TOKEN_FILE, TOKEN_CACHE_FILE, "token 快取", notes)

    if LEGACY_WORK_ROOT.is_dir():
        for entry in sorted(LEGACY_WORK_ROOT.iterdir()):
            if entry.is_dir():
                _migrate_one(entry, WORK_ROOT / entry.name, f"工作區 {entry.name}", notes)

    # 搬空後把留下的空殼收掉;非空(還有衝突或雜檔)就原樣留著
    for stale in (LEGACY_TOKEN_DIR, LEGACY_WORK_ROOT):
        try:
            stale.rmdir()
        except OSError:
            pass
    return notes


def bootstrap() -> None:
    """所有 CLI 的統一開場:UTF-8 輸出 → 備妥使用者資料目錄 → 搬遷舊版資料。

    遷移提示一律走 stderr:多支腳本的 stdout 是給機器讀的 JSON,不能污染。
    """
    utf8_stdout()
    try:
        USER_DIR.mkdir(parents=True, exist_ok=True)
        os.chmod(USER_DIR, 0o700)
    except OSError:
        pass  # 權限或唯讀家目錄;真正需要寫入時會拋出更具體的錯
    for note in migrate_legacy_user_data():
        print(note, file=sys.stderr)


def write_env(text: str) -> None:
    """寫入 .env 並盡量收緊權限(Windows 上 chmod 不一定生效)。"""
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    ENV_FILE.write_text(text, encoding="utf-8")
    try:
        os.chmod(ENV_FILE, 0o600)
    except OSError:
        pass


def load_env() -> dict[str, str]:
    """讀 USER_DIR/.env;真實環境變數優先(CI 或臨時覆寫)。

    新位置不存在時退回舊的 skill 目錄內 .env——bootstrap() 通常已搬走,
    這條後備是給「直接 import common 而沒跑 bootstrap」的呼叫端兜底。
    """
    env: dict[str, str] = {}
    source = ENV_FILE if ENV_FILE.exists() else LEGACY_ENV_FILE
    if source.exists():
        for line in source.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    for k in ("DEVPORTAL_API", "DEVPORTAL_PAT", "AIGO_BASE_URL", "AIGO_TOKEN",
              "AIGO_EMAIL", "AIGO_PASSWORD"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    env.setdefault("DEVPORTAL_API", DEVPORTAL_DEFAULT_API)
    env.setdefault("AIGO_BASE_URL", AIGO_DEFAULT_BASE)
    return env


def http_call(method: str, url: str, *, body: Any = None, token: str | None = None,
              timeout: float = 60.0) -> tuple[int, Any]:
    """回傳 (status, parsed_json_or_text)。非 2xx 不拋錯,由呼叫端判斷。"""
    import httpx

    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    resp = httpx.request(method, url, json=body, headers=headers, timeout=timeout)
    try:
        return resp.status_code, resp.json()
    except ValueError:
        return resp.status_code, {"detail": resp.text[:500]}


# ── 工作區 ──────────────────────────────────────────────────────

def work_dir(slug: str) -> Path:
    """工作區在 USER_DIR/work/<slug>。新位置還不存在、而舊位置有東西時沿用舊的
    (同 load_env 的理由:給沒跑 bootstrap 的呼叫端兜底,不讓進行中的轉換憑空消失)。"""
    new = WORK_ROOT / slug
    if not new.exists() and (LEGACY_WORK_ROOT / slug).is_dir():
        return LEGACY_WORK_ROOT / slug
    return new


def state_path(work: Path) -> Path:
    return work / "transfer_state.json"


def decisions_path(work: Path) -> Path:
    return work / "decisions.json"


def load_state(work: Path) -> dict:
    p = state_path(work)
    if not p.exists():
        raise SystemExit(f"[FAIL] 找不到 {p}。請先跑 transfer_cli.py init --slug <slug>")
    return json.loads(p.read_text(encoding="utf-8"))


def save_state(work: Path, state: dict) -> None:
    state_path(work).write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def load_decisions(work: Path) -> dict:
    p = decisions_path(work)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def save_decisions(work: Path, decisions: dict) -> None:
    decisions_path(work).write_text(
        json.dumps(decisions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def init_state(slug: str) -> Path:
    work = work_dir(slug)
    work.mkdir(parents=True, exist_ok=True)
    p = state_path(work)
    if p.exists():
        raise SystemExit(f"[FAIL] {p} 已存在;若要重來請先手動刪除工作區或用 reset")
    state = {
        "slug": slug,
        "created_at": _now(),
        "last_hash": None,
        "stages": {s: {"status": "pending"} for s in STAGES},
    }
    save_state(work, state)
    return work


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def content_hash(work: Path) -> str | None:
    """template/(含 dc_schema.json)的內容雜湊;template/ 不存在時回 None。"""
    template = work / "template"
    if not template.is_dir():
        return None
    h = hashlib.sha256()
    entries: list[tuple[str, bytes]] = []
    for path in sorted(template.rglob("*")):
        if path.is_file():
            rel = path.relative_to(template).as_posix()
            entries.append((f"template/{rel}", path.read_bytes()))
    dc = work / "dc_schema.json"
    if dc.exists():
        entries.append(("dc_schema.json", dc.read_bytes()))
    for rel, data in entries:
        h.update(rel.encode("utf-8"))
        h.update(b"\x00")
        h.update(data)
        h.update(b"\x00")
    return h.hexdigest()


def file_hash(path: Path) -> str | None:
    """單檔內容雜湊;檔案不存在回 None。
    用於把人工裁決綁定到當下的檔案內容(meta 人工閘:確認過的必須就是要推的那份)。"""
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_stage(work: Path, stage: str, *, optional_ok: tuple[str, ...] = (),
                  allow_content_change: bool = False) -> dict:
    """閘:跑 stage 前確認所有前置階段 passed(或列於 optional_ok 且 skipped),
    且 template/ 內容未在閘外被改動。回傳 state。

    allow_content_change=True 僅供「本身就是在核准新內容」的閘使用
    (S5 demo 資料閘、normalize_meta):用戶確認即核准,S6 audit 的污染複掃會再兜底。"""
    state = load_state(work)
    idx = STAGES.index(stage)
    for prev in STAGES[:idx]:
        status = state["stages"].get(prev, {}).get("status")
        if status == "passed":
            continue
        if prev in optional_ok and status == "skipped":
            continue
        raise SystemExit(
            f"[FAIL] 階段閘:{stage} 之前的 {prev} 尚未通過(目前:{status})。"
            f"請依序完成各階段,不可跳關。"
        )
    if not allow_content_change:
        current = content_hash(work)
        recorded = state.get("last_hash")
        if recorded is not None and current != recorded:
            raise SystemExit(
                "[FAIL] 內容閘:template/ 內容與最後一次通過階段時的雜湊不符——"
                "有變更發生在階段閘之外。請從產生變更的階段重跑(必要時 transfer_cli.py reset)。"
            )
    return state


def mark_stage(work: Path, state: dict, stage: str, status: str, **extra: Any) -> None:
    """記錄階段結果並更新內容雜湊。status: passed | skipped | failed。

    failed 也更新雜湊:閘內腳本(如 apply_decisions)可能已合法改動內容,
    不更新會把重跑的路鎖死;閘外手改仍會被下一個 require_stage 擋下。"""
    entry: dict[str, Any] = {"status": status, "at": _now()}
    entry.update(extra)
    state["stages"][stage] = entry
    state["last_hash"] = content_hash(work)
    save_state(work, state)


def refresh_hash(work: Path, state: dict) -> None:
    """閘內合法寫入後重新對齊內容雜湊(如 normalize_meta 寫 _template_meta.json)。"""
    state["last_hash"] = content_hash(work)
    save_state(work, state)


def require_user_decision(decisions: dict, key: str, what: str) -> dict:
    """人工閘:decisions[key] 必須存在且 decided_by == 'user'。"""
    entry = decisions.get(key)
    if not isinstance(entry, dict) or entry.get("decided_by") != "user":
        raise SystemExit(
            f"[FAIL] 人工閘:decisions.json 缺少 '{key}' 的用戶裁決({what})。"
            f"此欄位必須由用戶確認後以 decided_by=\"user\" 寫入;AI 或腳本不得代填。"
        )
    return entry


def read_template_files(template: Path) -> dict[str, str]:
    """讀 template/ 下全部文字檔為 {posix 相對路徑: 內容};binary 略過。"""
    files: dict[str, str] = {}
    for path in sorted(template.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(template).as_posix()
        if path.suffix in TEXT_EXT or path.name in ("_template_meta.json",):
            try:
                files[rel] = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
    return files


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_config(name: str) -> Any:
    return load_json(CONFIG_DIR / name)


def add_vendor_to_path() -> None:
    vendor = REPO_ROOT / "vendor"
    if str(vendor) not in sys.path:
        sys.path.insert(0, str(vendor))
