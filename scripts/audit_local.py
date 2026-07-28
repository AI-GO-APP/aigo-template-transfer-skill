#!/usr/bin/env python3
"""S6 本地 audit 硬閘:vendored 四類閘 + 本 skill 新增閘。全數 PASS 才過。

    python scripts/audit_local.py --slug my_template
    python scripts/audit_local.py --slug my_template --ai-go-backend "C:/path/to/ai-go"

新增閘(上游 audit_cli 未涵蓋、但 preflight/安裝時會炸的項目,在本地先擋):
  shape        entry、SDK 三檔、package.json 依賴、INJ 空殼、bare import 白名單
  manifest     actions/manifest.json ↔ actions/*.py 一一對應、flat dict 格式
  secrets      ctx.secrets.get 的 key ⊆ setup_schema(反向不覆蓋則 warn)
  dsl          data_center_schema 驗證(本地鏡射或權威 parser)
  legacy       禁舊制 CustomObject(meta 欄位 + *_object API)
  limits       檔數/單檔大小(AI GO 200 檔/1MB)
  paths        路徑安全(不含 \\ 與 ..)
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common
from scan import scan_template

common.add_vendor_to_path()
from audit_core import run_audit  # noqa: E402
from dsl_validator import validate_data_center_schema, validate_with_backend  # noqa: E402

_SECRET_GET_RE = re.compile(r"""\bctx\s*\.\s*secrets\s*\.\s*get\s*\(\s*['"]([^'"\n]+)['"]""")
_IMPORT_RE = re.compile(r"""(?:\bfrom|\bimport)\s+['"](?P<spec>[^'"\n]+)['"]""")
_TS_IMPORT_RE = re.compile(r"""(?:\bfrom|\bimport|\brequire)\s*\(?\s*['"](?P<spec>[^'"\n]+)['"]""")


def audit_shape(template: Path, rule: dict) -> list[str]:
    failures: list[str] = []
    if not (template / "src/main.tsx").exists() and not (template / "src/App.tsx").exists():
        failures.append("缺少 entry:src/main.tsx 或 src/App.tsx")
    for sdk in sorted(common.PROTECTED_SDK_FILES):
        if not (template / sdk).exists():
            failures.append(f"缺少 SDK 檔:{sdk}")

    pkg_path = template / "package.json"
    if not pkg_path.exists():
        failures.append("缺少 package.json")
    else:
        try:
            pkg = json.loads(pkg_path.read_text(encoding="utf-8"))
            deps = set((pkg.get("dependencies") or {}).keys())
            missing = set(rule["core_dependencies"]) - deps
            if missing:
                failures.append(f"package.json 缺核心依賴:{', '.join(sorted(missing))}")
            if pkg.get("devDependencies"):
                failures.append("package.json 不得含 devDependencies")
            if pkg.get("private") is not True:
                failures.append("package.json 應設 private: true")
        except json.JSONDecodeError as e:
            failures.append(f"package.json 非合法 JSON:{e}")

    for stub in rule["empty_stub_files"]:
        p = template / stub
        if p.exists():
            try:
                if json.loads(p.read_text(encoding="utf-8") or "{}") != {}:
                    failures.append(f"{stub} 必須是空殼 {{}}(租戶資料不得殘留)")
            except json.JSONDecodeError:
                failures.append(f"{stub} 非合法 JSON")
    for forbidden in rule["forbidden_files"]:
        if (template / forbidden).exists():
            failures.append(f"{forbidden} 不得存在(平台生成檔)")

    # bare import 白名單(鏡射 developer preflight check_imports)
    allowed = set(rule["import_map_packages"])
    for path in sorted(template.rglob("*")):
        if path.suffix not in (".ts", ".tsx", ".js", ".jsx") or not path.is_file():
            continue
        rel = path.relative_to(template).as_posix()
        for m in _TS_IMPORT_RE.finditer(path.read_text(encoding="utf-8", errors="replace")):
            spec = m.group("spec")
            if spec.startswith((".", "/", "http:", "https:", "data:")):
                continue
            pkg_name = spec if not spec.startswith("@") else "/".join(spec.split("/")[:2])
            root = pkg_name.split("/")[0] if not pkg_name.startswith("@") else pkg_name
            if root not in allowed and pkg_name not in allowed:
                failures.append(f"({rel}): 第三方套件 '{spec}' 不在 import map 白名單內")
    return failures


def audit_manifest(template: Path) -> list[str]:
    failures: list[str] = []
    actions_dir = template / "actions"
    manifest_path = actions_dir / "manifest.json"
    py_files = {p.stem for p in actions_dir.glob("*.py")} if actions_dir.is_dir() else set()

    if not actions_dir.is_dir():
        return []
    if not manifest_path.exists():
        return ["actions/ 存在但缺少 actions/manifest.json"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return [f"actions/manifest.json 非合法 JSON:{e}"]

    if isinstance(manifest, dict):
        if "actions" in manifest and isinstance(manifest.get("actions"), dict):
            failures.append("manifest 使用 nested 格式,AI GO parser 不認——請改扁平 {action_name: {...}}")
            declared = set(manifest["actions"].keys())
        else:
            declared = set(manifest.keys())
    elif isinstance(manifest, list):
        declared = {e.get("name") for e in manifest if isinstance(e, dict)}
    else:
        return ["actions/manifest.json 必須是物件或陣列"]

    for name in sorted(declared - py_files):
        failures.append(f"manifest 宣告的 action '{name}' 沒有對應的 actions/{name}.py")
    for name in sorted(py_files - declared):
        failures.append(f"actions/{name}.py 未在 manifest 宣告")
    return failures


def audit_secrets(template: Path) -> tuple[list[str], list[str]]:
    """回傳 (failures, warnings)。"""
    meta_path = template / "_template_meta.json"
    declared: set[str] = set()
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            declared = set((meta.get("setup_schema") or {}).keys())
        except json.JSONDecodeError:
            pass
    used: set[str] = set()
    for py in template.rglob("*.py"):
        used |= set(_SECRET_GET_RE.findall(py.read_text(encoding="utf-8", errors="replace")))
    failures = [f"程式碼讀取未宣告的金鑰:{k}(須加入 setup_schema)" for k in sorted(used - declared)]
    warnings = [f"setup_schema 宣告了未被讀取的金鑰:{k}" for k in sorted(declared - used)]
    return failures, warnings


def audit_dsl(template: Path, ai_go_backend: str | None) -> tuple[list[str], str]:
    meta_path = template / "_template_meta.json"
    if not meta_path.exists():
        return ["缺少 _template_meta.json(先跑 normalize_meta.py)"], "none"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return [f"_template_meta.json 非合法 JSON:{e}"], "none"
    schema = meta.get("data_center_schema")
    if ai_go_backend:
        result = validate_with_backend(schema, ai_go_backend)
        if result is not None:
            return result, "ai-go-backend"
    return validate_data_center_schema(schema), "local"


def audit_legacy(template: Path, rule: dict) -> list[str]:
    failures: list[str] = []
    meta_path = template / "_template_meta.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            for key in rule["forbid_meta_keys"]:
                if meta.get(key):
                    failures.append(f"_template_meta.json 含舊制欄位 {key}(舊制退場,不支援)")
        except json.JSONDecodeError:
            pass
    patterns = [re.compile(p) for p in rule["forbid_patterns"]]
    for py in sorted(template.rglob("*.py")):
        rel = py.relative_to(template).as_posix()
        for line_no, line in enumerate(py.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for pattern in patterns:
                if pattern.search(line):
                    failures.append(f"第 {line_no} 行 ({rel}): 舊制 CustomObject API,必須改寫為 Data Center 新制")
    return failures


def audit_limits_and_paths(template: Path, rule: dict) -> tuple[list[str], list[str]]:
    failures: list[str] = []
    warnings: list[str] = []
    files = [p for p in template.rglob("*") if p.is_file()]
    if len(files) > rule["max_files_fail"]:
        failures.append(f"檔數 {len(files)} 超過 AI GO 上限 {rule['max_files_fail']}")
    elif len(files) > rule["max_files_warn"]:
        warnings.append(f"檔數 {len(files)} 接近 AI GO 上限 {rule['max_files_fail']}")
    for p in files:
        rel = p.relative_to(template).as_posix()
        if p.stat().st_size > rule["max_file_bytes"]:
            failures.append(f"{rel} 超過單檔上限 {rule['max_file_bytes']} bytes")
        if "\\" in rel or ".." in rel.split("/"):
            failures.append(f"路徑不安全:{rel}")
    return failures, warnings


def audit_pollution_rescan(work: Path, template: Path) -> list[str]:
    """污染複掃兜底:S3 之後(demo 資料、meta、閘內手改)混入的新污染在此擋下。
    任何非 info 且沒有用戶 keep 裁決的 finding 都是失敗。"""
    rules_cfg = common.load_config("scan_rules.json")
    fd = common.load_decisions(work).get("findings", {})
    failures: list[str] = []
    for f in scan_template(template, rules_cfg):
        if f["severity"] == "info":
            continue
        d = fd.get(f["id"])
        if isinstance(d, dict) and d.get("decided_by") == "user" and d.get("action") == "keep":
            continue
        failures.append(f"[{f['severity']}] {f['rule']} {f['file']}:{f['line']} {f['excerpt'][:80]}"
                        f"(回 Phase 3 補裁決)")
    return failures


def main() -> None:
    common.utf8_stdout()
    parser = argparse.ArgumentParser(description="S6 本地 audit 硬閘")
    parser.add_argument("--slug", required=True)
    parser.add_argument("--ai-go-backend", help="ai-go repo 路徑,DSL 用權威 parser 驗證")
    args = parser.parse_args()

    work = common.work_dir(args.slug)
    template = work / "template"
    state = common.require_stage(work, "S6_audit", optional_ok=("S5_demo_data",))
    rules = common.load_config("audit_rules.json")

    results: dict[str, list[str]] = dict(run_audit(template, rules))
    results["形狀(shape)"] = audit_shape(template, rules["shape"])
    results["Manifest 對應"] = audit_manifest(template)
    secret_fails, secret_warns = audit_secrets(template)
    results["Secrets 覆蓋"] = secret_fails
    dsl_errors, dsl_by = audit_dsl(template, args.ai_go_backend)
    results[f"DSL 驗證({dsl_by})"] = dsl_errors
    results["舊制禁用"] = audit_legacy(template, rules["legacy"])
    limit_fails, limit_warns = audit_limits_and_paths(template, rules["limits"])
    results["檔數/路徑上限"] = limit_fails
    results["污染複掃"] = audit_pollution_rescan(work, template)

    all_pass = True
    for name, failures in results.items():
        if failures:
            all_pass = False
            print(f"[FAIL] {name}({len(failures)})")
            for msg in failures:
                print(f"   {msg}")
        else:
            print(f"[OK]   {name}")
    for w in secret_warns + limit_warns:
        print(f"[WARN] {w}")
    print("[NOTE] tags 白名單與 preflight 由 S7 在平台端驗證")

    report = {name: failures for name, failures in results.items()}
    report["_warnings"] = secret_warns + limit_warns
    common.dump_json(work / "audit_report.json", report)

    if not all_pass:
        common.mark_stage(work, state, "S6_audit", "failed")
        raise SystemExit(1)
    common.mark_stage(work, state, "S6_audit", "passed", dsl_validated_by=dsl_by)
    print(f"\n[OK] S6 全數通過 → {work / 'audit_report.json'}")
    print("下一步:python scripts/devportal.py push --slug", args.slug)


if __name__ == "__main__":
    main()
