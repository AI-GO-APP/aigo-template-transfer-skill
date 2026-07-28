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

    # Phase 3: 表 CRUD(經 sandbox ext proxy;internal 亦可用 proxy/{app_id} 形式)
    tables = (meta.get("data_center_schema") or {}).get("tables", [])
    for table in tables:
        tkey = table["key"]
        sample = {}
        for f in table["fields"]:
            if f.get("type") == "relation":
                continue
            sample[f["key"]] = {
                "text": "e2e 測試", "number": 1, "boolean": True,
                "date": "2026-01-01", "datetime": "2026-01-01T00:00:00",
                "select": (f.get("options") or ["e2e"])[0],
                "json": {}, "image": None,
            }.get(f.get("type"), "e2e")
        base = (f"/sandbox/v/{vid}/ext/proxy/{tkey}" if access_mode == "external"
                else f"/sandbox/v/{vid}/proxy/{vid}/{tkey}")
        status, created = api(env, "POST", base, body=sample)
        if status not in (200, 201):
            if is_approval_pending(created):
                run_phase(report, f"crud:{tkey}", "warn",
                          "簽核流程攔截(pending)——非失敗,不可重試")
                continue
            run_phase(report, f"crud:{tkey}", "fail", f"insert HTTP {status}:{created}")
            hard_fail = True
            continue
        status, rows = api(env, "GET", base)
        if status != 200:
            run_phase(report, f"crud:{tkey}", "fail", f"query HTTP {status}")
            hard_fail = True
            continue
        run_phase(report, f"crud:{tkey}", "pass", "insert+query")

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

    # Phase 4.5: 送審門檻試算——平台要求每支 enabled action 在最後 deploy 後
    # 至少一筆 status=success 的沙箱執行紀錄(伺服器自動記,前端不可宣稱)。
    # 沒跑通的 enabled action = 送審必被 422;唯二出路:補真憑證跑通,或 manifest 停用。
    not_passed = [r["phase"].split(":", 1)[1].replace("(webhook)", "")
                  for r in report
                  if r["phase"].startswith("action:") and "冪等" not in r["phase"]
                  and r["status"] != "pass"
                  and r["phase"].split(":", 1)[1].replace("(webhook)", "") not in disabled]
    if not_passed and not args.quick:
        run_phase(report, "submit-gate", "warn",
                  f"這些 enabled action 未成功執行,送審會被平台擋下:{', '.join(not_passed)}"
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
