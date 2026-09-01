"""AI GO(來源側)認證與 API 客戶端。

    python scripts/aigo_client.py whoami    # Phase 0:來源側憑證與權限預檢

憑證與租戶空間紀律對齊 aigo-app-builder-skill 1.8.0+ 的 aigo_auth.py:
- Agent 絕不在對話中向用戶要密碼、絕不代填;憑證一律由用戶自己寫進 .env。
- 登入走租戶空間 https://{tenant}.ai-go.app(common.aigo_base_url 解析,apex 直接擋
  ——apex 的 401 與密碼錯完全同形,放行只會把人送去查一個無解的密碼問題)。
- Token 取得順序:AIGO_TOKEN 環境變數/.env > 未過期快取 > refresh_token 換發 >
  .env 帳密登入。全部失敗 → 拋 RuntimeError,訊息內含設定指引,原樣轉給用戶。
- Token 快取在 ~/.aigo-transfer/token.json(skill 目錄外,重裝不會被清掉),
  快取綁 base_url——token 綁租戶,換租戶即整份作廢;密碼不進指令列與 log。
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common

CACHE_DIR = common.USER_DIR
CACHE_FILE = common.TOKEN_CACHE_FILE

SETUP_GUIDE = f"""無法取得 AI GO 憑證。請(用戶本人)在 {common.ENV_FILE} 填入:
  AIGO_TENANT=<租戶前綴>      # 登入時網址列的第一段,如 urfit
  AIGO_EMAIL=<你的 AI GO 帳號>
  AIGO_PASSWORD=<你的密碼>
或直接提供 AIGO_TOKEN=<JWT>。帳號需具備 builder.access 權限。
(該檔在 skill 目錄外,更新或重裝不會被清掉;密碼不要貼在對話或指令列中)"""


def _load_cache(base_url: str) -> dict | None:
    if not CACHE_FILE.exists():
        return None
    try:
        cached = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return cached if cached.get("base_url") == base_url else None


def _save_cache(base_url: str, payload: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps({
        "base_url": base_url,
        "access_token": payload["access_token"],
        "refresh_token": payload.get("refresh_token", ""),
        "expires_at": time.time() + max(payload.get("expires_in", 3600) - 60, 0),
    }), encoding="utf-8")
    try:
        os.chmod(CACHE_FILE, 0o600)
    except OSError:
        pass  # Windows 上不一定生效


def _login(env: dict, base_url: str) -> str:
    email = env.get("AIGO_EMAIL")
    password = env.get("AIGO_PASSWORD") or os.environ.get("AIGO_PASSWORD")
    if not email or not password:
        raise RuntimeError(SETUP_GUIDE)
    status, payload = common.http_call(
        "POST", f"{base_url}/api/v1/auth/login",
        body={"email": email, "password": password})
    if status == 401:
        # 平台反帳號列舉設計:密碼錯與租戶錯的 401 完全同形(狀態碼/detail 皆不可區分),
        # 不能只叫人查密碼——那可能是一個無解的方向。
        raise RuntimeError(
            f"AI GO 登入失敗(HTTP 401):{payload.get('detail', payload)}。\n"
            f"「密碼錯」與「租戶錯」的 401 完全同形,兩個方向都要查:\n"
            f"  1) {common.ENV_FILE} 的 AIGO_EMAIL / AIGO_PASSWORD 是否正確\n"
            f"  2) 租戶空間是否正確(目前打:{base_url};"
            f"AIGO_TENANT 應為登入時網址列的第一段)")
    if status != 200:
        raise RuntimeError(f"AI GO 登入失敗(HTTP {status}):{payload.get('detail', payload)}。"
                           f"請確認 .env 的 AIGO_EMAIL / AIGO_PASSWORD 正確。")
    _save_cache(base_url, payload)
    return payload["access_token"]


def _refresh(base_url: str, refresh_token: str) -> str | None:
    status, payload = common.http_call(
        "POST", f"{base_url}/api/v1/auth/refresh",
        body={"refresh_token": refresh_token})
    if status == 200 and payload.get("access_token"):
        _save_cache(base_url, payload)
        return payload["access_token"]
    return None


def get_token(env: dict | None = None) -> str:
    """依序:AIGO_TOKEN > 快取 > refresh > .env 帳密。失敗拋 RuntimeError(含指引)。"""
    env = env or common.load_env()
    if env.get("AIGO_TOKEN"):
        return env["AIGO_TOKEN"]
    base_url = common.aigo_base_url(env)
    cached = _load_cache(base_url)
    if cached:
        if cached.get("expires_at", 0) > time.time():
            return cached["access_token"]
        if cached.get("refresh_token"):
            token = _refresh(base_url, cached["refresh_token"])
            if token:
                return token
    return _login(env, base_url)


def api(env: dict, method: str, path: str, body=None) -> tuple[int, dict]:
    """帶 token 打 AI GO API;401 時清快取重新取得再試一次。"""
    base_url = common.aigo_base_url(env)
    url = base_url + "/api/v1/" + path.lstrip("/")
    status, payload = common.http_call(method, url, body=body, token=get_token(env))
    if status == 401 and not env.get("AIGO_TOKEN"):
        CACHE_FILE.unlink(missing_ok=True)
        status, payload = common.http_call(method, url, body=body, token=get_token(env))
    return status, payload


# ── Phase 0 預檢 ────────────────────────────────────────────────

BUILDER_PERMISSION = "builder.access"
ADMIN_PERMISSION = "system.admin"  # 平台 require_permission 的萬能鑰匙(同租戶內)


def has_builder_access(me: dict) -> bool:
    """對齊 ai-go `require_permission("builder.access")`:system.admin 直接放行。"""
    perms = set(me.get("permissions") or [])
    return ADMIN_PERMISSION in perms or BUILDER_PERMISSION in perms


def whoami(env: dict | None = None) -> dict:
    """GET /auth/me。失敗拋 RuntimeError(訊息原樣轉給用戶,不要自行推測修法)。"""
    env = env or common.load_env()
    status, me = api(env, "GET", "auth/me")
    if status != 200:
        raise RuntimeError(f"AI GO /auth/me 失敗(HTTP {status}):{me.get('detail', me)}。"
                           f"401 代表憑證失效(重設 {common.ENV_FILE} 或刪掉 {CACHE_FILE} 重登),"
                           f"403 代表權限不足(請租戶管理員處理,不要繞路)。")
    return me


def cmd_whoami() -> int:
    try:
        me = whoami()
    except RuntimeError as e:
        print(f"[FAIL] {e}")
        return 1
    tenant = me.get("tenant_name") or me.get("tenant_id") or "?"
    print(f"{me.get('email')}  租戶={tenant}  member={me.get('name') or '-'}")
    if not has_builder_access(me):
        print(f"[FAIL] 此帳號缺少 {BUILDER_PERMISSION} 權限,無法讀取 custom app 的 vfs_state。"
              f"\n       請租戶管理員在後台授予後重試——這是權限設定問題,改 code 改不掉。")
        return 1
    print(f"[OK] 來源側就緒(具備 {BUILDER_PERMISSION})")
    return 0


def main() -> None:
    common.bootstrap()
    parser = argparse.ArgumentParser(description="AI GO 來源側憑證檢查")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("whoami", help="驗證 .env 憑證與 builder.access 權限")
    parser.parse_args()
    raise SystemExit(cmd_whoami())


if __name__ == "__main__":
    main()
