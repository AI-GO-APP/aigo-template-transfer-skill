#!/usr/bin/env python3
"""S4 Data Center schema:撈租戶自建表 → 產新制 data_center_schema 草稿並驗證。

    # 列出租戶所有自建表(人工從中挑選屬於此 app 的表)
    python scripts/dc_extract.py --slug my_template --list

    # 以挑選的表產 DSL 草稿(--tables 即人工挑表的裁決,會記入 decisions.json)
    python scripts/dc_extract.py --slug my_template --tables csd_tickets,csd_replies

    # 此 app 不用任何自建表
    python scripts/dc_extract.py --slug my_template --none

    # 以權威 parser 驗證(可選;找不到後端時自動降級本地驗證)
    python scripts/dc_extract.py --slug my_template --tables ... --ai-go-backend "C:/path/to/ai-go"

一律產新制 data_center_schema(version=1);不讀、不轉任何舊制 custom_objects_schema。
另外交叉檢查:template 內 actions 用 ctx.db.query_table 等引用的表名,必須被 DSL 覆蓋。
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common

common.add_vendor_to_path()
from dsl_validator import validate_data_center_schema, validate_with_backend  # noqa: E402

_TABLE_REF_RE = re.compile(
    r"ctx\.db\.(?:query_table|insert_row|update_row|delete_row)\s*\(\s*['\"]([^'\"\n]+)['\"]"
)


def get_aigo_token(env: dict) -> str:
    token = env.get("AIGO_TOKEN")
    if token:
        return token
    import getpass
    email = env.get("AIGO_EMAIL") or input("AI GO 帳號 email:").strip()
    password = getpass.getpass("AI GO 密碼(不會儲存):")
    status, payload = common.http_call(
        "POST", f"{env['AIGO_BASE_URL'].rstrip('/')}/api/v1/auth/login",
        body={"email": email, "password": password})
    if status != 200:
        raise SystemExit(f"[FAIL] AI GO 登入失敗(HTTP {status}):{payload.get('detail', payload)}")
    return payload["access_token"]


def fetch_tables(env: dict, token: str) -> list[dict]:
    base = env["AIGO_BASE_URL"].rstrip("/")
    status, payload = common.http_call(f"GET", f"{base}/api/v1/data-center/tables", token=token)
    if status != 200:
        raise SystemExit(f"[FAIL] 撈表失敗(HTTP {status}):{payload}")
    return payload if isinstance(payload, list) else payload.get("items", payload.get("tables", []))


def fetch_table_detail(env: dict, token: str, key: str) -> dict:
    base = env["AIGO_BASE_URL"].rstrip("/")
    status, payload = common.http_call(f"GET", f"{base}/api/v1/data-center/tables/{key}", token=token)
    if status != 200:
        raise SystemExit(f"[FAIL] 撈表 {key} 失敗(HTTP {status}):{payload}")
    return payload


def table_to_dsl(detail: dict) -> dict:
    """租戶表定義 → DSL 表。欄位鍵名對映後端 DcTable/DcField 的讀取形狀。"""
    fields = []
    for f in detail.get("fields", []):
        key = f.get("key") or f.get("field_key") or f.get("physical_name")
        ftype = f.get("type") or f.get("field_type") or "text"
        if key in ("id", "created_at", "updated_at"):
            continue  # 系統欄不入 DSL(cs_desk 曾因此過不了官方 parser)
        entry: dict = {
            "key": key,
            "display_name": f.get("display_name") or f.get("name") or key,
            "type": ftype,
        }
        if f.get("is_required") or f.get("required"):
            entry["required"] = True
        if f.get("is_unique") or f.get("unique"):
            entry["unique"] = True
        if f.get("options"):
            entry["options"] = list(f["options"])
        if ftype == "relation":
            if f.get("target_table"):
                entry["target_table"] = f["target_table"]
            elif f.get("target_erp_key"):
                entry["target_erp_key"] = f["target_erp_key"]
        fields.append(entry)
    return {
        "key": detail.get("key") or detail.get("physical_name"),
        "display_name": detail.get("display_name") or detail.get("name") or detail.get("key"),
        "fields": fields,
    }


def referenced_tables(template: Path) -> set[str]:
    refs: set[str] = set()
    actions = template / "actions"
    if actions.is_dir():
        for py in actions.rglob("*.py"):
            try:
                refs |= set(_TABLE_REF_RE.findall(py.read_text(encoding="utf-8")))
            except (UnicodeDecodeError, OSError):
                continue
    return refs


def main() -> None:
    common.utf8_stdout()
    parser = argparse.ArgumentParser(description="S4 Data Center schema")
    parser.add_argument("--slug", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--list", action="store_true", help="列出租戶所有自建表(不動狀態機)")
    mode.add_argument("--tables", help="逗號分隔的表 key 清單(人工挑選結果)")
    mode.add_argument("--none", action="store_true", help="此 app 不使用任何自建表")
    mode.add_argument("--from-file", help="離線來源:表定義 JSON(list[table detail])")
    parser.add_argument("--ai-go-backend", help="ai-go repo 路徑,用權威 parser 驗證")
    args = parser.parse_args()

    work = common.work_dir(args.slug)
    template = work / "template"
    env = common.load_env()

    if args.list:
        token = get_aigo_token(env)
        tables = fetch_tables(env, token)
        refs = referenced_tables(template)
        print(f"租戶自建表({len(tables)} 張;* = 本 app 的 actions 有引用):")
        for t in tables:
            key = t.get("key") or t.get("physical_name")
            mark = "*" if key in refs else " "
            print(f"  {mark} {key:<32} {t.get('display_name', '')}")
        if refs:
            print(f"\nactions 引用的表:{', '.join(sorted(refs))}")
        print("\n挑好後執行:python scripts/dc_extract.py --slug", args.slug, "--tables key1,key2")
        return

    state = common.require_stage(work, "S4_dc_schema")
    refs = referenced_tables(template)

    if args.none:
        if refs:
            raise SystemExit(f"[FAIL] --none 但 actions 引用了自建表:{', '.join(sorted(refs))}")
        schema = {"version": 1, "tables": []}
        selected: list[str] = []
    else:
        if args.from_file:
            details = common.load_json(Path(args.from_file))
            selected = [d.get("key") or d.get("physical_name") for d in details]
        else:
            selected = [k.strip() for k in args.tables.split(",") if k.strip()]
            token = get_aigo_token(env)
            details = [fetch_table_detail(env, token, key) for key in selected]
        schema = {"version": 1, "tables": [table_to_dsl(d) for d in details]}

    # 交叉檢查:actions 引用的表必須被 DSL 覆蓋
    declared = {t["key"] for t in schema["tables"]}
    missing = refs - declared
    if missing:
        raise SystemExit(f"[FAIL] actions 引用了未納入 DSL 的表:{', '.join(sorted(missing))}。"
                         f"請補進 --tables 或改寫 action。")
    unused = declared - refs
    if unused:
        print(f"[WARN] DSL 宣告了 actions 未引用的表:{', '.join(sorted(unused))}"
              f"(前端經 proxy 使用則屬正常,請確認)")

    # 驗證:優先權威 parser,降級本地
    validated_by = "local"
    if args.ai_go_backend:
        result = validate_with_backend(schema, args.ai_go_backend)
        if result is None:
            print("[WARN] 無法載入 ai-go 後端 parser,降級為本地驗證")
            errors = validate_data_center_schema(schema)
        else:
            errors = result
            validated_by = "ai-go-backend"
    else:
        errors = validate_data_center_schema(schema)

    if errors:
        print(f"[FAIL] DSL 驗證失敗({len(errors)} 項):")
        for e in errors:
            print(f"  {e}")
        raise SystemExit(1)

    common.dump_json(work / "dc_schema.json", schema)

    decisions = common.load_decisions(work)
    decisions["dc_tables"] = {
        "decision": "none" if args.none else ",".join(selected),
        "decided_by": "user",
        "at": common._now(),
        "notes": "表清單由用戶以 --tables/--none 指定(挑表即裁決)",
    }
    common.save_decisions(work, decisions)

    common.mark_stage(work, state, "S4_dc_schema", "passed",
                      tables=len(schema["tables"]), validated_by=validated_by)
    print(f"[OK] S4 完成:{len(schema['tables'])} 張表 → {work / 'dc_schema.json'}(驗證:{validated_by})")
    print("下一步:起草 demo 資料(SKILL.md Phase 5),或 transfer_cli.py gate --stage S5 --decision skipped")


if __name__ == "__main__":
    main()
