#!/usr/bin/env python3
"""轉換總入口:工作區初始化、階段狀態、人工閘記錄、重置。

    python scripts/transfer_cli.py init --slug my_template
    python scripts/transfer_cli.py status --slug my_template
    python scripts/transfer_cli.py gate --slug my_template --stage S0 \
        --decision new --notes "與既有 sales_crm 重疊已評估,決定新開"
    python scripts/transfer_cli.py gate --slug my_template --stage S5 --decision approved
    python scripts/transfer_cli.py reset --slug my_template --from-stage S2

    # S1 前:確認來源 app 身分(uuid 打錯不會報錯,只會安靜地抽走別支 app)
    python scripts/transfer_cli.py confirm-source --slug my_template --app <uuid_or_slug>
    # S6 前:確認模板門面文案(name/description/category/長描述都是上架給第三方看的)
    python scripts/transfer_cli.py confirm-meta --slug my_template

人工閘(gate / confirm-*)一律互動確認:必須在終端機輸入 yes 才會寫入 decided_by="user"。
這是刻意設計——AI 代理無法在非互動環境替用戶按下確認。
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common
from common import STAGES

GATE_STAGES = {
    "S0": ("S0_candidate", "candidate", "候選判定:new(新模板)/ merge(併入既有)/ exclude(不做)",
           {"new", "merge", "exclude"}),
    "S5": ("S5_demo_data", "demo_data", "demo 資料:approved(已審閱 seed 內容)/ skipped(此模板不需要)",
           {"approved", "skipped"}),
}


def cmd_init(args) -> None:
    work = common.init_state(args.slug)
    print(f"[OK] 已建立工作區 {work}")
    print("下一步:transfer_cli.py gate --slug", args.slug, "--stage S0 --decision new|merge|exclude")


def cmd_status(args) -> None:
    work = common.work_dir(args.slug)
    state = common.load_state(work)
    current = common.content_hash(work)
    stale = state.get("last_hash") is not None and current != state.get("last_hash")
    print(f"模板:{state['slug']}  工作區:{work}")
    if stale:
        print("[WARN] template/ 內容與最後通過階段的雜湊不符——存在閘外變更,下一個階段會被擋。")
    for stage in STAGES:
        entry = state["stages"].get(stage, {})
        status = entry.get("status", "pending")
        mark = {"passed": "[OK]  ", "skipped": "[SKIP]", "failed": "[FAIL]"}.get(status, "[ -- ]")
        extra = "  ".join(f"{k}={v}" for k, v in entry.items() if k not in ("status",))
        print(f"  {mark} {stage:<14} {extra}")


def cmd_gate(args) -> None:
    if args.stage not in GATE_STAGES:
        raise SystemExit(f"[FAIL] gate 只用於人工閘階段 {sorted(GATE_STAGES)};"
                         f"S3 由 apply_decisions.py 承載、S9 由 devportal.py submit 承載")
    stage_key, decision_key, desc, valid = GATE_STAGES[args.stage]
    if args.decision not in valid:
        raise SystemExit(f"[FAIL] --decision 須為 {sorted(valid)} 其中之一({desc})")

    work = common.work_dir(args.slug)
    state = common.load_state(work)

    # S0 之外的人工閘仍受階段順序約束;S5 閘允許內容變更
    # (起草的 seed_demo_data.py / dc seed 就是本閘要核准的東西,S6 污染複掃會兜底)
    if stage_key != "S0_candidate":
        state = common.require_stage(work, stage_key, allow_content_change=True)

    if stage_key == "S5_demo_data" and args.decision == "approved":
        seed = work / "template" / "actions" / "seed_demo_data.py"
        if not seed.exists():
            raise SystemExit("[FAIL] S5 approved 需要 template/actions/seed_demo_data.py 存在;"
                             "若此模板不需要 demo 資料請用 --decision skipped 並附 --notes 理由")

    print(f"人工閘 {stage_key}:{desc}")
    print(f"  裁決:{args.decision}")
    if args.notes:
        print(f"  備註:{args.notes}")
    confirm("確認以上裁決?(輸入 yes 確認)")

    decisions = common.load_decisions(work)
    decisions[decision_key] = {
        "decision": args.decision,
        "notes": args.notes or "",
        "decided_by": "user",
        "at": common._now(),
    }
    common.save_decisions(work, decisions)

    if args.decision == "exclude":
        common.mark_stage(work, state, stage_key, "failed", decision="exclude")
        print("[OK] 已記錄 exclude:此 app 不做模板,流程到此為止。")
        return
    status = "skipped" if args.decision == "skipped" else "passed"
    common.mark_stage(work, state, stage_key, status, decision=args.decision)
    print(f"[OK] {stage_key} → {status}")


def confirm(prompt: str = "確認?(輸入 yes 確認)") -> None:
    """人工閘的唯一入口。非互動環境(agent 直接跑)讀到 EOF 一律當未確認——
    這裡拋 traceback 會讓人以為是程式壞了,實際上是這步本來就該由用戶親自執行。"""
    try:
        answer = input(prompt)
    except EOFError:
        raise SystemExit("[ABORT] 非互動環境無法確認;此步驟必須由用戶在終端機親自執行。")
    if answer.strip().lower() != "yes":
        raise SystemExit("[ABORT] 未確認,不寫入。")


def cmd_confirm_source(args) -> None:
    """來源 app 身分閘(S1 前置)。

    抽取線上 app 只要 uuid 打錯就會安靜地轉走另一支 app 的內容——不會 404、
    不會有任何警訊,直到上架才發現。故身分由用戶親自對著平台回來的資料確認。
    """
    import acquire  # 延後 import:只有這條路徑需要 AI GO 連線

    work = common.work_dir(args.slug)
    common.load_state(work)  # 工作區必須已 init
    env = common.load_env()
    app_info = acquire.fetch_app_vfs(env, args.app)

    print("來源 app(平台回傳的實際資料):")
    print(acquire.identity_card(app_info))
    print("\n[!] 確認這就是你要轉成模板的那一支;抽錯 app 等於把別的客戶的內容做成模板。")
    confirm("確認來源身分?(輸入 yes 確認)")

    decisions = common.load_decisions(work)
    decisions[acquire.SOURCE_DECISION_KEY] = {
        "app_id": str(app_info.get("id") or ""),
        "app_slug": app_info.get("slug"),
        "app_name": app_info.get("name"),
        "requested": args.app,
        "decided_by": "user",
        "at": common._now(),
    }
    common.save_decisions(work, decisions)
    print(f"[OK] 已記錄來源身分。下一步:\n"
          f"    python scripts/acquire.py --slug {args.slug} --from-app {app_info.get('id')}")


def cmd_confirm_meta(args) -> None:
    """模板 meta 人工閘(S6 前置)。

    name / description / category / tags / 長描述是上架後第三方唯一看得到的東西,
    由 AI 起草可以,但不能由 AI 拍板。確認綁定當下的檔案內容雜湊:meta 改過就要重確認。
    """
    work = common.work_dir(args.slug)
    common.load_state(work)
    meta_path = work / "template" / "_template_meta.json"
    if not meta_path.exists():
        raise SystemExit("[FAIL] 找不到 template/_template_meta.json;請先跑 normalize_meta.py")
    meta = common.load_json(meta_path)

    print("模板 meta(上架後第三方看到的門面):\n")
    for key in ("slug", "name", "category", "version", "access_mode", "author", "icon_emoji"):
        if meta.get(key):
            print(f"  {key:<12}:{meta[key]}")
    if meta.get("tags"):
        print(f"  {'tags':<12}:{', '.join(meta['tags'])}")
    print(f"  {'description':<12}:{meta.get('description')}")
    for key, label in (("setup_schema", "安裝表單欄位"), ("required_egress", "需授權的外部服務")):
        if meta.get(key):
            print(f"  {label:<12}:{', '.join(sorted(meta[key]))}")
    tables = [t.get("key") for t in (meta.get("data_center_schema") or {}).get("tables", [])
              if isinstance(t, dict)]
    if tables:
        print(f"  {'自建表':<12}:{', '.join(str(t) for t in tables)}")
    if meta.get("long_description"):
        print("\n--- long_description(含安裝後設定清單)---")
        print(meta["long_description"])
        print("--- end ---")
    print("\n[!] 逐項讀過再確認:文案錯字、殘留客戶名、category 選錯,上架後都要重送審。")
    confirm("確認以上 meta?(輸入 yes 確認)")

    decisions = common.load_decisions(work)
    decisions["meta"] = {
        "meta_hash": common.file_hash(meta_path),
        "name": meta.get("name"),
        "category": meta.get("category"),
        "decided_by": "user",
        "at": common._now(),
    }
    common.save_decisions(work, decisions)
    print(f"[OK] 已記錄 meta 裁決。下一步:\n"
          f"    python scripts/audit_local.py --slug {args.slug}")


def cmd_reset(args) -> None:
    work = common.work_dir(args.slug)
    state = common.load_state(work)
    idx = STAGES.index(args.from_stage)
    for stage in STAGES[idx:]:
        state["stages"][stage] = {"status": "pending"}
    state["last_hash"] = common.content_hash(work)
    common.save_state(work, state)
    print(f"[OK] 已重置 {args.from_stage} 起的所有階段(內容雜湊已重新對齊目前狀態)")


def main() -> None:
    common.bootstrap()
    parser = argparse.ArgumentParser(description="custom app → template 轉換總入口")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="建立工作區與狀態機")
    p.add_argument("--slug", required=True)
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("status", help="顯示各階段狀態")
    p.add_argument("--slug", required=True)
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("gate", help="人工閘裁決(S0 候選判定 / S5 demo 資料)")
    p.add_argument("--slug", required=True)
    p.add_argument("--stage", required=True, choices=sorted(GATE_STAGES))
    p.add_argument("--decision", required=True)
    p.add_argument("--notes", default="")
    p.set_defaults(func=cmd_gate)

    p = sub.add_parser("confirm-source", help="確認來源 app 身分(S1 前置,人工)")
    p.add_argument("--slug", required=True)
    p.add_argument("--app", required=True, help="線上 custom app 的 uuid 或 slug")
    p.set_defaults(func=cmd_confirm_source)

    p = sub.add_parser("confirm-meta", help="確認模板 meta 門面文案(S6 前置,人工)")
    p.add_argument("--slug", required=True)
    p.set_defaults(func=cmd_confirm_meta)

    p = sub.add_parser("reset", help="重置某階段(含)之後的狀態")
    p.add_argument("--slug", required=True)
    p.add_argument("--from-stage", required=True, choices=STAGES)
    p.set_defaults(func=cmd_reset)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
