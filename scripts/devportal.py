#!/usr/bin/env python3
"""Developer 平台整合:PAT 設定/驗證、S7 建 module + 推 draft、S9 送審。

    python scripts/devportal.py setup              # 產生 .env 範本
    python scripts/devportal.py set-pat            # 互動貼入 PAT 並當場驗證
    python scripts/devportal.py whoami             # 驗證 PAT 與權限等級
    python scripts/devportal.py push --slug my_template [--category ...]   # S7
    python scripts/devportal.py submit --slug my_template --note "..."     # S9(互動確認)

PAT 引導(SKILL.md Phase 0 的落地):
1. 登入/註冊 https://developer.ai-go.app → 設定頁(/settings)→「API Token(PAT)」→ 發行
   (token 只顯示一次,aigodev_ 開頭)
2. python scripts/devportal.py set-pat 貼入
3. whoami 顯示 level;read_only 代表帳號尚未被 admin 升級為 editor,不能建模組

認證與 API 慣例對齊 ai-go-developer/scripts/devportal_auth.py 與 cli/aigodev.py。
"""
import argparse
import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common

ENV_TEMPLATE = """# Developer 平台(本檔已被 .gitignore,不會進版控)
DEVPORTAL_API=https://developer.ai-go.app/api/v1
DEVPORTAL_PAT=

# 來源側 AI GO(抽取線上 app / 撈 Data Center 表用,帳號需 builder.access)
# 憑證由用戶本人填寫;AI agent 不代填、不在對話中詢問密碼。
# 有 AIGO_TOKEN 就用 token;否則用帳密自動換發並快取到 .aigo/token.json。
AIGO_BASE_URL=https://ai-go.app
AIGO_EMAIL=
AIGO_PASSWORD=
AIGO_TOKEN=
"""

PAT_GUIDE = """[!] 尚未設定 DEVPORTAL_PAT。請依以下步驟取得:
  1. 開啟 https://developer.ai-go.app 登入(沒有帳號先註冊)
  2. 進「設定」頁(https://developer.ai-go.app/settings)
  3. 「API Token(PAT)」區塊 → 發行 PAT(token 只顯示一次,格式 aigodev_...)
  4. 回到終端機執行:python scripts/devportal.py set-pat
注意:新註冊帳號預設 read_only,需請平台 admin 升級為 editor 才能建立模組。"""


def api(env: dict, method: str, path: str, body=None) -> tuple[int, dict]:
    pat = env.get("DEVPORTAL_PAT")
    if not pat:
        print(PAT_GUIDE)
        raise SystemExit(1)
    url = env["DEVPORTAL_API"].rstrip("/") + "/" + path.lstrip("/")
    return common.http_call(method, url, body=body, token=pat)


def cmd_setup(args) -> None:
    if common.ENV_FILE.exists():
        print(f".env 已存在:{common.ENV_FILE}(未覆蓋)")
    else:
        common.ENV_FILE.write_text(ENV_TEMPLATE, encoding="utf-8")
        print(f"已建立 {common.ENV_FILE}")
    print(PAT_GUIDE)


def cmd_set_pat(args) -> None:
    # 用可見 input() 而非 getpass:Windows 主控台隱藏輸入吃不到 Ctrl+V(devportal_auth 同款理由)
    pat = input("貼上 PAT(aigodev_ 開頭,貼完按 Enter):").strip()
    if len(pat) < 20 or not pat.startswith("aigodev_"):
        raise SystemExit(f"[FAIL] 這不像本平台的 PAT(收到 {len(pat)} 字元,應為 aigodev_ 開頭)。"
                         f"請從 https://developer.ai-go.app/settings 重新發行。")
    lines = common.ENV_FILE.read_text(encoding="utf-8").splitlines() if common.ENV_FILE.exists() else []
    lines = [ln for ln in lines if not ln.strip().startswith("DEVPORTAL_PAT=")]
    lines.append(f"DEVPORTAL_PAT={pat}")
    common.ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    env = common.load_env()
    status, me = api(env, "GET", "/auth/me")
    if status != 200:
        raise SystemExit(f"已寫入 .env,但驗證失敗(HTTP {status}):{me}")
    print(f"[OK] 已寫入並驗證:{me['email']}  level={me['level']}")
    if me["level"] == "read_only":
        print("[!] 帳號為 read_only,無法建立模組;請聯繫平台 admin 升級為 editor。")


def cmd_whoami(args) -> None:
    env = common.load_env()
    status, me = api(env, "GET", "/auth/me")
    if status != 200:
        raise SystemExit(f"[FAIL] GET /auth/me 失敗(HTTP {status}):{me}\n"
                         f"PAT 可能已撤銷或過期,請重新發行後 set-pat。")
    print(f"{me['email']}  level={me['level']}  status={me.get('status')}")
    if me["level"] == "read_only":
        print("[!] read_only 無法建立模組;請聯繫平台 admin 升級為 editor。")


