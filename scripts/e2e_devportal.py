#!/usr/bin/env python3
"""S8 Developer 沙箱端到端測試:secrets → seed → CRUD → actions → test 事件。

    python scripts/e2e_devportal.py --slug my_template                # full(預設)
    python scripts/e2e_devportal.py --slug my_template --quick        # 快速檔
    python scripts/e2e_devportal.py --slug my_template --secrets-file secrets.e2e.json
    python scripts/e2e_devportal.py --slug my_template --expect expect.e2e.json --no-event

分級(對齊 builder skill Phase 4.2 的變更範圍分級):
- --quick:preflight + secrets + 表 CRUD。適用只改文案/CSS 後的重驗。
  quick 不記 test 事件(不足以代表可用性)。
- full(預設):quick + 全部 action 執行 + seed_demo_data 冪等重跑 + test 事件。
  送審(S9)一律要求最後一次 e2e 是 full。

送審門檻(2026-07-28 平台更新):最後 deploy 後需 (a) 一筆預覽型 test 事件,
且 (b) **每支 enabled action 至少一筆 status=success 的沙箱執行紀錄**——由沙箱
執行端點伺服器自動記錄,前端不可宣稱。full 檔跑過所有 action 即同時滿足;
沒跑通的 action 只能補憑證重跑或 manifest 停用,--expect allow_fail 擋不住平台端。

判讀規則:
- runner 未配置(503)→ 該 phase 記 SKIP,不視為失敗,但會標注在報告
  (注意:runner 不可用時 enabled action 無 success 紀錄,送審會被平台 422)
- 回應含 approval_status=="pending" / 簽核例外 → 記 WARN 不記 FAIL:
  那是租戶簽核流程攔截(builder 核心規則 24),不是 bug,且**不可重試**
- --expect 檔可宣告允許失敗的 action(如需要真實第三方憑證者)→ 記 WARN
- webhook 宣告的 action 在沙箱以一般 action 方式驗證;對外端點登記本身
  無法在沙箱測,已列入安裝後設定清單
- 若要走瀏覽器 preview 的正式 test 事件,改用 --no-event,再開
  https://developer.ai-go.app/preview/<module_id>?v=<version_id>
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common
import devportal_paths as paths
from devportal import api


def run_phase(report: list, name: str, status: str, detail: str = "") -> None:
    report.append({"phase": name, "status": status, "detail": detail})
    tag = {"pass": "[OK]  ", "fail": "[FAIL]", "skip": "[SKIP]", "warn": "[WARN]"}[status]
    print(f"{tag} {name}" + (f":{detail}" if detail else ""))


def main() -> None:
    common.utf8_stdout()
    parser = argparse.ArgumentParser(description="S8 Developer 沙箱 e2e")
    parser.add_argument("--slug", required=True)
    parser.add_argument("--quick", action="store_true",
                        help="快速檔:preflight+secrets+CRUD,不跑 action、不記 test 事件")
    parser.add_argument("--secrets-file", help="e2e 用 secrets 值 JSON({KEY: value})")
    parser.add_argument("--egress-file",
                        help="沙箱 egress 設定 JSON({slug: {base_url, auth_type, auth_config, allow_dynamic_host}})")
    parser.add_argument("--expect", help="期望設定 JSON({allow_fail_actions: [..]})")
    parser.add_argument("--no-event", action="store_true",
                        help="不自動記 test 事件(改走瀏覽器 preview)")
    args = parser.parse_args()

    work = common.work_dir(args.slug)
    template = work / "template"
    state = common.require_stage(work, "S8_e2e", optional_ok=("S5_demo_data",))
    env = common.load_env()

    s7 = state["stages"]["S7_draft"]
    module_id, vid = s7["module_id"], s7["version_id"]
    meta = common.load_json(template / "_template_meta.json")
    access_mode = meta.get("access_mode", "internal")
    expect = common.load_json(Path(args.expect)) if args.expect else {}
    allow_fail = set(expect.get("allow_fail_actions", []))
    secrets_values = common.load_json(Path(args.secrets_file)) if args.secrets_file else {}

    inv_path = work / "inventory.json"
    inventory = common.load_json(inv_path) if inv_path.exists() else {}
    webhook_actions = set(inventory.get("webhooks", []))

    report: list[dict] = []
    hard_fail = False
    runner_down = False

    def is_approval_pending(resp) -> bool:
        """簽核攔截語義(builder 核心規則 24):pending 非成功非失敗,不可重試。"""
        text = str(resp)
        return '"approval_status": "pending"' in text or "approval_status='pending'" in text \
            or "簽核" in text or "approval_status" in text and "pending" in text

    # Phase 1: preflight
    status, pf = api(env, "GET", f"/modules/{module_id}/versions/{vid}/preflight")
    if status == 200 and pf.get("ok"):
        run_phase(report, "preflight", "pass")
    else:
        run_phase(report, "preflight", "fail", f"HTTP {status} ok={pf.get('ok')}")
        hard_fail = True

    # Phase 2: 沙箱 secrets
    setup_schema = meta.get("setup_schema") or {}
    if setup_schema:
        payload = {}
        dummies = []
        for key in setup_schema:
            if key in secrets_values:
                payload[key] = secrets_values[key]
            else:
                payload[key] = f"e2e-dummy-{key.lower()}"
                dummies.append(key)
        status, resp = api(env, "PUT", f"/sandbox/v/{vid}/secrets", body=payload)
        if status == 200:
            detail = f"dummy 金鑰:{', '.join(dummies)}" if dummies else "全部真值"
            run_phase(report, "secrets", "pass", detail)
        else:
            run_phase(report, "secrets", "fail", f"HTTP {status}:{resp}")
            hard_fail = True
    else:
        run_phase(report, "secrets", "skip", "setup_schema 為空")

    # Phase 2.5: 沙箱 egress 註冊(required_egress 宣告的 slug 沒註冊,action 測不動;
    # 平台 preflight 也會 warn「缺沙箱註冊」)
    required_egress = meta.get("required_egress") or {}
    egress_values = common.load_json(Path(args.egress_file)) if args.egress_file else {}
    for slug in required_egress:
        cfg = egress_values.get(slug, {})
        body = {
            "base_url": cfg.get("base_url", "https://example.invalid"),
            "auth_type": cfg.get("auth_type", "none"),
            "auth_config": cfg.get("auth_config", {}),
            "is_active": True,
            "allow_dynamic_host": bool(cfg.get("allow_dynamic_host", False)),
        }
        status, resp = api(env, "PUT", f"/sandbox/v/{vid}/egress/{slug}", body=body)
        if status == 200:
            note = "真值" if slug in egress_values else "dummy base_url(該 slug 的 action 預期打不通)"
            run_phase(report, f"egress:{slug}", "pass", note)
        else:
            run_phase(report, f"egress:{slug}", "fail", f"HTTP {status}:{resp}")
            hard_fail = True

    # Phase 3: 表 CRUD——**自建表與引用表是兩個不同的端點面**,見 devportal_paths 檔頭。
    # 3a 自建表(data_center_schema)走 data_table SDK 面 /data/objects/{key}/records;
    # 3b 引用表(data_references_schema)走 proxy SDK 面 /proxy/...(平台會驗 AI GO 快照)。
    # 兩者互餵必定 404,且 0.3.4 以前的 e2e 正是把自建表餵給 /proxy。

    def crud_cycle(label: str, base: str, sample: dict,
                   record_path, query_path: str | None = None) -> None:
        """insert → list → (query) → update → delete。

        兩個面的 insert 與 list 都是同一個 base(POST/GET 同路徑);update/delete
        則因面而異(自建表以 record id 反查、引用表帶表名),故由 record_path 組。
        會刪掉自己插的列,不留測試髒資料。
        """
        nonlocal hard_fail
        status, created = api(env, "POST", base, body=sample)
        if status not in (200, 201):
            if is_approval_pending(created):
                run_phase(report, label, "warn", "簽核流程攔截(pending)——非失敗,不可重試")
                return
            run_phase(report, label, "fail", f"insert HTTP {status}:{str(created)[:200]}")
            hard_fail = True
            return
        steps = ["insert"]
        status, _ = api(env, "GET", base)
        if status != 200:
            run_phase(report, label, "fail", f"list HTTP {status}")
            hard_fail = True
            return
        steps.append("list")
        if query_path:
            status, _ = api(env, "POST", query_path, body={"filters": {}})
            if status != 200:
                run_phase(report, label, "fail", f"query HTTP {status}")
                hard_fail = True
                return
            steps.append("query")

        rid = created.get("id") if isinstance(created, dict) else None
        if not rid:
            run_phase(report, label, "warn",
                      f"{'+'.join(steps)};回應無 id,update/delete 未驗")
            return
        status, _ = api(env, "PATCH", record_path(rid), body=sample)
        if status not in (200, 204):
            run_phase(report, label, "fail", f"update HTTP {status}")
            hard_fail = True
            return
        steps.append("update")
        status, _ = api(env, "DELETE", record_path(rid))
        if status not in (200, 204):
            run_phase(report, label, "fail", f"delete HTTP {status}")
            hard_fail = True
            return
        steps.append("delete")
        run_phase(report, label, "pass", "+".join(steps))

    # 3a: 自建表
    for table in paths.declared_tables(meta):
        tkey = table["key"]
        crud_cycle(
            f"crud:自建表 {tkey}",
            paths.data_records(vid, tkey, access_mode),
            {"data": paths.sample_for_fields(table.get("fields"))},
            lambda rid: paths.data_record(vid, rid, access_mode),
        )

    # 3b: 引用表。樣本列依 AI GO 真實欄位型別產生(GET /refs/tables/{t}/columns),
    # 順帶驗證宣告的表在平台真的存在——preflight 對此只給 fail 訊息,這裡提前抓。
    for ref in paths.declared_refs(meta):
        tname = ref["table_name"]
        status, cols = api(env, "GET", f"/refs/tables/{tname}/columns")
        if status != 200:
            run_phase(report, f"crud:引用表 {tname}", "fail",
                      f"AI GO 無此表或不可引用(HTTP {status})——"
                      f"data_references_schema 宣告錯誤,租戶安裝會被靜默略過")
            hard_fail = True
            continue
        crud_cycle(
            f"crud:引用表 {tname}",
            paths.proxy_rows(vid, tname, access_mode),
            paths.sample_for_columns(cols),
            lambda rid, t=tname: paths.proxy_row(vid, t, rid, access_mode),
            paths.proxy_query(vid, tname, access_mode),
        )

    # Phase 4: actions(--quick 跳過)
    actions_dir = template / "actions"
    manifest_path = actions_dir / "manifest.json"
    action_names: list[str] = []
    disabled: list[str] = []
    if args.quick:
        run_phase(report, "actions", "skip", "--quick 檔不跑 action;送審前需跑 full")
    elif manifest_path.exists():
        manifest = common.load_json(manifest_path)
        entries: dict = {}
        if isinstance(manifest, dict):
            entries = {n: c for n, c in manifest.items() if n != "actions"}
        elif isinstance(manifest, list):
            entries = {e.get("name"): e for e in manifest if isinstance(e, dict) and e.get("name")}
        for name, cfg in entries.items():
            # is_enabled:false 的 action 沙箱執行回 409,且不列入送審門檻——直接跳過
            if isinstance(cfg, dict) and cfg.get("is_enabled") is False:
                disabled.append(name)
                run_phase(report, f"action:{name}", "skip", "manifest 已停用(不列入送審門檻)")
                continue
            action_names.append(name)

    def run_action(name: str) -> tuple[int, dict]:
        if access_mode == "external":
            return api(env, "POST", f"/sandbox/v/{vid}/ext/actions/run/{name}",
                       body={"params": {}})
        return api(env, "POST", f"/sandbox/v/{vid}/actions/apps/{vid}/run/{name}",
                   body={"params": {}})

    for name in action_names:
        status, resp = run_action(name)
        tag = "(webhook)" if name in webhook_actions else ""
        if status == 503:
            run_phase(report, f"action:{name}{tag}", "skip", "runner 未配置(503)")
            runner_down = True
            continue
        if is_approval_pending(resp):
            run_phase(report, f"action:{name}{tag}", "warn",
                      "簽核流程攔截(pending)——非失敗,不可重試")
            continue
        if 200 <= status < 300:
            run_phase(report, f"action:{name}{tag}", "pass")
            if name == "seed_demo_data":
                status2, resp2 = run_action(name)
                if 200 <= status2 < 300:
                    run_phase(report, "action:seed_demo_data(冪等重跑)", "pass")
                else:
                    run_phase(report, "action:seed_demo_data(冪等重跑)", "fail",
                              f"HTTP {status2}")
                    hard_fail = True
        elif name in allow_fail:
            run_phase(report, f"action:{name}{tag}", "warn",
                      f"HTTP {status}(expect 檔允許失敗:需真實憑證)")
        else:
            run_phase(report, f"action:{name}{tag}", "fail", f"HTTP {status}:{str(resp)[:200]}")
            hard_fail = True

    # Phase 4.5: 送審門檻對帳——平台要求每支 enabled action 在最後 deploy 後
    # 至少一筆 status=success 的沙箱執行紀錄(伺服器自動記,前端不可宣稱)。
    # 先前這裡只拿本地報告推算;本地判定「pass」與伺服器真的記到事件是兩回事
    # (例如 runner 回 2xx 但事件寫入失敗),所以改為 GET 事件跟伺服器對帳。
    if not args.quick:
        status, events = api(env, "GET", f"/modules/{module_id}/versions/{vid}/events")
        if status != 200 or not isinstance(events, list):
            run_phase(report, "submit-gate", "warn",
                      f"無法讀取事件紀錄(HTTP {status}),改以本地報告推算門檻")
            succeeded = {r["phase"].split(":", 1)[1].replace("(webhook)", "")
                         for r in report
                         if r["phase"].startswith("action:") and "冪等" not in r["phase"]
                         and r["status"] == "pass"}
        else:
            # 只認最後一次 deploy 之後的事件——deploy 會讓先前的驗證全部失效。
            last_deploy = max((e.get("created_at") or "" for e in events
                               if e.get("kind") == "deploy"), default="")
            succeeded = {
                (e.get("detail") or {}).get("action")
                for e in events
                if e.get("kind") == "test"
                and (e.get("created_at") or "") >= last_deploy
                and (e.get("detail") or {}).get("status") == "success"
                and (e.get("detail") or {}).get("action")
            }
            run_phase(report, "submit-gate-events", "pass",
                      f"伺服器已記錄成功執行的 action:"
                      f"{', '.join(sorted(succeeded)) if succeeded else '(無)'}")
            # 門檻的另一半:最後 deploy 後要有一筆**無 detail.action** 的 test 事件
            # (預覽測試)。本腳本的 Phase 6 會補記,故 --no-event 時才需要提醒。
            has_preview = any(
                e.get("kind") == "test" and (e.get("created_at") or "") >= last_deploy
                and not (e.get("detail") or {}).get("action") for e in events)
            if not has_preview and args.no_event:
                run_phase(report, "submit-gate-preview", "warn",
                          "最後 deploy 後尚無預覽型 test 事件,送審會被擋——"
                          f"請開 https://developer.ai-go.app/preview/{module_id}?v={vid}")

        not_passed = [n for n in action_names if n not in succeeded and n not in disabled]
        if not_passed:
            run_phase(report, "submit-gate", "warn",
                      f"這些 enabled action 在伺服器上沒有「最後 deploy 之後的成功執行紀錄」,"
                      f"送審會被平台擋下:{', '.join(not_passed)}"
                      f"——補真憑證重跑,或在 manifest 設 is_enabled:false 停用")

    # Phase 5: 表列筆數(資訊性)
    status, counts = api(env, "GET", f"/sandbox/v/{vid}/tables")
    if status == 200:
        run_phase(report, "tables-count", "pass", str(counts)[:200])

    summary = {
        "tier": "quick" if args.quick else "full",
        "pass": sum(1 for r in report if r["status"] == "pass"),
        "fail": sum(1 for r in report if r["status"] == "fail"),
        "skip": sum(1 for r in report if r["status"] == "skip"),
        "warn": sum(1 for r in report if r["status"] == "warn"),
        "runner_available": not runner_down,
    }
    common.dump_json(work / "e2e_report.json", {"summary": summary, "phases": report})
    print(f"\n報告 → {work / 'e2e_report.json'}  {summary}")

    if hard_fail:
        common.mark_stage(work, state, "S8_e2e", "failed", **summary)
        raise SystemExit("[FAIL] S8 未通過,修正後重跑(必要時回 S3/S6)")

    if args.quick:
        print("[OK] quick 檔通過。送審前仍需跑 full(不帶 --quick)以完成可用性驗證。")
        return  # 不推進狀態機、不記 test 事件

    # Phase 6: test 事件(送審門檻:最後 test 不早於最後 deploy)
    if args.no_event:
        print("[NOTE] 未記 test 事件。請開瀏覽器執行 preview 以產生正式 test 事件:")
        print(f"  https://developer.ai-go.app/preview/{module_id}?v={vid}")
    else:
        status, resp = api(env, "POST", f"/modules/{module_id}/versions/{vid}/events",
                           body={"kind": "test", "detail": {"source": "aigo-template-transfer-skill e2e",
                                                            "summary": summary}})
        if status not in (200, 201):
            common.mark_stage(work, state, "S8_e2e", "failed", **summary)
            raise SystemExit(f"[FAIL] 記 test 事件失敗(HTTP {status}):{resp}")
        print("[OK] 已記 test 事件(送審門檻已滿足)")

    common.mark_stage(work, state, "S8_e2e", "passed", **summary)
    if runner_down:
        print("[WARN] 平台 runner 未配置,server action 未真跑——送審前請人工評估此風險")
    print("下一步:審閱 e2e_report.json 後 python scripts/devportal.py submit --slug", args.slug)


if __name__ == "__main__":
    main()
