#!/usr/bin/env python3
"""S1 抽取正規化:從線上 app 或本地 repo 取得 VFS,落成 work/<slug>/template/ 標準佈局。

    # 線上 custom app(AIGO_TOKEN 環境變數,或 AIGO_EMAIL + 互動輸入密碼)
    python scripts/acquire.py --slug my_template --from-app <app_id_or_slug>

    # 本地 repo(A 層標準佈局自動偵測;B 層依 layout_profiles 偵測)
    python scripts/acquire.py --slug my_template --from-repo <path>
    python scripts/acquire.py --slug my_template --from-repo <path> --vfs-subdir admin
    python scripts/acquire.py --slug my_template --from-repo <path> --mapping mapping.json

處理原則:
- SDK 三檔(src/api.ts, db.ts, action.ts)照抄——模板需要包含 canonical SDK。
- INJ 三檔(src/data.json, db.json, actions.json)是租戶資料快照:
  原始內容存到 raw/ 供 S4 參考;template/ 內 data.json、db.json 一律寫 {} 空殼,
  actions.json 不落地(平台生成)。
- 其餘檔案原樣複製(排除 node_modules/.git/__pycache__ 等)。
- 完成後做形狀檢查:entry 檔、package.json。任何一項缺 → S1 不過。
"""
import argparse
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import aigo_client
import common

_URL_RE = re.compile(r"https?://([A-Za-z0-9.\-]+)")
_EGRESS_SLUG_RE = re.compile(r"ctx\.http\.(?:call|fetch)\s*\(\s*['\"]([^'\"\n]+)['\"]")
_LEGACY_API_RE = re.compile(
    r"ctx\.db\.(?:query_object|insert_object|update_object|remove_object|list_custom_objects)"
    r"|\b(?:submitRecord|listRecords|updateRecord|deleteRecord)\s*\(")


def fetch_app_vfs(env: dict, app_id: str) -> dict:
    """GET /api/v1/builder/apps/{app_id} → 完整 app_info(含 vfs_state)。"""
    try:
        status, app_info = aigo_client.api(env, "GET", f"builder/apps/{app_id}")
    except RuntimeError as e:
        raise SystemExit(f"[FAIL] {e}")
    if status != 200:
        raise SystemExit(f"[FAIL] 取得 app 失敗(HTTP {status}):{app_info.get('detail', app_info)}")
    return app_info


def build_inventory(template: Path, env: dict, app_id: str | None) -> dict:
    """盤點不隨 VFS 走的 app/租戶級資源:webhook 宣告、對外網域、排程、legacy 痕跡。

    對齊 builder skill Phase 0 步驟 5/7/8——這些不盤,轉出來的模板會默默丟能力。"""
    inventory: dict = {"webhooks": [], "egress_domains": [], "egress_slugs": [],
                       "crons": [], "crons_note": "", "legacy_usage": []}

    manifest_path = template / "actions" / "manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(manifest, dict):
                for name, cfg in manifest.items():
                    if isinstance(cfg, dict) and cfg.get("webhook"):
                        inventory["webhooks"].append(name)
            if (template / "actions" / "receive_webhook.py").exists() \
                    and "receive_webhook" not in inventory["webhooks"]:
                inventory["webhooks"].append("receive_webhook")
        except json.JSONDecodeError:
            pass

    domains: set[str] = set()
    slugs: set[str] = set()
    actions_dir = template / "actions"
    if actions_dir.is_dir():
        for py in actions_dir.rglob("*.py"):
            text = py.read_text(encoding="utf-8", errors="replace")
            domains |= {d for d in _URL_RE.findall(text)
                        if d not in ("localhost", "127.0.0.1")}
            slugs |= set(_EGRESS_SLUG_RE.findall(text))
            for m in _LEGACY_API_RE.finditer(text):
                inventory["legacy_usage"].append(
                    f"{py.relative_to(template).as_posix()}: {m.group(0)}")
    for ts in template.rglob("*.ts*"):
        if ts.is_file():
            for m in _LEGACY_API_RE.finditer(ts.read_text(encoding="utf-8", errors="replace")):
                inventory["legacy_usage"].append(
                    f"{ts.relative_to(template).as_posix()}: {m.group(0)}")
    inventory["egress_domains"] = sorted(domains)
    inventory["egress_slugs"] = sorted(slugs)

    if app_id:
        try:
            status, crons = aigo_client.api(env, "GET", "app-crons")
            if status == 200:
                items = crons if isinstance(crons, list) else crons.get("items", [])
                inventory["crons"] = [c for c in items
                                      if str(c.get("app_id", "")) in ("", str(app_id))]
            else:
                inventory["crons_note"] = f"GET /app-crons 失敗(HTTP {status}),請人工確認排程"
        except RuntimeError:
            inventory["crons_note"] = "無 AI GO 憑證,未盤點排程"
    else:
        inventory["crons_note"] = "repo 來源無線上 app,無法盤點排程;若原 app 已上線請人工確認"
    return inventory


