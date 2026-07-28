"""template-audit 四類閘的純函式版。

Vendored 自 ai-go-templates/.agent/skills/template-audit/scripts/audit_cli.py(2026-07-28),
僅保留吃 Path 參數的四支審計函式與 run_audit,去除硬編碼路徑與 CLI。
規則語義與上游一致;上游規則變更時應同步本檔。
"""
import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Any


def audit_forbidden_strings(template_dir: Path, rule: dict) -> list[str]:
    """掃描 .py .tsx .ts .json .css 檔案,確認不含 rule['patterns'] 中列出的禁止字串。"""
    if not rule.get("enabled", False):
        return []

    target_extensions = {".py", ".tsx", ".ts", ".json", ".css"}
    patterns: list[str] = rule.get("patterns", [])
    exclude_files: list[str] = rule.get("exclude_files", [])
    failures: list[str] = []

    if not patterns:
        return []

    for root, _dirs, files in os.walk(template_dir):
        for filename in files:
            if filename in exclude_files:
                continue
            filepath = Path(root) / filename
            if filepath.suffix not in target_extensions:
                continue
            try:
                content_lines = filepath.read_text(encoding="utf-8").splitlines()
            except (UnicodeDecodeError, OSError):
                continue
            for line_no, line in enumerate(content_lines, start=1):
                for pat in patterns:
                    if pat in line:
                        rel = filepath.relative_to(template_dir)
                        failures.append(f"第 {line_no} 行 ({rel}): 包含禁止字串 '{pat}'")
    return failures


_EMOJI_PATTERN = re.compile(
    "["
    "\U0001F600-\U0001F64F"
    "\U0001F300-\U0001F5FF"
    "\U0001F680-\U0001F6FF"
    "\U0001F1E0-\U0001F1FF"
    "\U00002702-\U000027B0"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FA6F"
    "\U0001FA70-\U0001FAFF"
    "\U00002600-\U000026FF"
    "\U0000FE00-\U0000FE0F"
    "\U0000200D"
    "\U00002B50"
    "\U0000203C-\U0000203C"
    "\U00002049-\U00002049"
    "\U000024C2-\U000024C2"
    "\U000025AA-\U000025AB"
    "\U000025B6-\U000025B6"
    "\U000025C0-\U000025C0"
    "\U000025FB-\U000025FE"
    "\U00002934-\U00002935"
    "\U00003030"
    "\U0000303D"
    "\U00003297"
    "\U00003299"
    "]+",
    flags=re.UNICODE,
)


def _is_allowed_symbol(char: str, allowed_keywords: list[str]) -> bool:
    try:
        name = unicodedata.name(char, "")
    except ValueError:
        return False
    return any(keyword.upper() in name.upper() for keyword in allowed_keywords)


def audit_emoji(template_dir: Path, rule: dict) -> list[str]:
    """檢查 .tsx 檔案中是否有 Emoji 符號殘留。"""
    if not rule.get("enabled", False):
        return []

    target_extensions = set(rule.get("target_extensions", [".tsx"]))
    allowed_keywords: list[str] = rule.get("allowed_symbols", [])
    failures: list[str] = []

    for root, _dirs, files in os.walk(template_dir):
        for filename in files:
            filepath = Path(root) / filename
            if filepath.suffix not in target_extensions:
                continue
            try:
                content_lines = filepath.read_text(encoding="utf-8").splitlines()
            except (UnicodeDecodeError, OSError):
                continue
            for line_no, line in enumerate(content_lines, start=1):
                for match in _EMOJI_PATTERN.findall(line):
                    for char in match:
                        if not _is_allowed_symbol(char, allowed_keywords):
                            rel = filepath.relative_to(template_dir)
                            char_name = unicodedata.name(char, f"U+{ord(char):04X}")
                            failures.append(
                                f"第 {line_no} 行 ({rel}): 發現 Emoji '{char}' ({char_name})"
                            )
    return failures


