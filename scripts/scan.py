#!/usr/bin/env python3
"""S2 污染掃描:依 config/scan_rules.json 產出待裁決清單。只報告,不改任何檔。

    python scripts/scan.py --slug my_template
    python scripts/scan.py --slug my_template --rescan   # S3 套用後複掃(不動狀態機)

finding id 以 (rule, 檔案, 行內容, 同內容第幾次出現) 計算,行號位移不會讓裁決失效。
"""
import argparse
import hashlib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common

SEVERITY_ORDER = {"blocker": 0, "high": 1, "medium": 2, "info": 3}


def finding_id(rule_id: str, rel: str, line_text: str, occurrence: int) -> str:
    h = hashlib.sha1(f"{rule_id}|{rel}|{line_text.strip()}|{occurrence}".encode("utf-8"))
    return h.hexdigest()[:12]


def scan_template(template: Path, rules_cfg: dict) -> list[dict]:
    findings: list[dict] = []
    compiled = []
    for rule in rules_cfg["rules"]:
        compiled.append((rule, re.compile(rule["pattern"])))

    for path in sorted(template.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(template).as_posix()
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        seen_occurrence: dict[tuple[str, str], int] = {}
        for line_no, line in enumerate(lines, start=1):
            for rule, pattern in compiled:
                if path.suffix not in rule.get("extensions", []):
                    continue
                if rel in rule.get("exclude_files", []):
                    continue
                m = pattern.search(line)
                if not m:
                    continue
                if any(ex in line for ex in rule.get("exclude_patterns", [])):
                    continue
                key = (rule["id"], line.strip())
                occurrence = seen_occurrence.get(key, 0)
                seen_occurrence[key] = occurrence + 1
                findings.append({
                    "id": finding_id(rule["id"], rel, line, occurrence),
                    "rule": rule["id"],
                    "severity": rule["severity"],
                    "file": rel,
                    "line": line_no,
                    "excerpt": line.strip()[:200],
                    "captured": m.group(1) if rule.get("capture") and m.groups() else None,
                    "description": rule["description"],
                    "suggestion": rule.get("suggestion", ""),
                })
    findings.sort(key=lambda f: (SEVERITY_ORDER.get(f["severity"], 9), f["file"], f["line"]))
    return findings


def main() -> None:
    common.utf8_stdout()
    parser = argparse.ArgumentParser(description="S2 污染掃描")
    parser.add_argument("--slug", required=True)
    parser.add_argument("--rescan", action="store_true",
                        help="僅重新產出報告,不推進狀態機(S3 內部複掃用)")
    args = parser.parse_args()

    work = common.work_dir(args.slug)
    template = work / "template"
    rules_cfg = common.load_config("scan_rules.json")

    if not args.rescan:
        state = common.require_stage(work, "S2_scan")

    findings = scan_template(template, rules_cfg)
    common.dump_json(work / "scan_report.json", {"findings": findings})

    by_severity: dict[str, int] = {}
    for f in findings:
        by_severity[f["severity"]] = by_severity.get(f["severity"], 0) + 1
    print(f"[OK] 掃描完成:{len(findings)} 筆 → {work / 'scan_report.json'}")
    for sev in ("blocker", "high", "medium", "info"):
        if by_severity.get(sev):
            print(f"  {sev:>8}: {by_severity[sev]}")

    if not args.rescan:
        common.mark_stage(work, state, "S2_scan", "passed",
                          findings=len(findings), by_severity=by_severity)
        print("下一步:逐條裁決寫入 decisions.json(見 SKILL.md Phase 3),"
              "再跑 python scripts/apply_decisions.py --slug", args.slug)


if __name__ == "__main__":
    main()
