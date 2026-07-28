"""data_center_schema DSL 的本地驗證器。

鏡射自 ai-go/backend/app/services/data_center/template_dsl.py 的
parse_data_center_schema + order_tables 語義(2026-07-28),零相依、可離線跑。
權威仍是 ai-go 後端;dc_extract/audit 支援以 --ai-go-backend 指向該 repo 做真驗證,
本檔是找不到後端時的降級與單元測試用替身。語義如有漂移,以後端為準並回改本檔。

規則來源(逐條對應後端):
- version 必須 == 1
- tables 非空陣列,表 key 全域唯一
- 表/欄 key:^[a-z_][a-z0-9_]{0,62}$(identifiers._IDENT_RE, MAX_IDENT_LEN=63)
- 欄 key 不得 ∈ {id, created_at, updated_at}(ddl_executor.SYSTEM_FIELD_NAMES)
- type ∈ text|number|boolean|date|datetime|select|image|json|relation(field_types registry)
- select 必須有非空 options;非 select 可有 options(後端允許 None 以外值僅驗字串陣列)
- relation 必須 target_table / target_erp_key 恰一;非 relation 兩者皆不可設
- relation target_table 必須指向本模板宣告的表
- seed 列的鍵必須是已宣告欄位
- section_path 為字串陣列
- relation 相依需可拓樸排序(自我參照不算相依;真環報錯)
"""
import re
from typing import Any

DSL_VERSION = 1
IDENT_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
SYSTEM_FIELD_NAMES = frozenset({"id", "created_at", "updated_at"})
FIELD_TYPES = frozenset({
    "text", "number", "boolean", "date", "datetime", "select", "image", "json", "relation",
})


def validate_data_center_schema(raw: Any) -> list[str]:
    """回傳錯誤訊息列表;空列表 = 通過。訊息格式貼近後端 TemplateSchemaError。"""
    if raw in (None, {}, []):
        return []
    errors: list[str] = []
    if not isinstance(raw, dict):
        return [f"data_center_schema 必須是物件,實際為 {type(raw).__name__}"]

    version = raw.get("version", DSL_VERSION)
    if version != DSL_VERSION:
        return [f"data_center_schema.version 不支援:{version!r}(本版僅支援 {DSL_VERSION})"]

    tables = raw.get("tables")
    if tables is None:
        return ["data_center_schema 缺少必要欄位 'tables'"]
    if not isinstance(tables, list):
        return ["data_center_schema.tables 必須是陣列"]

    table_keys: set[str] = set()
    deps: dict[str, set[str]] = {}

    for i, table in enumerate(tables):
        where = f"tables[{i}]"
        if not isinstance(table, dict):
            errors.append(f"{where} 必須是物件")
            continue

        key = table.get("key")
        if not isinstance(key, str) or not key.strip():
            errors.append(f"{where}.key 必須是非空字串")
            key = None
        elif not IDENT_RE.match(key):
            errors.append(f"{where}.key 非合法實體表名:{key!r}(限小寫字母/底線開頭的 ASCII 識別字)")
        elif key in table_keys:
            errors.append(f"data_center_schema 表 key 重複:{key!r}")
        else:
            table_keys.add(key)

        dn = table.get("display_name")
        if not isinstance(dn, str) or not dn.strip():
            errors.append(f"{where}.display_name 必須是非空字串")

        sp = table.get("section_path")
        if sp is not None and (not isinstance(sp, list) or not all(isinstance(s, str) for s in sp)):
            errors.append(f"{where}.section_path 必須是字串陣列")

        fields = table.get("fields")
        if not isinstance(fields, list) or not fields:
            errors.append(f"{where}.fields 必須是非空陣列")
            continue

        field_keys: set[str] = set()
        table_deps: set[str] = set()
        for j, field in enumerate(fields):
            fwhere = f"{where}.fields[{j}]"
            if not isinstance(field, dict):
                errors.append(f"{fwhere} 必須是物件")
                continue

            fkey = field.get("key")
            if not isinstance(fkey, str) or not fkey.strip():
                errors.append(f"{fwhere}.key 必須是非空字串")
                fkey = None
            else:
                if not IDENT_RE.match(fkey):
                    errors.append(f"{fwhere}.key 非合法實體欄名:{fkey!r}(限小寫字母/底線開頭的 ASCII 識別字)")
                if fkey in SYSTEM_FIELD_NAMES:
                    errors.append(f"{fwhere}.key 不可用系統欄名:{fkey!r}")
                if fkey in field_keys:
                    errors.append(f"{where} 欄位 key 重複:{fkey!r}")
                field_keys.add(fkey)

            if not isinstance(field.get("display_name"), str) or not str(field.get("display_name")).strip():
                errors.append(f"{fwhere}.display_name 必須是非空字串")

            ftype = field.get("type")
            if not isinstance(ftype, str) or not ftype.strip():
                errors.append(f"{fwhere}.type 必須是非空字串")
                continue
            if ftype not in FIELD_TYPES:
                errors.append(f"{fwhere}.type 不支援:{ftype!r}(合法:{sorted(FIELD_TYPES)})")
                continue

            target_table = field.get("target_table")
            target_erp_key = field.get("target_erp_key")
            if ftype == "relation":
                if bool(target_table) == bool(target_erp_key):
                    errors.append(f"{fwhere} 為 relation 型別,須指定 target_table 或 target_erp_key 兩者恰一")
                elif target_table:
                    if key and target_table != key:
                        table_deps.add(target_table)
            elif target_table or target_erp_key:
                errors.append(f"{fwhere} 非 relation 型別,不可設定 target_table/target_erp_key")

            options = field.get("options")
            if options is not None and (
                not isinstance(options, list) or not all(isinstance(o, str) for o in options)
            ):
                errors.append(f"{fwhere}.options 必須是字串陣列")
                options = None
            if ftype == "select" and not options:
                errors.append(f"{fwhere} 為 select 型別,options 不可為空")

        seed = table.get("seed") or []
        if not isinstance(seed, list):
            errors.append(f"{where}.seed 必須是陣列")
        else:
            for k, row in enumerate(seed):
                if not isinstance(row, dict):
                    errors.append(f"{where}.seed[{k}] 必須是物件")
                    continue
                unknown = set(row) - field_keys
                if unknown:
                    errors.append(f"{where}.seed[{k}] 含未宣告欄位:{sorted(unknown)}")

        if key:
            deps[key] = table_deps

    # relation target 必須指向本模板宣告的表
    for tkey, tdeps in deps.items():
        for dep in tdeps:
            if dep not in table_keys:
                errors.append(f"tables[{tkey}] 的 relation target_table 指向未宣告的表:{dep!r}")

    # 拓樸排序:真環報錯(自我參照已在收集 deps 時排除)
    if not errors and deps:
        done: set[str] = set()
        remaining = [k for k in deps]
        while remaining:
            ready = [k for k in remaining if deps[k] <= done]
            if not ready:
                errors.append(f"data_center_schema 表間關聯成環,無法決定建表順序:{sorted(remaining)}")
                break
            done.update(ready)
            remaining = [k for k in remaining if k not in done]

    return errors


