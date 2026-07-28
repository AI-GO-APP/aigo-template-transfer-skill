"""測試共用:路徑設定與最小合法 template fixture。"""
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
for p in (REPO_ROOT / "scripts", REPO_ROOT / "vendor"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


MINIMAL_META = {
    "slug": "e2e_fixture",
    "name": "測試模板",
    "description": "單元測試用最小模板",
    "category": "integration",
    "version": "1.0.0",
    "access_mode": "internal",
    "setup_schema": {"API_KEY": {"type": "secret", "label": "API Key"}},
}

PACKAGE_JSON = {
    "name": "e2e-fixture",
    "private": True,
    "dependencies": {
        "react": "^18.0.0",
        "react-dom": "^18.0.0",
        "react-router-dom": "^6.0.0",
        "lucide-react": "^0.300.0",
        "react-hot-toast": "^2.4.0",
    },
}

ACTION_OK = '''def execute(ctx):
    key = ctx.secrets.get("API_KEY")
    ctx.log("ok")
    return ctx.response.json({"success": True})
'''


def make_minimal_template(template: Path, *, meta: dict | None = None) -> Path:
    """建立可通過 S6 全部閘的最小 template。"""
    (template / "src").mkdir(parents=True, exist_ok=True)
    (template / "actions").mkdir(parents=True, exist_ok=True)
    (template / "package.json").write_text(
        json.dumps(PACKAGE_JSON, ensure_ascii=False, indent=2), encoding="utf-8")
    (template / "src" / "main.tsx").write_text(
        'import "./App.css"\nimport App from "./App"\nexport default App\n', encoding="utf-8")
    (template / "src" / "App.tsx").write_text(
        "export default function App() { return null }\n", encoding="utf-8")
    (template / "src" / "App.css").write_text("body {}\n", encoding="utf-8")
    for sdk in ("api.ts", "db.ts", "action.ts"):
        (template / "src" / sdk).write_text("export {}\n", encoding="utf-8")
    (template / "src" / "data.json").write_text("{}\n", encoding="utf-8")
    (template / "src" / "db.json").write_text("{}\n", encoding="utf-8")
    (template / "actions" / "manifest.json").write_text(json.dumps({
        "check_status": {"description": "檢查狀態", "timeout_ms": 15000, "is_enabled": True},
    }), encoding="utf-8")
    (template / "actions" / "check_status.py").write_text(ACTION_OK, encoding="utf-8")
    (template / "_template_meta.json").write_text(
        json.dumps(meta or MINIMAL_META, ensure_ascii=False, indent=2), encoding="utf-8")
    return template
