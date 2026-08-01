#!/usr/bin/env python3
"""Developer 平台整合:PAT 設定/驗證、S7 建 module + 推 draft、S9 送審。

    python scripts/devportal.py setup              # 產生 .env 範本
    python scripts/devportal.py set-pat            # 互動貼入 PAT 並當場驗證
    python scripts/devportal.py whoami             # 驗證 PAT 與權限等級
    python scripts/devportal.py push --slug my_template [--category ...]   # S7
    python scripts/devportal.py submit --slug my_template --note "..."     # S9(互動確認)

版本線與診斷(0.4.0 新增):

    python scripts/devportal.py bump --slug my_template --kind minor  # 已發布模組出下一版
    python scripts/devportal.py withdraw --slug my_template           # 撤回送審才能繼續編輯
    python scripts/devportal.py events --slug my_template             # 送審門檻現況(伺服器真相)
    python scripts/devportal.py pull --slug my_template               # 把平台上的檔案取回
    python scripts/devportal.py live-templates [--query x]            # 架上清單(S0 比對重疊)
    python scripts/devportal.py adopt --template-slug x               # 接管架上模板(admin,不可逆)

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
import devportal_paths as paths

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
    states = {v.get("state") for v in detail.get("versions", [])}
    if "submitted" in states:
        raise SystemExit("[FAIL] 版本已送審(submitted),送審中不可改內容。要繼續編輯先撤回:"
                         "\n    python scripts/devportal.py withdraw --slug <slug>")
    raise SystemExit("[FAIL] 模組沒有可編輯(draft/rejected)的版本(目前:"
                     f"{', '.join(sorted(s for s in states if s)) or '無版本'})。"
                     "已發布的模組要出下一版請先開新版本:"
                     "\n    python scripts/devportal.py bump --slug <slug> --kind minor")


def state_ids(work) -> tuple[str, str]:
    """從狀態機取 S7 記下的 module_id / version_id。"""
    state = common.load_state(work)
    s7 = state["stages"].get("S7_draft") or {}
    if not s7.get("module_id") or not s7.get("version_id"):
        raise SystemExit("[FAIL] 狀態機沒有 module_id/version_id——請先跑 "
                         "python scripts/devportal.py push --slug <slug>")
    return s7["module_id"], s7["version_id"]


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
            # 回應形狀 {"tags": [...], "source": "registry+aigo+local"};候選集 =
            # admin registry ∪ 架上使用中 ∪ 本地既有,不可當場新造字串(tag 治理 ADR-0005)
            raw = tags_ref if isinstance(tags_ref, list) else tags_ref.get("tags", [])
            valid = {t if isinstance(t, str) else t.get("slug") or t.get("name") for t in raw}
            bad = [t for t in meta["tags"] if t not in valid]
            if bad:
                raise SystemExit(f"[FAIL] tags 不在平台候選集:{bad}——合法值見 GET /refs/tags;"
                                 f"要新增 tag 需 admin 在標籤總覽建立(registry)")

    # data_references_schema 前置檢查:引用了 AI GO 不存在的表 → 租戶安裝時被靜默略過,
    # runtime 打 /proxy 直接被擋。平台 preflight 會 fail,但錯誤要到推完檔才看得到;
    # 這裡提前用 /refs 擋下,順便驗欄位名(preflight 對欄位只給 warn)。
    refs = paths.declared_refs(meta)
    if refs:
        status, available = api(env, "GET", "/refs/available-tables")
        if status != 200:
            # 這條路徑上「引用宣告有沒有問題」是**未知**,不是「沒問題」——
            # 講成已驗證會讓人以為 71 張表都對過了,錯誤其實延到 S8 或租戶安裝才炸。
            print(f"[WARN] 讀 /refs/available-tables 失敗(HTTP {status}):"
                  f"**引用宣告未經驗證**({len(refs)} 張表)。"
                  f"該端點不在此平台部署時屬正常(權威清單見 GET /dev-docs/endpoints),"
                  f"驗證改由 S8 e2e 以沙箱 proxy 實打。")
        else:
            names = {t.get("name") for t in available if isinstance(t, dict)}
            missing = [r["table_name"] for r in refs if r["table_name"] not in names]
            if missing:
                raise SystemExit(
                    f"[FAIL] data_references_schema 引用了 AI GO 不存在(或不可引用)的表:"
                    f"{missing}——租戶安裝會被靜默略過,runtime 打 /proxy 即被擋。"
                    f"合法表清單見 GET /refs/available-tables")
            cols_unverified = []
            for r in refs:
                declared_cols = r.get("columns") or []
                if not declared_cols:
                    continue
                status, cols = api(env, "GET", f"/refs/tables/{r['table_name']}/columns")
                if status != 200:
                    # 表名驗過了,但欄位是**未知**不是「沒問題」——這支端點同樣不是每個部署都有。
                    # 早期版本在這裡靜靜 continue,最後照樣印「引用宣告已驗證」,
                    # 跟上面 available-tables 那條是同一種誤報,只是低一層。
                    cols_unverified.append(r["table_name"])
                    continue
                real = {c.get("name") for c in cols if isinstance(c, dict)}
                bad_cols = [c for c in declared_cols if c not in real]
                if bad_cols:
                    raise SystemExit(
                        f"[FAIL] 引用表 '{r['table_name']}' 宣告了不存在的欄位:{bad_cols}——"
                        f"實際欄位見 GET /refs/tables/{r['table_name']}/columns")
            if cols_unverified:
                print(f"[OK] 引用**表名**已驗證({len(refs)} 張 AI GO 表);"
                      f"其中 {len(cols_unverified)} 張讀不到 GET /refs/tables/{{t}}/columns,"
                      f"**欄位未驗**:{cols_unverified[:5]}"
                      f"{' …' if len(cols_unverified) > 5 else ''}(改由 S8 e2e 實打)")
            else:
                print(f"[OK] 引用宣告已驗證({len(refs)} 張 AI GO 表)")

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
    # `status` 是 mark_stage 的位置參數,不能再從 **extra 傳同名鍵(會 TypeError,
    # 而且是在**送審已經成功之後**才炸——用戶只看到 traceback,以為沒送出去)。
    common.mark_stage(work, state, "S9_submit", "passed",
                      request_id=resp.get("request_id"), review_status=resp.get("status"))
    print(f"[OK] 已送審:request_id={resp.get('request_id')} status={resp.get('status')}")


def cmd_bump(args) -> None:
    """開新版本。已發布(approved)的模組要出下一版只有這條路。

    平台規則:同時只能有一條進行中的版本線,已有 draft/rejected 時回 409。
    新版本會成為 S7 的目標,S8/S9 一律重置——新版本沒測過。
    """
    work = common.work_dir(args.slug)
    env = common.load_env()
    module_id, old_vid = state_ids(work)

    status, resp = api(env, "POST", f"/modules/{module_id}/versions",
                       body={"kind": args.kind, "copy_files": not args.empty})
    if status == 409:
        raise SystemExit(f"[FAIL] 已有進行中的版本線(HTTP 409):{resp.get('detail', resp)}\n"
                         f"       草稿本身就是新版本——直接編輯並送審,或先刪除該版本。")
    if status not in (200, 201):
        raise SystemExit(f"[FAIL] 開新版本失敗(HTTP {status}):{resp}")

    state = common.load_state(work)
    state["stages"]["S7_draft"] = {"status": "passed", "at": common._now(),
                                   "module_id": module_id, "version_id": resp["id"],
                                   "version": resp.get("version"),
                                   "note": f"bump {args.kind} from {old_vid}"}
    for stage in ("S8_e2e", "S9_submit"):
        state["stages"][stage] = {"status": "pending"}
    common.save_state(work, state)
    print(f"[OK] 已開新版本 {resp.get('version')}(id={resp['id']},state={resp.get('state')})"
          f"{'' if args.empty else ',已複製上一版檔案'}")
    print("[!] S8/S9 已重置——新版本必須重跑 e2e。下一步:")
    print(f"    python scripts/devportal.py push --slug {args.slug}")


def cmd_withdraw(args) -> None:
    """撤回送審。送審中(submitted)不可改內容,要繼續編輯得先撤回。"""
    work = common.work_dir(args.slug)
    env = common.load_env()
    module_id, version_id = state_ids(work)

    status, resp = api(env, "POST", f"/modules/{module_id}/versions/{version_id}/withdraw")
    if status not in (200, 201):
        raise SystemExit(f"[FAIL] 撤回失敗(HTTP {status}):{resp}")

    # ★ 寫後回讀:確認狀態真的離開 submitted
    status, detail = api(env, "GET", f"/modules/{module_id}")
    ver_state = next((v.get("state") for v in detail.get("versions", [])
                      if v.get("id") == version_id), None) if status == 200 else None
    if ver_state == "submitted":
        raise SystemExit("[FAIL] 寫後回讀:版本仍是 submitted,撤回未生效,請到平台確認")

    state = common.load_state(work)
    state["stages"]["S9_submit"] = {"status": "pending"}
    common.save_state(work, state)
    print(f"[OK] 已撤回送審(版本現為 {ver_state});S9 已重置,可繼續編輯後重新送審。")


def cmd_events(args) -> None:
    """讀版本的佈署/測試事件——送審門檻的唯一真相在伺服器,不在本地報告。"""
    env = common.load_env()
    module_id, version_id = state_ids(common.work_dir(args.slug))
    status, events = api(env, "GET", f"/modules/{module_id}/versions/{version_id}/events")
    if status != 200:
        raise SystemExit(f"[FAIL] 讀事件失敗(HTTP {status}):{events}")

    last_deploy = max((e.get("created_at") or "" for e in events
                       if e.get("kind") == "deploy"), default="")
    print(f"共 {len(events)} 筆事件;最後 deploy:{last_deploy or '(尚無)'}\n")
    for e in events:
        detail = e.get("detail") or {}
        fresh = "*" if (e.get("created_at") or "") >= last_deploy and last_deploy else " "
        tail = ""
        if detail.get("action"):
            tail = f"  action={detail['action']} status={detail.get('status')}"
        elif e.get("kind") == "test":
            tail = "  (預覽型 test)"
        print(f" {fresh} {e.get('created_at')}  {e.get('kind'):<7}{tail}")
    print("\n(* = 發生在最後一次 deploy 之後,即對送審門檻有效的事件)")

    fresh_events = [e for e in events if (e.get("created_at") or "") >= last_deploy]
    passed = {(e.get("detail") or {}).get("action") for e in fresh_events
              if e.get("kind") == "test" and (e.get("detail") or {}).get("status") == "success"}
    passed.discard(None)
    has_preview = any(e.get("kind") == "test" and not (e.get("detail") or {}).get("action")
                      for e in fresh_events)
    print(f"\n門檻現況:預覽型 test = {'有' if has_preview else '缺'};"
          f"已成功執行的 action = {', '.join(sorted(passed)) if passed else '(無)'}")


def cmd_pull(args) -> None:
    """把平台上某版本的檔案內容取回本機。

    ai-go-templates repo 已關閉後,架上/平台的內容才是權威;要接續維護一支
    不是本機轉出來的模板(或核對平台實際存了什麼),得靠這支。
    """
    env = common.load_env()
    module_id, version_id = state_ids(common.work_dir(args.slug))
    status, files = api(env, "GET",
                        f"/modules/{module_id}/versions/{version_id}/files/content")
    if status != 200:
        raise SystemExit(f"[FAIL] 取檔案內容失敗(HTTP {status}):{files}")

    dest = Path(args.dest) if args.dest else common.work_dir(args.slug) / "pulled"
    if dest.exists() and any(dest.iterdir()) and not args.force:
        raise SystemExit(f"[FAIL] {dest} 非空;確認要覆寫請加 --force")
    written = 0
    for f in files:
        rel = f.get("file_path") or ""
        # 平台端已擋 `..` 與 `\`,這裡再擋一次:寫檔前絕不信任遠端路徑。
        if not rel or rel.startswith("/") or ".." in rel.split("/") or "\\" in rel:
            print(f"[WARN] 略過可疑路徑:{rel!r}")
            continue
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if f.get("is_binary"):
            target.write_bytes(base64.b64decode(f.get("content") or ""))
        else:
            target.write_text(f.get("content") or "", encoding="utf-8")
        written += 1
    print(f"[OK] 已取回 {written} 檔 → {dest}")


def cmd_live_templates(args) -> None:
    """架上模板清單——候選判定(S0)比對重疊的唯一權威。

    回應形狀是 `{"templates": [...], "source": "aigo"}`(不是裸陣列);
    每支帶 `is_managed` / `can_adopt`,是否可接管以 `can_adopt` 為準,不要自行推論。
    """
    env = common.load_env()
    status, payload = api(env, "GET", "/live-templates")
    if status != 200:
        raise SystemExit(f"[FAIL] 讀架上清單失敗(HTTP {status}):{payload}")
    items = payload.get("templates", []) if isinstance(payload, dict) else payload
    q = (args.query or "").lower()
    rows = [t for t in items if isinstance(t, dict) and (
        not q or q in str(t.get("slug", "")).lower() or q in str(t.get("name", "")).lower()
        or q in str(t.get("category", "")).lower())]
    print(f"架上 {len(items)} 支模板"
          + (f",符合 '{args.query}' 的 {len(rows)} 支" if q else "") + ":\n")
    for t in rows:
        if t.get("can_adopt"):
            managed = "未受管(可接管)"
        elif t.get("is_managed"):
            managed = "已受管"
        else:
            managed = str(t.get("state") or "-")
        print(f"  {str(t.get('slug')):<30} {str(t.get('category') or ''):<13} "
              f"{managed:<14} {t.get('name', '')}")


def cmd_adopt(args) -> None:
    """接管一支未受管的架上模板(admin)。

    **不可逆**:一支模板只能被接管一次,且會在 AI GO 端鎖住其他發布路徑。
    故比照 submit 走人工閘,由用戶親自輸入確認。
    """
    env = common.load_env()
    status, me = api(env, "GET", "/auth/me")
    if status != 200:
        raise SystemExit(f"[FAIL] 認證失敗(HTTP {status}):{me}")
    if me.get("level") != "admin":
        raise SystemExit(f"[FAIL] 接管需要 admin(目前 level={me.get('level')})。"
                         f"請找平台 admin 執行,不要嘗試繞路。")

    print(f"接管確認(不可逆):架上模板 '{args.template_slug}' 將被納入本平台管理,")
    print("並在 AI GO 端鎖住其他發布路徑;creator 會掛在你身上(之後可用「移交模組」轉出)。")
    answer = input("確認接管?(輸入 yes 確認)")
    if answer.strip().lower() != "yes":
        raise SystemExit("[ABORT] 未確認,不接管。")

    status, resp = api(env, "POST", f"/live-templates/{args.template_slug}/adopt")
    if status == 502:
        raise SystemExit(f"[FAIL] AI GO 那側失敗(HTTP 502):{resp.get('detail', resp)}\n"
                         f"       本地尚未寫入任何東西,排除後可安全重試。")
    if status not in (200, 201):
        raise SystemExit(f"[FAIL] 接管失敗(HTTP {status}):{resp}")
    print(f"[OK] 已接管:module_id={resp.get('module_id')} "
          f"version={resp.get('version')} files={resp.get('files_adopted')}")
    print("下一步:用 pull 取回內容作為後續維護的基準:")
    print(f"    python scripts/devportal.py pull --slug <你的工作區 slug>")


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

    p = sub.add_parser("bump", help="開新版本(已發布模組要出下一版的唯一路徑)")
    p.add_argument("--slug", required=True)
    p.add_argument("--kind", choices=("major", "minor", "patch"), default="minor")
    p.add_argument("--empty", action="store_true", help="不複製上一版檔案")
    p.set_defaults(func=cmd_bump)

    p = sub.add_parser("withdraw", help="撤回送審(送審中不可改內容)")
    p.add_argument("--slug", required=True)
    p.set_defaults(func=cmd_withdraw)

    p = sub.add_parser("events", help="讀佈署/測試事件與送審門檻現況")
    p.add_argument("--slug", required=True)
    p.set_defaults(func=cmd_events)

    p = sub.add_parser("pull", help="把平台上的版本檔案取回本機")
    p.add_argument("--slug", required=True)
    p.add_argument("--dest", help="目的目錄(預設 work/<slug>/pulled)")
    p.add_argument("--force", action="store_true", help="目的目錄非空時仍覆寫")
    p.set_defaults(func=cmd_pull)

    p = sub.add_parser("live-templates", help="架上模板清單(S0 候選判定用)")
    p.add_argument("--query", help="以 slug/名稱過濾")
    p.set_defaults(func=cmd_live_templates)

    p = sub.add_parser("adopt", help="接管未受管的架上模板(admin,不可逆,互動確認)")
    p.add_argument("--template-slug", required=True, help="架上模板的 slug")
    p.set_defaults(func=cmd_adopt)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
