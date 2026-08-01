#!/usr/bin/env python3
"""S3 去租戶化:依 decisions.json 的逐條裁決套用修改,再複掃驗證收斂。

    python scripts/apply_decisions.py --slug my_template --check   # 只列未裁決,不改檔
    python scripts/apply_decisions.py --slug my_template           # 套用 + 複掃 + 過閘

decisions.json 的 findings 區格式(key = scan_report 的 finding id):

    "findings": {
      "a1b2c3d4e5f6": {
        "action": "replace",             # replace | delete_file | keep
        "old": "https://customer.example.com",
        "new": "ctx.secrets.get(\"WEBHOOK_BASE_URL\")",
        "note": "客戶網域參數化",
        "decided_by": "user"
      }
    }

規則:
- 每一筆 blocker/high/medium finding 都必須有 decided_by=="user" 的裁決;info 自動視為 keep。
- blocker 不可裁決為 keep(必須 replace 或 delete_file)。
- replace 以「檔案內精確字串」為單位(old→new,預設限定該檔全部出現次數);
  這讓修改內容完全由裁決紀錄決定,可重現、可稽核。
- 套用後自動複掃:仍存在且未被裁決為 keep 的 finding → S3 不過。
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common
from scan import scan_template


def main() -> None:
    common.bootstrap()
    parser = argparse.ArgumentParser(description="S3 去租戶化")
    parser.add_argument("--slug", required=True)
    parser.add_argument("--check", action="store_true", help="只檢查裁決完整性,不套用")
    args = parser.parse_args()

    work = common.work_dir(args.slug)
    template = work / "template"
    state = common.require_stage(work, "S3_detenant")

    report = common.load_json(work / "scan_report.json")
    findings = {f["id"]: f for f in report["findings"]}
    decisions = common.load_decisions(work)
    fd = decisions.get("findings", {})

    # replace 的 new 字串是用戶核准過的內容:含該內容的 finding 自動視為 keep
    # (典型:參數化成 ctx.secrets.get("NEW_KEY") 後,secret_key_usage 會以新 id 再現)
    approved_snippets = [
        d["new"] for d in fd.values()
        if isinstance(d, dict) and d.get("decided_by") == "user"
        and d.get("action") == "replace" and d.get("new")
    ]

    def auto_keep_if_approved(f: dict) -> bool:
        # 雙向包含:單行 replace(new ⊆ 行)與多行 replace(行 ⊆ new)都要涵蓋
        if f["severity"] == "blocker":
            return False
        line = f["excerpt"].strip()
        if line and any(sn and (sn in line or line in sn) for sn in approved_snippets):
            fd[f["id"]] = {"action": "keep", "decided_by": "user",
                           "note": "自動:此行內容即用戶核准的 replace 結果"}
            return True
        return False

    undecided: list[dict] = []
    invalid: list[str] = []
    for fid, f in findings.items():
        if f["severity"] == "info":
            continue
        d = fd.get(fid)
        if not isinstance(d, dict) or d.get("decided_by") != "user":
            if not auto_keep_if_approved(f):
                undecided.append(f)
            continue
        action = d.get("action")
        if action not in ("replace", "delete_file", "keep"):
            invalid.append(f"{fid}: 未知 action {action!r}")
        elif f["severity"] == "blocker" and action == "keep":
            invalid.append(f"{fid}: blocker 不可裁決為 keep({f['rule']} @ {f['file']}:{f['line']})")
        elif action == "replace" and (not d.get("old") or "new" not in d):
            invalid.append(f"{fid}: replace 需要 old 與 new 欄位")

    if undecided:
        print(f"[FAIL] 尚有 {len(undecided)} 筆 finding 未經用戶裁決:")
        for f in undecided[:30]:
            print(f"  {f['id']}  [{f['severity']}] {f['rule']}  {f['file']}:{f['line']}  {f['excerpt'][:80]}")
        if len(undecided) > 30:
            print(f"  ...及另外 {len(undecided) - 30} 筆")
        raise SystemExit(1)
    if invalid:
        print("[FAIL] 裁決內容不合法:")
        for msg in invalid:
            print(f"  {msg}")
        raise SystemExit(1)

    if args.check:
        print(f"[OK] 裁決完整:{len(findings)} 筆 finding 全數有效裁決。可執行套用。")
        return

    # 套用(依檔案分組,delete_file 優先)
    applied = {"replace": 0, "delete_file": 0, "keep": 0}
    deleted_files: set[str] = set()
    for fid, f in findings.items():
        d = fd.get(fid) or {"action": "keep"}
        action = d.get("action", "keep")
        if action == "delete_file" and f["file"] not in deleted_files:
            target = template / Path(*f["file"].split("/"))
            if target.exists():
                target.unlink()
            deleted_files.add(f["file"])
            applied["delete_file"] += 1
        elif action == "replace":
            if f["file"] in deleted_files:
                continue
            target = template / Path(*f["file"].split("/"))
            content = target.read_text(encoding="utf-8")
            old, new = d["old"], d["new"]
            if old not in content:
                print(f"[WARN] {fid}: 檔案 {f['file']} 內找不到 old 字串(可能已被前一筆裁決改掉)")
                continue
            count = d.get("count")
            content = content.replace(old, new, count) if count else content.replace(old, new)
            target.write_text(content, encoding="utf-8")
            applied["replace"] += 1
        else:
            applied["keep"] += 1

    # 複掃收斂驗證
    rules_cfg = common.load_config("scan_rules.json")
    residual = scan_template(template, rules_cfg)
    common.dump_json(work / "scan_report.json", {"findings": residual})

    unresolved = []
    for f in residual:
        if f["severity"] == "info":
            continue
        d = fd.get(f["id"])
        if isinstance(d, dict) and d.get("decided_by") == "user" and d.get("action") == "keep":
            continue
        if auto_keep_if_approved(f):
            continue
        unresolved.append(f)
    decisions["findings"] = fd
    common.save_decisions(work, decisions)

    if unresolved:
        print(f"[FAIL] 套用後仍有 {len(unresolved)} 筆未收斂(replace 後產生新樣態,或裁決未生效):")
        for f in unresolved[:30]:
            print(f"  {f['id']}  [{f['severity']}] {f['rule']}  {f['file']}:{f['line']}  {f['excerpt'][:80]}")
        print("請補裁決後重跑。")
        common.mark_stage(work, state, "S3_detenant", "failed", unresolved=len(unresolved))
        raise SystemExit(1)

    common.mark_stage(work, state, "S3_detenant", "passed", **applied)
    print(f"[OK] S3 完成:replace={applied['replace']} delete_file={applied['delete_file']} keep={applied['keep']}")
    print("下一步:python scripts/dc_extract.py --slug", args.slug)


if __name__ == "__main__":
    main()