def collect_files(template: Path) -> list[dict]:
    files = []
    for path in sorted(template.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(template).as_posix()
        if path.suffix in common.TEXT_EXT:
            try:
                files.append({"file_path": rel,
                              "content": path.read_text(encoding="utf-8"),
                              "is_binary": False})
                continue
            except UnicodeDecodeError:
                pass
        files.append({"file_path": rel,
                      "content": base64.b64encode(path.read_bytes()).decode("ascii"),
                      "is_binary": True})
    return files


def build_metadata(meta: dict) -> dict:
    keys = ["name", "description", "long_description", "icon_emoji", "category", "tags",
            "access_mode", "setup_schema", "required_egress", "data_center_schema",
            "data_references_schema", "author", "version"]
    return {k: meta[k] for k in keys if meta.get(k) is not None and meta.get(k) != ""}


def find_editable_version(env: dict, module_id: str) -> dict:
    status, detail = api(env, "GET", f"/modules/{module_id}")
    if status != 200:
        raise SystemExit(f"[FAIL] 取模組失敗(HTTP {status}):{detail}")
    for v in detail.get("versions", []):
        if v.get("state") in ("draft", "rejected"):
            return v
    raise SystemExit("[FAIL] 模組沒有可編輯(draft/rejected)的版本;"
                     "若上一版已送審請先 withdraw,已發布請在平台開新版本。")


def cmd_push(args) -> None:
    work = common.work_dir(args.slug)
    template = work / "template"
    state = common.require_stage(work, "S7_draft", optional_ok=("S5_demo_data",))
    env = common.load_env()

    meta = common.load_json(template / "_template_meta.json")

    # 權限與 tags 白名單前置檢查
    status, me = api(env, "GET", "/auth/me")
    if status != 200:
        raise SystemExit(f"[FAIL] 認證失敗(HTTP {status}):{me}")
    if me["level"] == "read_only":
        raise SystemExit("[FAIL] 帳號為 read_only,無法建模組;請先請 admin 升級為 editor。")
    if meta.get("tags"):
        status, tags_ref = api(env, "GET", "/refs/tags")
        if status == 200:
            valid = {t if isinstance(t, str) else t.get("slug") or t.get("name")
                     for t in (tags_ref if isinstance(tags_ref, list) else tags_ref.get("items", []))}
            bad = [t for t in meta["tags"] if t not in valid]
            if bad:
                raise SystemExit(f"[FAIL] tags 不在平台白名單:{bad}(GET /refs/tags 取得合法值)")

    # 建立或沿用模組(建立時平台自動帶 1.0.0 draft,不可再 POST /versions)
    module_id = state["stages"].get("S7_draft", {}).get("module_id")
    if not module_id:
        status, created = api(env, "POST", "/modules", body={
            "slug": args.slug,
            "name": meta["name"],
            "category": meta["category"],
            "access_mode": meta.get("access_mode", "internal"),
        })
        if status == 201 or status == 200:
            module_id = created["id"]
            print(f"[OK] 已建立模組 {args.slug}(id={module_id})")
        elif status == 409:
            # slug 已存在:找自己的同名模組沿用
            status2, mine = api(env, "GET", "/modules?mine=true")
            match = next((m for m in (mine if isinstance(mine, list) else mine.get("items", []))
                          if m.get("slug") == args.slug.replace("_", "-") or m.get("slug") == args.slug),
                         None) if status2 == 200 else None
            if not match:
                raise SystemExit(f"[FAIL] slug 衝突(HTTP 409)且不是你的模組:{created}")
            module_id = match["id"]
            print(f"[OK] 沿用既有模組 {match['slug']}(id={module_id})")
        else:
            raise SystemExit(f"[FAIL] 建模組失敗(HTTP {status}):{created}")

    version = find_editable_version(env, module_id)
    version_id = version["id"]

    # 推 metadata → 推 files(PUT files 全量取代,平台自動記 deploy 事件)
    payload = build_metadata(meta)
    status, resp = api(env, "PUT", f"/modules/{module_id}/versions/{version_id}/metadata",
                       body={"metadata": payload})
    if status != 200:
        raise SystemExit(f"[FAIL] 推 metadata 失敗(HTTP {status}):{resp}")

    # ★ 寫後回讀:確認關鍵欄位真的存進去(對齊 builder skill 的二次 GET 驗證慣例)
    status, detail = api(env, "GET", f"/modules/{module_id}")
    stored = next((v.get("metadata") or {} for v in detail.get("versions", [])
                   if v.get("id") == version_id), {}) if status == 200 else {}
    for key in ("name", "category", "setup_schema", "data_center_schema"):
        if payload.get(key) is not None and stored.get(key) != payload.get(key):
            raise SystemExit(f"[FAIL] 寫後回讀:metadata 的 '{key}' 與送出內容不符——"
                             f"平台可能靜默丟棄或改寫了它,請人工檢查後再繼續")
    print("[OK] metadata 已更新並回讀驗證(含 data_center_schema)")

    files = collect_files(template)
    status, resp = api(env, "PUT", f"/modules/{module_id}/versions/{version_id}/files",
                       body={"files": files})
    if status != 200:
        raise SystemExit(f"[FAIL] 推檔案失敗(HTTP {status}):{resp}")

    # ★ 寫後回讀:檔數一致
    status, listing = api(env, "GET", f"/modules/{module_id}/versions/{version_id}/files")
    if status == 200:
        remote = listing if isinstance(listing, list) else listing.get(
            "files", listing.get("items", []))
        if len(remote) != len(files):
            raise SystemExit(f"[FAIL] 寫後回讀:遠端檔數 {len(remote)} ≠ 上傳 {len(files)}")
    print(f"[OK] 已上傳並回讀驗證 {resp.get('files_written', len(files))} 檔"
          f"({resp.get('total_bytes', '?')} bytes),平台已記 deploy 事件")

    status, pf = api(env, "GET", f"/modules/{module_id}/versions/{version_id}/preflight")
    if status != 200:
        raise SystemExit(f"[FAIL] preflight 取得失敗(HTTP {status}):{pf}")
    issues = pf.get("issues", [])
    for issue in issues:
        tag = "[FAIL]" if issue.get("severity") == "fail" else "[WARN]"
        print(f"  {tag} {issue.get('check')}: {issue.get('message')}"
              + (f"({issue.get('where')})" if issue.get("where") else ""))
    if not pf.get("ok"):
        common.mark_stage(work, state, "S7_draft", "failed",
                          module_id=module_id, version_id=version_id)
        raise SystemExit(f"[FAIL] 平台 preflight 未通過({pf.get('fail_count')} fail)")

    common.mark_stage(work, state, "S7_draft", "passed",
                      module_id=module_id, version_id=version_id,
                      version=version.get("version"))
    print(f"[OK] S7 完成:draft {version.get('version')} 就緒,preflight ok")
    print("下一步:python scripts/e2e_devportal.py --slug", args.slug)


def cmd_submit(args) -> None:
    work = common.work_dir(args.slug)
    state = common.require_stage(work, "S9_submit", optional_ok=("S5_demo_data",))
    env = common.load_env()
    s7 = state["stages"]["S7_draft"]
    module_id, version_id = s7["module_id"], s7["version_id"]

    s8 = state["stages"].get("S8_e2e", {})
    if s8.get("tier") and s8["tier"] != "full":
        raise SystemExit("[FAIL] 最後一次 e2e 是 quick 檔;送審前必須跑 full:"
                         "python scripts/e2e_devportal.py --slug " + args.slug)

    e2e_report = work / "e2e_report.json"
    print(f"送審前確認(人工閘 S9):")
    print(f"  模組 {args.slug}  module={module_id}  version={version_id}")
    print(f"  e2e 報告:{e2e_report}(請先審閱)")
    answer = input("已審閱 e2e 報告並確認送審?(輸入 yes 確認)")
    if answer.strip().lower() != "yes":
        raise SystemExit("[ABORT] 未確認,不送審。")

    status, resp = api(env, "POST", f"/modules/{module_id}/versions/{version_id}/submit",
                       body={"note": args.note or ""})
    if status not in (200, 201):
        raise SystemExit(f"[FAIL] 送審失敗(HTTP {status}):{resp}")

    # ★ 寫後回讀:確認版本狀態已轉 submitted
    status, detail = api(env, "GET", f"/modules/{module_id}")
    ver_state = next((v.get("state") for v in detail.get("versions", [])
                      if v.get("id") == version_id), None) if status == 200 else None
    if ver_state != "submitted":
        print(f"[WARN] 寫後回讀:版本狀態為 {ver_state!r} 而非 submitted,請到平台確認")

    decisions = common.load_decisions(work)
    decisions["submit"] = {"decision": "submitted", "decided_by": "user", "at": common._now(),
                           "request_id": resp.get("request_id")}
    common.save_decisions(work, decisions)
    common.mark_stage(work, state, "S9_submit", "passed",
                      request_id=resp.get("request_id"), status=resp.get("status"))
    print(f"[OK] 已送審:request_id={resp.get('request_id')} status={resp.get('status')}")


def main() -> None:
    common.utf8_stdout()
    parser = argparse.ArgumentParser(description="Developer 平台整合")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("setup", help="產生 .env 範本與 PAT 引導").set_defaults(func=cmd_setup)
    sub.add_parser("set-pat", help="互動貼入 PAT 並驗證").set_defaults(func=cmd_set_pat)
    sub.add_parser("whoami", help="驗證 PAT 與權限").set_defaults(func=cmd_whoami)

    p = sub.add_parser("push", help="S7:建模組 + 推 metadata/files + preflight")
    p.add_argument("--slug", required=True)
    p.set_defaults(func=cmd_push)

    p = sub.add_parser("submit", help="S9:送審(互動確認)")
    p.add_argument("--slug", required=True)
    p.add_argument("--note", default="")
    p.set_defaults(func=cmd_submit)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