def validate_with_backend(raw: Any, backend_path: str) -> list[str] | None:
    """以權威 parser 驗證。backend_path 可指向:
    - ai-go-developer repo(用 packages/ctx-core 的 ctx_core.template_dsl,零相依,**首選**
      ——PUT metadata 存檔即驗跑的就是這一套)
    - ai-go repo(app.services.data_center.template_dsl,需該 repo 相依套件如 sqlalchemy)
    成功回傳錯誤列表(空=通過);import 不到時回傳 None(呼叫端降級本地驗證並警告)。"""
    import sys
    from pathlib import Path

    backend = Path(backend_path)

    # 首選:ai-go-developer 的 ctx-core(零相依)
    for cand in (backend / "packages" / "ctx-core", backend):
        if (cand / "ctx_core" / "template_dsl.py").exists():
            sys.path.insert(0, str(cand))
            try:
                from ctx_core.template_dsl import (  # type: ignore
                    TemplateSchemaError, order_tables, parse_data_center_schema)
                try:
                    order_tables(parse_data_center_schema(raw))
                    return []
                except TemplateSchemaError as e:
                    return [str(e)]
            except ImportError:
                return None
            finally:
                sys.path.remove(str(cand))

    # 次選:ai-go 後端(需其相依套件)
    for cand in (backend, backend / "backend"):
        if (cand / "app" / "services" / "data_center" / "template_dsl.py").exists():
            sys.path.insert(0, str(cand))
            try:
                from app.services.data_center.template_dsl import (  # type: ignore
                    TemplateSchemaError, order_tables, parse_data_center_schema)
                try:
                    order_tables(parse_data_center_schema(raw))
                    return []
                except TemplateSchemaError as e:
                    return [str(e)]
            except ImportError:
                return None
            finally:
                sys.path.remove(str(cand))
    return None
