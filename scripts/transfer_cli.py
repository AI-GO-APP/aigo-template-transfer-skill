#!/usr/bin/env python3
"""轉換總入口:工作區初始化、階段狀態、人工閘記錄、重置。

    python scripts/transfer_cli.py init --slug my_template
    python scripts/transfer_cli.py status --slug my_template
    python scripts/transfer_cli.py gate --slug my_template --stage S0 \
        --decision new --notes "與既有 sales_crm 重疊已評估,決定新開"
    python scripts/transfer_cli.py gate --slug my_template --stage S5 --decision approved
    python scripts/transfer_cli.py reset --slug my_template --from-stage S2

人工閘(gate)一律互動確認:必須在終端機輸入 yes 才會寫入 decided_by="user"。
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
    answer = input("確認以上裁決?(輸入 yes 確認)")
    if answer.strip().lower() != "yes":
        raise SystemExit("[ABORT] 未確認,不寫入。")

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
    common.utf8_stdout()
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

    p = sub.add_parser("reset", help="重置某階段(含)之後的狀態")
    p.add_argument("--slug", required=True)
    p.add_argument("--from-stage", required=True, choices=STAGES)
    p.set_defaults(func=cmd_reset)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
