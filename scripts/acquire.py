#!/usr/bin/env python3
"""S1 抽取正規化:從線上 app 或本地 repo 取得 VFS,落成 work/<slug>/template/ 標準佈局。

    # 線上 custom app:先列出租戶下的 app 找出 uuid,再由用戶確認身分,最後才抽取
    python scripts/acquire.py --list-apps
    python scripts/transfer_cli.py confirm-source --slug my_template --app <uuid_or_slug>
    python scripts/acquire.py --slug my_template --from-app <app_id_or_slug>

    # repo(本地路徑或 URL;A 層標準佈局自動偵測,B 層依 layout_profiles 偵測)
    python scripts/acquire.py --slug my_template --from-repo <path>
    python scripts/acquire.py --slug my_template --from-repo https://github.com/org/repo.git
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
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import aigo_client
import common

SOURCE_DECISION_KEY = "source_app"

_URL_RE = re.compile(r"https?://([A-Za-z0-9.\-]+)")
_EGRESS_SLUG_RE = re.compile(r"ctx\.http\.(?:call|fetch)\s*\(\s*['\"]([^'\"\n]+)['\"]")
# slug 放在模組級常數裡:`OPENAI_EGRESS = "openai"` → `ctx.http.call(OPENAI_EGRESS, ...)`。
# 只認字面值直接漏掉這種寫法,而漏掉的後果是 required_egress 少宣告 →
# 租戶安裝時不會被提示授權該服務 → 裝完 action 一律連不出去。
# 0.7.0 把 ctx.http.call 定為對外呼叫的唯一正解之後,這種寫法只會更多。
_EGRESS_SLUG_VAR_RE = re.compile(r"ctx\.http\.(?:call|fetch)\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*,")
_STR_CONST_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*['\"]([^'\"\n]+)['\"]\s*$",
                           re.MULTILINE)


def _egress_slugs(text: str) -> set[str]:
    """撈出這份原始碼宣告的 egress slug,字面值與模組級字串常數都算。

    只解析同一個檔案裡的常數——跨檔 import 的常數不追(要追就得做真的
    符號解析,而漏報在這裡比誤報安全:誤報會讓模板宣告一個不存在的服務,
    租戶安裝時被要求授權一個根本用不到的東西)。
    """
    slugs = set(_EGRESS_SLUG_RE.findall(text))
    consts = dict(_STR_CONST_RE.findall(text))
    for name in _EGRESS_SLUG_VAR_RE.findall(text):
        if name in consts:
            slugs.add(consts[name])
    return slugs
_LEGACY_API_RE = re.compile(
    r"ctx\.db\.(?:query_object|insert_object|update_object|remove_object|list_custom_objects)"
    r"|\b(?:submitRecord|listRecords|updateRecord|deleteRecord)\s*\(")


def _clear_dir(path: Path, retries: int = 3) -> None:
    """清空目錄但保留目錄本體。Windows 上索引器/防毒常短暫持有目錄 handle,
    rmtree 連目錄一起刪會 WinError 32;只刪內容物 + 重試可避開。"""
    import time
    path.mkdir(parents=True, exist_ok=True)
    for attempt in range(retries):
        try:
            for child in path.iterdir():
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
            return
        except OSError:
            if attempt == retries - 1:
                raise
            time.sleep(1.0)


def fetch_app_vfs(env: dict, app_id: str) -> dict:
    """GET /api/v1/builder/apps/{app_id} → 完整 app_info(含 vfs_state)。"""
    try:
        status, app_info = aigo_client.api(env, "GET", f"builder/apps/{app_id}")
    except RuntimeError as e:
        raise SystemExit(f"[FAIL] {e}")
    if status != 200:
        raise SystemExit(f"[FAIL] 取得 app 失敗(HTTP {status}):{app_info.get('detail', app_info)}")
    return app_info


def list_apps(env: dict) -> None:
    """列出租戶下的 custom app,供用戶找出正確的 app uuid。

    平台以 `updated_at desc` 排序並做可見度過濾,故這裡看到的就是此帳號能抽的全部。"""
    try:
        status, payload = aigo_client.api(env, "GET", "builder/apps")
    except RuntimeError as e:
        raise SystemExit(f"[FAIL] {e}")
    if status != 200:
        raise SystemExit(f"[FAIL] 列出 app 失敗(HTTP {status}):"
                         f"{payload.get('detail', payload) if isinstance(payload, dict) else payload}")
    items = payload if isinstance(payload, list) else payload.get("items", [])
    print(f"租戶下可見的 custom app 共 {len(items)} 支(新到舊):\n")
    print(f"  {'slug':<28} {'status':<10} {'access_mode':<10} {'updated_at':<21} name / id")
    for app in items:
        if not isinstance(app, dict):
            continue
        print(f"  {str(app.get('slug') or '-'):<28} {str(app.get('status') or '-'):<10} "
              f"{str(app.get('access_mode') or '-'):<10} "
              f"{str(app.get('updated_at') or '-')[:19]:<21} "
              f"{app.get('name', '')}  {app.get('id')}")
    print("\n下一步(由用戶確認來源身分,uuid 打錯會轉到別支 app):")
    print("  python scripts/transfer_cli.py confirm-source --slug <slug> --app <uuid_or_slug>")


def identity_card(app_info: dict) -> str:
    """把 app 身分整理成給用戶過目的摘要——確認閘要看的就是這幾行。"""
    vfs = app_info.get("vfs_state") or {}
    actions = sorted({k.split("/")[1] for k in vfs
                      if k.lstrip("/").startswith("actions/") and k.endswith(".py")})
    lines = [
        f"  名稱      :{app_info.get('name')}",
        f"  slug      :{app_info.get('slug')}",
        f"  id (uuid) :{app_info.get('id')}",
        f"  子網域    :{app_info.get('subdomain') or '-'}",
        f"  狀態      :{app_info.get('status')}  access_mode={app_info.get('access_mode')}",
        f"  最後更新  :{str(app_info.get('updated_at') or '-')[:19]}",
        f"  VFS       :{len(vfs)} 檔;actions {len(actions)} 支"
        + (f"({', '.join(actions[:8])}{' …' if len(actions) > 8 else ''})" if actions else ""),
    ]
    return "\n".join(lines)


def require_source_decision(work: Path, slug: str) -> dict:
    """來源身分閘:抽取線上 app 前,用戶必須先確認過「是這一支」。
    先驗裁決存在再連線——憑證/網路都正常但抽錯 app,是最貴的錯。"""
    entry = common.load_decisions(work).get(SOURCE_DECISION_KEY)
    if not isinstance(entry, dict) or entry.get("decided_by") != "user":
        raise SystemExit(
            "[FAIL] 人工閘:尚未確認來源 app 的身分(decisions.json 缺 source_app)。\n"
            "       app uuid 打錯不會報錯,只會安靜地轉走另一支 app 的內容,故必須由用戶親自確認:\n"
            f"       python scripts/acquire.py --list-apps            # 先找出正確的 uuid\n"
            f"       python scripts/transfer_cli.py confirm-source --slug {slug} --app <uuid_or_slug>")
    return entry


def verify_source_identity(entry: dict, app_info: dict) -> None:
    """比對「用戶確認過的那支」與「這次真的抓到的那支」是否同一支。"""
    confirmed = str(entry.get("app_id") or "")
    fetched = str(app_info.get("id") or "")
    if confirmed != fetched:
        raise SystemExit(
            f"[FAIL] 來源身分不符:用戶確認的是 {entry.get('app_slug')}({confirmed}),"
            f"這次抓到的是 {app_info.get('slug')}({fetched})。\n"
            f"       若確實要換來源,請重跑 confirm-source 重新確認。")


# ── repo URL 來源 ──────────────────────────────────────────────

_CRED_IN_URL_RE = re.compile(r"(https?://)[^/\s@]+@")
_REPO_URL_RE = re.compile(
    r"^(?:https?://|git://|ssh://|git\+ssh://|[A-Za-z0-9_.\-]+@[A-Za-z0-9_.\-]+:)")

CLONE_HELP = """clone 失敗的常見原因與處置:
- private repo 未授權:先設好 git 認證(gh auth login / SSH key / credential helper)再重跑。
  **不要把 token 寫進 URL**——它會留在 shell 歷史與 log 裡。
