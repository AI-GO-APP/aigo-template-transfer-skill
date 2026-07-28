#!/usr/bin/env python3
"""建立/更新 template/_template_meta.json:單一合規 meta(S6 audit 的前置工具)。

    python scripts/normalize_meta.py --slug my_template \
        --name "客服工單中心" --category messaging --access-mode internal \
        --description "..." --author "AI GO" --version 1.0.0

來源優先序:CLI 參數 > work/<slug>/source_meta/ 的舊 meta(僅取白名單欄位)> 預設值。
data_center_schema 一律取自 work/<slug>/dc_schema.json(S4 產物);
setup_schema 由 CLI --setup-schema <json 檔> 提供或沿用舊 meta。
舊 meta 的 custom_objects_schema / factory_key / template_version / generated_at / source
一律丟棄(舊制退場 + repo 內部欄位不上平台)。
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common

# 舊 meta 可繼承的欄位(與 Developer 平台 metadata 語義對齊)
INHERIT_KEYS = [
    "name", "description", "long_description", "icon_emoji", "category",
    "tags", "access_mode", "setup_schema", "data_references_schema", "author", "version",
]
CATEGORIES = {
    "starter", "messaging", "crm", "catering", "integration",
    "ai", "operations", "productivity", "analytics",
}
ACCESS_MODES = {"internal", "external", "self_built"}


def refresh_inventory(work, template) -> dict:
    """以目前 template 內容重盤 webhook/egress/legacy(S1 快照在 S3 改寫後會過時,
    例:客戶網域已被替換,清單卻還列舊網域);排程與其註記保留 S1 結果(與內容無關)。"""
    from acquire import build_inventory
    inv_path = work / "inventory.json"
    old = common.load_json(inv_path) if inv_path.exists() else {}
    fresh = build_inventory(template, {}, None)
    fresh["crons"] = old.get("crons", [])
    fresh["crons_note"] = old.get("crons_note", "")
    common.dump_json(inv_path, fresh)
    return fresh


def build_post_install_checklist(work, meta: dict) -> str:
    """從 inventory.json 與 setup_schema 生成「安裝後設定」markdown 段落。
    這些是不隨模板 VFS 走的租戶級設定,不寫清楚 = 安裝後功能默默失效。"""
    template = work / "template"
    if template.is_dir():
        inventory = refresh_inventory(work, template)
    else:
        inv_path = work / "inventory.json"
        inventory = common.load_json(inv_path) if inv_path.exists() else {}
    lines: list[str] = []

    secrets = list((meta.get("setup_schema") or {}).keys())
    if secrets:
        lines.append("1. **金鑰設定**:安裝表單會詢問 " + "、".join(f"`{k}`" for k in secrets)
                     + ";未填的功能將無法運作。")
    if inventory.get("egress_domains"):
        lines.append("2. **Egress 白名單**:本模板的 action 會對外呼叫,"
                     "請租戶管理員在後台 `/dashboard/settings/integrations` 加入網域:"
                     + "、".join(f"`{d}`" for d in inventory["egress_domains"])
                     + "。白名單未設定前,對外呼叫一律被擋(這是設定問題,非程式錯誤)。")
    if inventory.get("webhooks"):
        lines.append("3. **Webhook 端點**:" + "、".join(f"`{w}`" for w in inventory["webhooks"])
                     + " 為對外接收端點,發布後請到事件來源系統重新登記新 URL"
                     "(同一事件源不可同時登記新舊兩條,會重複執行)。")
    if inventory.get("crons"):
        cron_lines = []
        for c in inventory["crons"]:
            name = c.get("name") or c.get("action_name") or "?"
            sched = c.get("cron") or c.get("schedule") or c.get("interval") or "?"
            cron_lines.append(f"`{name}`({sched})")
        lines.append("4. **排程重建**:原 app 綁有排程,模板無法帶走,"
                     "請安裝後到 `/dashboard/settings/app-crons` 重建:"
                     + "、".join(cron_lines) + "。")

    if not lines:
        return ""
    return "## 安裝後設定\n\n" + "\n".join(lines)


def main() -> None:
    common.utf8_stdout()
    parser = argparse.ArgumentParser(description="建立單一合規 _template_meta.json")
    parser.add_argument("--slug", required=True)
    parser.add_argument("--name")
    parser.add_argument("--description")
    parser.add_argument("--long-description")
    parser.add_argument("--icon-emoji")
    parser.add_argument("--category")
    parser.add_argument("--access-mode")
    parser.add_argument("--author")
    parser.add_argument("--version", default=None)
    parser.add_argument("--tags", help="逗號分隔(S7 會對平台 /refs/tags 驗證)")
    parser.add_argument("--setup-schema", help="setup_schema JSON 檔路徑")
    args = parser.parse_args()

    work = common.work_dir(args.slug)
    template = work / "template"
    if not template.is_dir():
        raise SystemExit("[FAIL] template/ 不存在,請先完成 S1")
    # 本工具是 S6 的閘內前置:確認 S5(含)之前已完成,寫檔後重新對齊雜湊
    state = common.require_stage(work, "S6_audit", optional_ok=("S5_demo_data",),
                                 allow_content_change=True)

    meta: dict = {}

    # 1. 舊 meta 白名單繼承
    source_meta_dir = work / "source_meta"
    if source_meta_dir.is_dir():
        for candidate in ("_template_meta.json", "_template.json"):
            p = source_meta_dir / candidate
            if p.exists():
                try:
                    old = common.load_json(p)
                except ValueError:
                    continue
                for key in INHERIT_KEYS:
                    if old.get(key) and key not in meta:
                        meta[key] = old[key]

    # 2. CLI 覆寫
    overrides = {
        "name": args.name, "description": args.description,
        "long_description": args.long_description, "icon_emoji": args.icon_emoji,
        "category": args.category, "access_mode": args.access_mode,
        "author": args.author, "version": args.version,
    }
    for key, value in overrides.items():
        if value:
            meta[key] = value
    if args.tags:
        meta["tags"] = [t.strip() for t in args.tags.split(",") if t.strip()]
    if args.setup_schema:
        meta["setup_schema"] = common.load_json(Path(args.setup_schema))

    # 3. 固定欄位與預設
    meta["slug"] = args.slug
    meta.setdefault("version", "1.0.0")
    meta.setdefault("access_mode", "internal")

    # 4. DSL 取自 S4 產物
    dc_path = work / "dc_schema.json"
    if dc_path.exists():
        schema = common.load_json(dc_path)
        if schema.get("tables"):
            meta["data_center_schema"] = schema
        else:
            meta.pop("data_center_schema", None)

    # 4.5 安裝後設定清單:webhook/排程/Egress 不隨模板走,必須明白告知安裝租戶
    checklist = build_post_install_checklist(work, meta)
    if checklist:
        base = meta.get("long_description") or meta.get("description") or ""
        marker = "## 安裝後設定"
        if marker in base:
            base = base.split(marker)[0].rstrip()
        meta["long_description"] = (base + "\n\n" if base else "") + checklist

    # 5. 就地驗證(必填欄位、字彙)
    problems = []
    for field in ("slug", "name", "description", "category", "version"):
        if not meta.get(field):
            problems.append(f"缺少必填欄位 {field}(以 --{field.replace('_', '-')} 提供)")
    if meta.get("category") and meta["category"] not in CATEGORIES:
        problems.append(f"category {meta['category']!r} 不在白名單 {sorted(CATEGORIES)}")
    if meta.get("access_mode") not in ACCESS_MODES:
        problems.append(f"access_mode 須為 {sorted(ACCESS_MODES)}")
    if "custom_objects_schema" in meta:
        problems.append("不得含 custom_objects_schema(舊制退場)")
    if problems:
        for p in problems:
            print(f"[FAIL] {p}")
        raise SystemExit(1)

    common.dump_json(template / "_template_meta.json", meta)
    common.refresh_hash(work, state)
    print(f"[OK] 已寫入 {template / '_template_meta.json'}")
    print("下一步:python scripts/audit_local.py --slug", args.slug)


if __name__ == "__main__":
    main()
