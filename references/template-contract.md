# Template 契約:目錄佈局與 _template_meta.json

整理自 ai-go-templates(vfs_structure.md + 實例)與 ai-go 後端 template_dsl.py(2026-07-28)。

## 標準目錄佈局(templates/<slug>/ 形)

```
_template_meta.json          必要;唯一被 audit/deploy 硬性檢查的檔
package.json                 必要;private:true,恰好 5 個核心依賴,無 devDependencies
src/main.tsx                 entry(必須 import "./App.css")
src/App.tsx  App.css  routes.ts
src/api.ts  src/db.ts  src/action.ts     [SDK] 三檔,照抄 canonical,勿改
                                         (db.ts 的 remove() 對 204 有既知缺陷:檔照抄,
                                          但 DELETE 繞過它不 import——見「正式站行為」§3)
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

## 正式站行為(沙箱曾經測不到的十件事)

2026-08-17 兩批真前端驗收在 demo 租戶抓到的正式站行為:§1–§6 來自 8 支已上架模板
(asn-tasks/jra-tracker/mnd-board/trl-board/cu-workspace/calendly-scheduling/
calendly-booking/ga4-analytics-hub)的安裝驗收;§7–§10 來自 cv 系列五支
(catalog/badge/ad-creative/social-kit/slide-studio)的安裝→發布→真前端點擊批次。
沙箱端保真度修正見 urfit-tech/aigo-developer-platfom#119(§7/§10 的沙箱側對齊
在 #121,送修中);AI GO 端這些是**現行正式站行為**(缺陷已記錄,修正不在本波範圍),
**模板必須自帶下列防禦**;日後平台修正後,防禦對正確形狀是 no-op
(前提見各則附註),不必移除。

適用面:§1–§4 實測的是 DB Proxy(引用表 `/proxy`)面——其中 §1 另有 action 端
(`ctx.db`)的 Python 變體實證,見 §6 末;§5–§10 是發布/runtime 面,與資料存取
走哪一面無關。自建表面(`/data-center/.../records`、`ctx.db.query_table`)除
§1 變體與 §7 的 `/data-center/tables/{t}/images` 上傳路徑外未實測——
勿逕自泛化,也勿假設安全,正式站先實打一筆再決定。

### 1. insert 回應是巢狀信封,且 `custom_data` 是 JSON「字串」

`POST /proxy/{app}/{table}` 回 `{id, created_at, data:{...}}`;`data.custom_data`
是 `json.dumps` 後的字串(query 路徑回物件,只有 insert 回應不同)。模板讀取層要
兩件事都做:攤平信封 ＋ 解析字串 custom_data:

```ts
const ENVELOPE_KEYS = new Set(["id", "created_at", "updated_at", "tenant_id", "data"]);