- 分支或標籤不存在:用 --ref 指定正確的 branch/tag。
- 網路或 proxy 擋住:確認本機可連到該主機。"""


def is_repo_url(value: str) -> bool:
    """判斷 --from-repo 給的是 URL 還是本地路徑。"""
    return bool(_REPO_URL_RE.match((value or "").strip()))


def redact(text: str) -> str:
    """去掉 URL 裡的 userinfo(https://user:token@host/…),避免憑證進 log 與狀態檔。"""
    return _CRED_IN_URL_RE.sub(r"\1", text or "")


def clone_repo(url: str, dest: Path, ref: str | None) -> tuple[Path, str]:
    """淺 clone 到 dest,回傳 (路徑, commit 短碼)。只讀取來源,不會推回去。"""
    if shutil.which("git") is None:
        raise SystemExit("[FAIL] 找不到 git,無法從 URL 取得 repo;請安裝 git 或改用本地路徑。")
    safe = redact(url.strip())
    _clear_dir(dest)
    cmd = ["git", "clone", "--depth", "1"]
    if ref:
        cmd += ["--branch", ref]
    cmd += [url.strip(), str(dest)]
    print(f"[NOTE] clone {safe}{(' @' + ref) if ref else ''} → {dest}")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=600)
    except subprocess.TimeoutExpired:
        raise SystemExit(f"[FAIL] git clone 逾時(600s):{safe}\n\n{CLONE_HELP}")
    if proc.returncode != 0:
        detail = redact((proc.stderr or proc.stdout or "").strip())[-800:]
        raise SystemExit(f"[FAIL] git clone 失敗(returncode {proc.returncode}):\n{detail}\n\n{CLONE_HELP}")
    rev = subprocess.run(["git", "-C", str(dest), "rev-parse", "HEAD"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace")
    commit = rev.stdout.strip()[:12] if rev.returncode == 0 else "?"
    print(f"[NOTE] clone 完成:commit {commit}")
    return dest, commit


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
            slugs |= _egress_slugs(text)
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
    common.bootstrap()
    parser = argparse.ArgumentParser(description="S1 抽取正規化")
    parser.add_argument("--slug", help="工作區 slug(--list-apps 以外必填)")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--from-app", help="線上 custom app 的 id 或 slug")
    source.add_argument("--from-repo", help="repo 本地路徑或 URL")
    source.add_argument("--list-apps", action="store_true",
                        help="列出租戶下的 custom app(查 uuid 用,不進行抽取)")
    parser.add_argument("--ref", help="repo URL 來源的 branch 或 tag")
    parser.add_argument("--vfs-subdir", help="多 app 佈局時指定子目錄")
    parser.add_argument("--mapping", help="自訂佈局對映 JSON 檔路徑")
    args = parser.parse_args()

    if args.list_apps:
        list_apps(common.load_env())
        return
    if not args.slug:
        raise SystemExit("[FAIL] 缺少 --slug")
    if not args.from_app and not args.from_repo:
        raise SystemExit("[FAIL] 需指定 --from-app 或 --from-repo"
                         "(不知道線上 app 的 uuid 就先跑 --list-apps)")
    if args.ref and not (args.from_repo and is_repo_url(args.from_repo)):
        raise SystemExit("[FAIL] --ref 只適用於 repo URL 來源")

    work = common.work_dir(args.slug)
    state = common.require_stage(work, "S1_acquire")

    template = work / "template"
    raw_dir = work / "raw"
    profiles_cfg = common.load_config("layout_profiles.json")
    exclude_dirs = set(profiles_cfg["exclude_dirs"])
    notes: list[str] = []

    # 來源解析先做完(身分閘、clone)再動 template/——身分沒確認就把上一輪成果清掉最傷。
    app_info: dict = {}
    repo: Path | None = None
    origin_desc = ""
    if args.from_app:
        env = common.load_env()
        entry = require_source_decision(work, args.slug)
        app_info = fetch_app_vfs(env, args.from_app)
        verify_source_identity(entry, app_info)
        print(f"[OK] 來源身分已確認:{app_info.get('name')}({app_info.get('slug')})")
    elif is_repo_url(args.from_repo):
        repo, commit = clone_repo(args.from_repo, work / "src_repo", args.ref)
        origin_desc = f"{redact(args.from_repo.strip())}@{commit}"
    else:
        repo = Path(args.from_repo).resolve()
        if not repo.is_dir():
            raise SystemExit(f"[FAIL] repo 路徑不存在:{repo}"
                             f"(要從遠端取得請給完整 URL,例:https://github.com/org/repo.git)")
        origin_desc = str(repo)

    _clear_dir(template)
    raw_dir.mkdir(exist_ok=True)

    if args.from_app:
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
        source_desc = f"app:{app_info.get('slug')}({app_info.get('id')})"
        profile_name = "online"
    else:
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
        source_desc = f"repo:{origin_desc}"

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
    inventory = build_inventory(template, env, str(app_info.get("id")) if args.from_app else None)
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