def detect_layout(repo: Path, profiles_cfg: dict, vfs_subdir: str | None) -> tuple[Path, str]:
    """依 layout_profiles 偵測 VFS 根。回傳 (vfs_root, profile_name)。"""
    markers = profiles_cfg["entry_markers"]

    def has_entry(d: Path) -> bool:
        return any((d / m).exists() for m in markers)

    for profile in profiles_cfg["profiles"]:
        root = repo / profile["vfs_root"] if profile["vfs_root"] != "." else repo
        if not root.is_dir():
            continue
        if profile.get("multi"):
            subdirs = [d for d in sorted(root.iterdir()) if d.is_dir() and has_entry(d)]
            if not subdirs:
                continue
            if vfs_subdir:
                target = root / vfs_subdir
                if not has_entry(target):
                    raise SystemExit(f"[FAIL] --vfs-subdir {vfs_subdir} 下找不到 entry 檔")
                return target, f"{profile['name']}:{vfs_subdir}"
            names = ", ".join(d.name for d in subdirs)
            raise SystemExit(
                f"[FAIL] 偵測到多 app 佈局({root}),請以 --vfs-subdir 指定其一:{names}")
        if has_entry(root):
            return root, profile["name"]

    raise SystemExit(
        "[FAIL] 無法偵測 VFS 佈局(所有 profile 都找不到 src/main.tsx 或 src/App.tsx)。\n"
        "自開發佈局請提供 --mapping <json>,格式:"
        '{"vfs_root": "<相對路徑>", "actions_root": "<選填>", "meta_paths": ["<選填>"]}')


def copy_tree(src: Path, dest: Path, exclude_dirs: set[str], raw_dir: Path) -> tuple[int, list[str]]:
    """複製 VFS 檔案樹;INJ 檔改寫空殼並把原始內容留在 raw/。回傳 (檔數, 注意事項)。"""
    notes: list[str] = []
    count = 0
    for path in sorted(src.rglob("*")):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(src).parts
        if any(part in exclude_dirs for part in rel_parts):
            continue
        rel = "/".join(rel_parts)
        out = dest / Path(*rel_parts)

        if rel in common.INJECTED_FILES:
            raw_out = raw_dir / Path(*rel_parts)
            raw_out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, raw_out)
            if rel == "src/actions.json":
                notes.append(f"{rel}:平台生成檔,不落入 template/(原檔在 raw/)")
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text("{}\n", encoding="utf-8")
            try:
                original = json.loads(path.read_text(encoding="utf-8") or "{}")
                if original:
                    notes.append(f"{rel}:原含租戶資料({len(original)} 鍵),已改寫為空殼,原檔在 raw/")
            except (json.JSONDecodeError, UnicodeDecodeError):
                notes.append(f"{rel}:原檔非合法 JSON,已改寫為空殼")
            count += 1
            continue

        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, out)
        count += 1
    return count, notes


def shape_check(template: Path) -> list[str]:
    problems: list[str] = []
    if not (template / "src" / "main.tsx").exists() and not (template / "src" / "App.tsx").exists():
        problems.append("缺少 entry:src/main.tsx 或 src/App.tsx")
    if not (template / "package.json").exists():
        problems.append("缺少 package.json")
    for sdk in common.PROTECTED_SDK_FILES:
        if not (template / Path(sdk)).exists():
            problems.append(f"缺少 SDK 檔:{sdk}(可從 starter 模板補上 canonical 版本)")
    return problems


