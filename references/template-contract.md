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
  租戶安裝時據此提示註冊同名 EgressService。**宣告的是「要連哪個服務」,不是憑證**
  ——ADR 0010 domain-only 之後 EgressService 上只有 base_url 與政策,第三方金鑰歸
  `setup_schema`、由 action 自組 `Authorization` header(SKILL.md 鐵律 6)。

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

## 自建表:實體名與唯一鍵

### 欄位的 key 也是實體名——執行期反查一律刪掉

上面「表名對照 helper 必須刪除」這條**同樣適用於欄位**,而欄位這一半更常被漏掉。
安裝時 AI GO 直接拿宣告的 key 當實體名(權威:`ai-go/backend/app/services/
data_center/template_install.py`,表 `physical_name=table.key`、欄 `physical_name=f.key`),
換租戶也不變,所以靜態就知道,不需要查:

```ts
// ✗ custom_objects 時代的遺留:那時 slug/欄位鍵是租戶級生成的,才需要執行期解析
const tables = await api.get("/data-center/tables");
const t = tables.find(x => x.display_name === "報單");
const fields = {};
for (const f of t.fields) fields[f.display_name] = f.physical_name || f.display_name;
await api.post(`/data-center/tables/${t.physical_name}/records`,
               {data: {[fields["報單號"]]: no}});

// ✓ 新制:宣告什麼就是什麼
await api.post("/data-center/tables/tbl/records", {data: {col: no}});
```

反查寫法除了多餘,還把自己綁在 `list_tables` 的回應形狀上——而那個形狀**兩面不同名**。

### 真的要讀 list_tables:兩面的實體名鍵不同

| 面 | 實體名鍵 |
|---|---|
| `GET /data-center/tables`(前端 api.ts) | `physical_name`(**沒有** `key`) |
| `ctx.db.list_tables()`(action) | `key`(**沒有** `physical_name`) |

這是 AI GO 兩個各自穩定的契約,不是筆誤(`schemas/data_center.py` 的 `TableOut`/`FieldOut`
對 `core/action_context.py` 的 `_dc_table_to_dict`)。`f.physical_name || f.display_name`
在 action 裡永遠退回顯示名;`f.key` 在前端永遠 undefined。兩邊都要跑的共用碼自己收斂一次:
`const phys = f.physical_name ?? f.key`。

失敗長相是「寫入被擋成未宣告的欄位」,而訊息會指向完全正確的 schema 宣告——照上面
「直接用宣告的 key」寫就完全不會遇到。

### unique 是真的 SQL UNIQUE

宣告 `"unique": true` 的欄位,AI GO 建表時下的是欄位級 `CONSTRAINT ... UNIQUE`
(`data_center/ddl_executor.py`),不是應用層檢查,也不是 partial index:

- NULL 不相等——沒帶到的欄位不佔用唯一性
- **空字串 `''` 是一般值**,兩列 `''` 照樣違反
- 違反回 **409** `{"error": "unique_violation"}`(422 是輸入不合法類,兩者不同碼,不要混用)

「需要唯一鍵」正是選擇開自建表、而不是塞 `custom_data` 的理由;這條路徑要在沙箱驗得到,
需要平台端 urfit-tech/aigo-developer-platfom#75(此前重複值在沙箱寫得進去、測試全綠,
上架後才被正式環境的約束擋下)。

## 引用 AI GO 既有表:值型別以正式環境為準

`data_references_schema` 引用的是 AI GO 的正式表,欄位型別**不可從沙箱種子資料反推**——
沙箱 fixture 是平台維護的近似值,與正式環境有過不一致的前例:

| 欄位 | 正式環境 | 曾經的沙箱 fixture |
|---|---|---|
| `hr_leave_types.requires_allocation` | `"yes"` / `"no"`(VARCHAR) | `true` / `false`(bool) |

兩個方向都很安靜(不拋錯,只是分支永遠不進去):照正式環境寫 `=== "yes"` 在沙箱恆 false、
該分支測不到;照沙箱寫 `=== true` 則上線後恆 false。

要確認型別就打正式環境實際讀一筆(`GET /proxy/{app_id}/{table}`),或查 AI GO 的模型層
(`ai-go/backend/app/models/`)——後者在該租戶剛好無資料時仍然有答案。
上表那一筆的 fixture 已修正(urfit-tech/aigo-developer-platfom#73)。
