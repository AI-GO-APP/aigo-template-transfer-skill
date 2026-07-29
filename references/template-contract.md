# Template 契約:目錄佈局與 _template_meta.json

整理自 ai-go-templates(vfs_structure.md + 實例)與 ai-go 後端 template_dsl.py(2026-07-28)。

## 標準目錄佈局(templates/<slug>/ 形)

```
_template_meta.json          必要;唯一被 audit/deploy 硬性檢查的檔
package.json                 必要;private:true,恰好 5 個核心依賴,無 devDependencies
src/main.tsx                 entry(必須 import "./App.css")
src/App.tsx  App.css  routes.ts
src/api.ts  src/db.ts  src/action.ts     [SDK] 三檔,照抄 canonical,勿改
src/data.json                [INJ] 一律空殼 {}
src/db.json                  [INJ] 一律空殼 {}(actions.json 不落地)
src/components/  src/pages/(_manifest.json)
actions/manifest.json        扁平 {action_name: {description, timeout_ms, is_enabled}}
actions/<name>.py            檔名 = action 名;唯一入口 def execute(ctx)
actions/_shared/**.py        共用模組(選用):被 action import,不要求 execute(ctx),
                             不可當 action 呼叫;沙箱/runner 自動隨行注入
actions/seed_demo_data.py    業務型模板慣例(冪等、繁中在地化、timeout_ms 30000)
```

核心依賴(= bare import 白名單):`react, react-dom, react-router-dom, lucide-react, react-hot-toast`。
VFS 上限(AI GO 側):200 檔、單檔 1MB。

## _template_meta.json

必填(audit 硬閘):`slug, name, description, category, version`
選填:`long_description, icon_emoji, access_mode, tags, setup_schema,
required_egress, data_center_schema, data_references_schema, author`

- `required_egress`:`{slug: {label?, description?}}`——模板使用 `ctx.http.call(slug)`
  (對外呼叫的唯一正解)時必須宣告(normalize_meta 會自動從盤點補上),
  租戶安裝時據此提示註冊同名 EgressService(base_url + 憑證由租戶填,閘道注入)。

- category ∈ starter|messaging|crm|catering|integration|ai|operations|productivity|analytics
- access_mode ∈ internal|external|self_built
- **不得含 custom_objects_schema(舊制退場;本 skill 一律新制)**

## data_center_schema DSL(version=1)

```json
{
  "version": 1,
  "tables": [
    {
      "key": "csd_tickets",
      "display_name": "客服工單",
      "section_path": ["客服"],
      "fields": [
        {"key": "ticket_no", "display_name": "工單號", "type": "text",
         "required": true, "unique": true},
        {"key": "status", "display_name": "狀態", "type": "select",
         "options": ["open", "closed"]},
        {"key": "assignee", "display_name": "負責人", "type": "relation",
         "target_table": "csd_agents"}
      ],
      "seed": [{"ticket_no": "T-001", "status": "open"}]
    }
  ]
}
```

規則(權威:ai-go/backend/app/services/data_center/template_dsl.py):

- 表/欄 key:`^[a-z_][a-z0-9_]{0,62}$`;表 key 即實體表名(6 碼後綴機制已退場)
- 欄 key 不得用系統欄名:`id, created_at, updated_at`
- type ∈ `text|number|boolean|date|datetime|select|image|json|relation`
- select 必須有非空 options;relation 必須 target_table/target_erp_key 恰一,
  target_table 只能指向本模板宣告的表;relation 相依不可成環(自我參照除外)
- seed 的鍵必須是已宣告欄位;seed 只灌新建表(重用既有表時跳過)
- 安裝相容判定:模板需求欄位 ⊆ 租戶既有同名表欄位且型別一致 → 重用;否則衝突報告

## 新舊制 API 對照(改寫 action 用)

| 舊制(禁止) | 新制 |
|---|---|
| `ctx.db.query_object(slug, ...)` | `ctx.db.query_table(table, {"filters": [...], "sort": "-created_at", "page": 1, "page_size": ≤200})` |
| `ctx.db.insert_object` | `ctx.db.insert_row(table, data)` |
| `ctx.db.update_object` | `ctx.db.update_row(table, row_id, data)` |
| `ctx.db.remove_object` | `ctx.db.delete_row(table, row_id)` |
| `ctx.db.list_custom_objects` | `ctx.db.list_tables()` |

陷阱:舊 query_object 預設 `created_at DESC`;新 query_table 未帶 sort 是**升冪**,
改寫時必須顯式 `"sort": "-created_at"`。舊 SDK 回 `{"data": {...}}` 包層,新制回平面 dict。
`_t(ctx, name)` 表名對照 helper 在新制下必須刪除(table key 即實體表名)。