_HARDCODED_KEY_PATTERN = re.compile(
    r"""(?:api_key|apikey|secret|token|password)\s*=\s*['"][A-Za-z0-9_\-]{8,}['"]""",
    re.IGNORECASE,
)


def audit_action_structure(template_dir: Path, rule: dict) -> list[str]:
    """檢查 actions/ 下 .py 檔:execute(ctx)、硬編碼金鑰、禁止 import、sync_ 慣例。"""
    if not rule.get("enabled", False):
        return []

    actions_dir = template_dir / "actions"
    if not actions_dir.is_dir():
        return []

    require_execute_ctx: bool = rule.get("require_execute_ctx", True)
    require_ctx_secrets: bool = rule.get("require_ctx_secrets", True)
    forbid_hardcoded: bool = rule.get("forbid_hardcoded_keys", True)
    forbid_imports: list[str] = rule.get("forbid_connector_imports", [])
    failures: list[str] = []

    for py_file in sorted(actions_dir.rglob("*.py")):
        rel = py_file.relative_to(template_dir)
        try:
            content = py_file.read_text(encoding="utf-8")
            lines = content.splitlines()
        except (UnicodeDecodeError, OSError):
            failures.append(f"({rel}): 無法讀取檔案")
            continue

        if require_execute_ctx:
            has_execute = any(re.search(r"def\s+execute\s*\(\s*ctx\b", line) for line in lines)
            if not has_execute:
                failures.append(f"({rel}): 缺少 def execute(ctx) 定義")

        if require_ctx_secrets:
            if "ctx.secrets.get" not in content and any("def execute" in line for line in lines):
                failures.append(f"({rel}): 未使用 ctx.secrets.get 管理金鑰")

        if forbid_hardcoded:
            for line_no, line in enumerate(lines, start=1):
                if _HARDCODED_KEY_PATTERN.search(line):
                    failures.append(f"第 {line_no} 行 ({rel}): 疑似硬編碼金鑰")

        for line_no, line in enumerate(lines, start=1):
            for mod in forbid_imports:
                if re.search(rf"\b(?:import\s+{mod}|from\s+{mod}\b)", line):
                    failures.append(f"第 {line_no} 行 ({rel}): 禁止 import '{mod}'")

        if py_file.stem.startswith("sync_"):
            if not re.search(r"ctx\.db\.(insert|update)", content):
                failures.append(f"({rel}): sync_ 檔案應使用 ctx.db.insert 或 ctx.db.update")
    return failures


def audit_meta_integrity(template_dir: Path, rule: dict) -> list[str]:
    """檢查 _template_meta.json 存在且包含所有必要欄位。"""
    if not rule.get("enabled", False):
        return []

    required_fields: list[str] = rule.get("required_meta_fields", [])
    failures: list[str] = []

    meta_file = template_dir / "_template_meta.json"
    if not meta_file.exists():
        return ["缺少 _template_meta.json 檔案"]
    try:
        with open(meta_file, "r", encoding="utf-8") as f:
            meta = json.load(f)
    except json.JSONDecodeError as e:
        return [f"_template_meta.json 格式錯誤:{e}"]

    for field in required_fields:
        if field not in meta:
            failures.append(f"_template_meta.json 缺少必要欄位:'{field}'")
        elif not meta[field]:
            failures.append(f"_template_meta.json 欄位 '{field}' 為空值")
    return failures


def run_audit(template_dir: Path, rules: dict[str, Any]) -> dict[str, list[str]]:
    """對單一模板目錄執行 vendored 四類審計。回傳 {審計名稱: [失敗訊息]}。"""
    return {
        "禁止字串掃描": audit_forbidden_strings(template_dir, rules.get("forbidden_strings", {})),
        "Emoji 限制": audit_emoji(template_dir, rules.get("emoji_check", {})),
        "Action 結構": audit_action_structure(template_dir, rules.get("action_structure", {})),
        "Meta 完整性": audit_meta_integrity(template_dir, rules.get("meta_integrity", {})),
    }