def main() -> None:
    common.utf8_stdout()
    parser = argparse.ArgumentParser(description="S1 抽取正規化")
    parser.add_argument("--slug", required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--from-app", help="線上 custom app 的 id 或 slug")
    source.add_argument("--from-repo", help="本地 repo 路徑")
    parser.add_argument("--vfs-subdir", help="多 app 佈局時指定子目錄")
    parser.add_argument("--mapping", help="自訂佈局對映 JSON 檔路徑")
    args = parser.parse_args()

    work = common.work_dir(args.slug)
    state = common.require_stage(work, "S1_acquire")

    template = work / "template"
    raw_dir = work / "raw"
    if template.exists():
        shutil.rmtree(template)
    template.mkdir(parents=True)
    raw_dir.mkdir(exist_ok=True)

    profiles_cfg = common.load_config("layout_profiles.json")
    exclude_dirs = set(profiles_cfg["exclude_dirs"])
    notes: list[str] = []

    if args.from_app:
        env = common.load_env()
        app_info = fetch_app_vfs(env, args.from_app)
        vfs_state: dict[str, str] = app_info.get("vfs_state", {}) or {}
        if not vfs_state:
            raise SystemExit("[FAIL] app 的 vfs_state 為空")
        common.dump_json(raw_dir / "app_info.json", {
            k: v for k, v in app_info.items() if k not in ("vfs_state", "published_vfs")})
        common.dump_json(raw_dir / "vfs_state.json", vfs_state)
        count = 0
        for rel, content in sorted(vfs_state.items()):
            rel = rel.lstrip("/")
            if rel in common.INJECTED_FILES:
                raw_out = raw_dir / Path(*rel.split("/"))
                raw_out.parent.mkdir(parents=True, exist_ok=True)
                raw_out.write_text(content, encoding="utf-8")
                if rel == "src/actions.json":
                    notes.append(f"{rel}:平台生成檔,不落入 template/(原檔在 raw/)")
                    continue
                out = template / Path(*rel.split("/"))
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text("{}\n", encoding="utf-8")
                if content.strip() not in ("", "{}"):
                    notes.append(f"{rel}:原含租戶資料,已改寫為空殼,原檔在 raw/")
                count += 1
                continue
            out = template / Path(*rel.split("/"))
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(content, encoding="utf-8")
            count += 1
        source_desc = f"app:{args.from_app}"
        profile_name = "online"
    else:
        repo = Path(args.from_repo).resolve()
        if not repo.is_dir():
            raise SystemExit(f"[FAIL] repo 路徑不存在:{repo}")
        if args.mapping:
            mapping = common.load_json(Path(args.mapping))
            vfs_root = repo / mapping["vfs_root"]
            if not vfs_root.is_dir():
                raise SystemExit(f"[FAIL] mapping 的 vfs_root 不存在:{vfs_root}")
            profile_name = "mapping"
        else:
            vfs_root, profile_name = detect_layout(repo, profiles_cfg, args.vfs_subdir)
        count, copy_notes = copy_tree(vfs_root, template, exclude_dirs, raw_dir)
        notes.extend(copy_notes)

        # actions/ 可能在 vfs_root 之外(mapping 指定)
        if args.mapping:
            mapping = common.load_json(Path(args.mapping))
            actions_root = mapping.get("actions_root")
            if actions_root and not (template / "actions").is_dir():
                a_count, a_notes = copy_tree(
                    repo / actions_root, template / "actions", exclude_dirs, raw_dir)
                count += a_count
                notes.extend(a_notes)
            for meta_rel in mapping.get("meta_paths", []):
                src_meta = repo / meta_rel
                if src_meta.exists():
                    dest = work / "source_meta" / src_meta.name
                    dest.parent.mkdir(exist_ok=True)
                    shutil.copy2(src_meta, dest)

        # 舊 meta 檔移到 source_meta/ 供 normalize_meta 參考,不留在 template/
        # (FDE repo 常把 _template.json 放 repo 根、vfs 放子目錄,兩處都收)
        for meta_name in profiles_cfg["meta_candidates"]:
            for candidate, move in ((template / meta_name, True), (repo / meta_name, False)):
                if candidate.exists():
                    dest = work / "source_meta" / meta_name
                    dest.parent.mkdir(exist_ok=True)
                    if move:
                        shutil.move(str(candidate), dest)
                    elif not dest.exists():
                        shutil.copy2(candidate, dest)
                    notes.append(f"{meta_name}:收進 source_meta/,S6 前由 normalize_meta.py 重建")
                    break
        source_desc = f"repo:{repo}"

    problems = shape_check(template)
    for note in notes:
        print(f"[NOTE] {note}")
    if problems:
        for p in problems:
            print(f"[FAIL] {p}")
        common.mark_stage(work, state, "S1_acquire", "failed",
                          source=source_desc, files=count, problems=problems)
        raise SystemExit(1)

    # 盤點不隨 VFS 走的資源(webhook/egress/排程/legacy)→ inventory.json
    env = common.load_env()
    inventory = build_inventory(template, env, args.from_app)
    common.dump_json(work / "inventory.json", inventory)
    if inventory["webhooks"]:
        print(f"[NOTE] webhook 宣告:{', '.join(inventory['webhooks'])}(對外端點,進安裝後設定清單)")
    if inventory["egress_domains"]:
        print(f"[NOTE] 對外網域:{', '.join(inventory['egress_domains'])}(需 Egress 白名單,進安裝後設定清單)")
    if inventory["crons"]:
        print(f"[NOTE] 排程 {len(inventory['crons'])} 條(模板無法帶走,進安裝後設定清單)")
    if inventory["crons_note"]:
        print(f"[NOTE] {inventory['crons_note']}")
    if inventory["legacy_usage"]:
        print(f"[NOTE] legacy CustomObject 痕跡 {len(inventory['legacy_usage'])} 處(S2/S3 會要求改寫)")

    common.mark_stage(work, state, "S1_acquire", "passed",
                      source=source_desc, layout=profile_name, files=count,
                      webhooks=len(inventory["webhooks"]),
                      egress_domains=len(inventory["egress_domains"]),
                      crons=len(inventory["crons"]))
    print(f"[OK] S1 完成:{count} 檔 → {template}(佈局:{profile_name})")
    print("下一步:python scripts/scan.py --slug", args.slug)


if __name__ == "__main__":
    main()
