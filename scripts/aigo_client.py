"""AI GO(來源側)認證與 API 客戶端。

憑證紀律對齊 aigo-app-builder-skill v1.1.x 的 aigo_auth.py:
- Agent 絕不在對話中向用戶要密碼、絕不代填;憑證一律由用戶自己寫進 .env。
- Token 取得順序:AIGO_TOKEN 環境變數/.env > 未過期快取 > refresh_token 換發 >
  .env 帳密登入。全部失敗 → 拋 RuntimeError,訊息內含設定指引,原樣轉給用戶。
- Token 快取在 .aigo/token.json(已被 .gitignore),密碼不進指令列與 log。
"""
import json
import os
import time
from pathlib import Path

import common

CACHE_DIR = common.REPO_ROOT / ".aigo"
CACHE_FILE = CACHE_DIR / "token.json"

SETUP_GUIDE = """無法取得 AI GO 憑證。請(用戶本人)在 repo 根目錄的 .env 填入:
  AIGO_EMAIL=<你的 AI GO 帳號>
  AIGO_PASSWORD=<你的密碼>
或直接提供 AIGO_TOKEN=<JWT>。帳號需具備 builder.access 權限。
(.env 已被 .gitignore;密碼不要貼在對話或指令列中)"""


def _load_cache(base_url: str) -> dict | None:
    if not CACHE_FILE.exists():
        return None
    try:
        cached = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return cached if cached.get("base_url") == base_url else None


def _save_cache(base_url: str, payload: dict) -> None:
    CACHE_DIR.mkdir(exist_ok=True)
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
    base_url = env["AIGO_BASE_URL"].rstrip("/")
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
    base_url = env["AIGO_BASE_URL"].rstrip("/")
    url = base_url + "/api/v1/" + path.lstrip("/")
    status, payload = common.http_call(method, url, body=body, token=get_token(env))
    if status == 401 and not env.get("AIGO_TOKEN"):
        CACHE_FILE.unlink(missing_ok=True)
        status, payload = common.http_call(method, url, body=body, token=get_token(env))
    return status, payload