function flatRow<T = any>(row: any): T {
  if (!row || typeof row !== "object" || Array.isArray(row)) return row as T;
  const inner = (row as any).data;
  // 信封判定:data 是純物件之外,頂層鍵也必須全落在信封鍵集內,
  // 避免把「恰好有名為 data 的物件欄」的一般列誤判成信封
  const isEnvelope =
    inner && typeof inner === "object" && !Array.isArray(inner) &&
    Object.keys(row).every((k) => ENVELOPE_KEYS.has(k));
  const flat: Record<string, any> = isEnvelope ? { ...inner } : { ...row };
  if (isEnvelope)
    for (const k of ["id", "created_at", "updated_at", "tenant_id"])
      if (row[k] != null) flat[k] = row[k];
  // 只 parse 序列化容器形狀的字串;純量字串("007"、"true")不貪婪轉型
  if (typeof flat.custom_data === "string" && /^\s*[\[{]/.test(flat.custom_data)) {
    try { flat.custom_data = JSON.parse(flat.custom_data); }
    catch { /* 非法 JSON:保留字串,下游 merge 前需自行檢查型別 */ }
  }
  return flat as T;
}
```

flatRow 的三個設計約束(改寫時不可丟):

- **絕不就地改寫傳入列**,一律回傳新物件——改在原物件上會汙染 React state/
  SWR 快取裡的那一份(參照未變不重繪、memo 失效),比原始 bug 更難查。
- 信封判定要求頂層鍵全落在 `{id, created_at, updated_at, tenant_id, data}`,
  一般列才不會被誤判整列吞掉。因此自建表**不要宣告名為 `data` 的欄位**;
  真的有,「除系統欄外只有 data 欄」的列仍會誤判,需自行改判定。
- `custom_data` 只在字串以 `{`/`[` 開頭時才 parse(信封的 `json.dumps` 產物必然
  如此);parse 失敗保留原字串——下游對 custom_data 做 spread/merge 前自行檢查
  `typeof`,對字串 spread 會得到逐字元索引物件。

少了字串解析的實測後果:建立後的本地物件讀不到自己剛寫入的 cfg——trello/monday 風格
模板的「看板 cfg 被下一個 merge-PATCH 整包洗掉」、jira 風格的「議題編號顯示 0」、
clickup 風格的「新清單顯示全租戶狀態列」,全是同一根因。**任何「insert 完立刻用
custom_data」或「merge-patch custom_data」的模板都必須過 flatRow 這類防禦。**

### 2. 寫入 body 必須包 `{data: {...}}`;PATCH 回應只有 `{id, updated}`

flat body 會 400「無有效欄位資料」。PATCH 不回列資料——依賴回傳列的程式要自備
fallback(沿用本地物件),不要讀回應欄位。

### 3. DELETE 回 204 無 body

正規 db.ts 的 `remove()` 對 204 呼叫 `.json()` 會拋例外(刪除其實成功了)。
模板一律在 services/ 層自寫 fetch 發 DELETE,檢查 `resp.ok`(204 也在 ok 範圍;
真正的教訓是 **204/空 body 不要呼叫 `.json()`**),不 import db.ts 的 remove。

### 4. 伺服器端 filter 對 DATE/TIMESTAMP 欄位下字串條件 → asyncpg 500

`{"column":"date_deadline","op":"gte","value":"2026-04-19"}` 在正式站直接
`DataError: 'str' object has no attribute 'toordinal'`——連 `created_at`+完整 ISO
也一樣。錯誤出在 asyncpg 的 date encoder;UUID 欄位未觀察到同類問題
(asyncpg 的 UUID codec 接受字串),等值查詢不必連坐改前端。
**日期/時間欄位的區間條件一律抓回前端收斂**,收斂時把兩端 `Date.parse`
成數值再比——直接比 ISO 字串只在同 offset、同格式、同精度時才等於時間序,
DB 回傳的 `+00:00` 混上前端 `toISOString()` 的 `Z`+毫秒就會在邊界漏列/多列。
不要下伺服器端條件。注意:沙箱(#119 之後)套用 filters 且日期比較可用——
這一項沙箱比正式站寬,沙箱綠不代表正式站可行。

### 5. 發布後 runtime bundle 有快取

republish 後直接開 runtime URL 可能拿到舊 bundle——驗證一律帶 `?cb=<亂數>` 破快取,
否則會把「已修好」誤判成「沒修好」。

### 6. external 匿名存取需要平台行政人員核可(T10)

`PATCH /builder/apps/{id}/settings {allow_anonymous_access:true}` 只是第一層;
未經 `PATCH /builder/apps/{id}/anonymous-approval`(**僅平台行政人員**,tenant admin
403)核可前,ext-runtime 對匿名訪客回「App 不存在或尚未發布」——**比登入牆更糟**。
external 公開頁模板的安裝說明必須寫明這兩步,並在未核可時保持
`allow_anonymous_access=false`(至少讓平台的客戶驗證牆能用)。

驗收面:客戶驗證牆的「註冊」本來就開放訪客——**用合成測試帳號註冊即可全自動走完
整條 external 流程**,不需要等 T10 核可;客戶帳號是 per-app(custom-app-auth/{slug}),
另一支安裝要重新註冊。已在 demo 租戶以 calendly-booking 的
預約→管理→改期→取消全流程實證(2026-08-17;該次同時抓到 §1 的 Python 變體:
action 端 `merge_ns(insert 回應的字串 custom_data)` 把整包預約設定洗掉,
修法同 flatRow——`_shared` helper 一律解析字串 custom_data)。

### 7. runtime CSP 的媒體白名單——外部 CDN 在正式租戶載不到

正式租戶的 app-runtime CSP(2026-08-17 於 demo 租戶以 securitypolicyviolation 實錘):
`img-src 'self' data: blob: https://*.s3.amazonaws.com https://*.s3.ap-east-2.amazonaws.com`,
`connect-src` 同樣只有 self/平台網域/S3(外加 api.openai.com)。意思是:

- **前端 hotlink 外部圖床(如 KIE 的 tempfile.aiquickdraw.com)= 破圖**;
- **前端 fetch 外部 CDN 轉存 = Failed to fetch**——「媒體轉存搬前端」這條路
  目前只在 developer 沙箱成立(沙箱預覽頁 CSP 對齊送修中,#121 合併後也不再成立);
- egress 閘道那頭 `json_or_text()` 對二進位回 None,action 也代抓不了。
  **二進位在正式租戶沒有任何跨界通道。**

生圖的正解範式(cv 系列 1.0.2 實證):action 走 openai egress 的
`POST /v1/responses`(`background:true` + `image_generation` 工具,
`quality:"low"`+`output_format:"jpeg"`+`output_compression:85`),前端沿用
送單+輪詢;成品以 **base64 JSON** 回來(~200KB,低於 egress 5MB 回應上限;
submit/poll 各約 1 秒,不撞 action/egress 的 30 秒硬上限——注意平台把 egress
timeout **封頂在 30000ms**,服務設定寫 60000 也沒用)。前端以 `data:` URL 預覽
(CSP 允許),挑中後 base64→blob→`/data-center/tables/{t}/images` 上傳平台 S3。
`image_generation` 工具不接受 `reasoning.effort:"minimal"`,最低給 `low`。
**影片**沒有等效通道(b64 過不了 5MB 上限)——設計期就不要做「生成影片後轉存」,
只能保留外部暫存連結並引導使用者以新分頁另存(上層導覽不受頁面 CSP 限制)。

### 8. 發布後 per-app runner 冷啟動 503

發布完成不等於 runner 就緒:首批 action 呼叫回 503「app runner 暫時不可用」,
持續 30 秒到數分鐘。此時 action **尚未執行**,重試安全(實測連打不會重複建資料)。
模板的 action 包裝層應內建退避重試(如 5s/10s/15s 三次)再放棄,並把放棄後的
文案寫成「App 服務正在啟動(發布後第一次使用約需一分鐘),請稍候再試」。
驗收流程面:publish 後先用 API 打一發輕量 action 催醒 runner 再開始前端實測。

### 9. `__APP_TOKEN__` 隨平台 JWT 一小時失效

頁面開著超過一小時後,所有 action/寫入變 401,App 自己拿不到新 token。
模板要把 401 一律翻成「登入權杖已逾時,請重新整理頁面後再操作」;
多步驟精靈(生成→展開→建立)要意識到中途 401 會留下半成品——能延後的寫入
盡量集中在最後一步。

### 10. 原生 confirm/alert/prompt——規範禁用,且會凍結 renderer

`window.confirm()` 在正式租戶「功能上」可用(原生對話框會跳),但與 App 內
`.dialog-overlay` 體系視覺完全脫節,而且原生對話框會阻塞 renderer——
自動化(CDP)點到刪除鈕整個分頁凍結 45 秒以上,Enter/Esc 都解不掉。
一律改自繪確認對話框(共用 ConfirmHost + `await confirmDialog(msg)` 範式,
掛在 ThemeProvider 的 .app-root 內)。devportal preflight 的 warn 級掃描
在平台側送修中(urfit-tech/aigo-developer-platfom#121)——合併上線前以自查為準。
