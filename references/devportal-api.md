# AI GO Developer 平台 API 摘要(本 skill 用到的子集)

Base:`https://developer.ai-go.app/api/v1`。權威清單:`GET /dev-docs/endpoints`(即時導出,含 min_level)。
本檔整理自 ai-go-developer 實碼(2026-07-28);漂移時以自省端點為準。

## 認證

- `Authorization: Bearer <token>`;PAT(`aigodev_` 開頭)與 session JWT 同一 header,所有端點通用。
- PAT 無 scope,繼承發行者 level:`read_only`(唯讀)/ `editor`(開發、送審)/ `admin`(審核發布)。
- 發行:portal `/settings` →「API Token(PAT)」;或 `POST /auth/login {email,password}` 取 JWT 後
  `POST /tokens {label, expires_in_days}`(token 只回一次)。
- 新註冊帳號預設 `read_only`,建模組需 admin 以 `PUT /accounts/{user_id}/level` 升級為 editor。

## 模組與版本

| Method / Path | 說明 |
|---|---|
| `POST /modules` | body `{slug, name, category, access_mode}` → 201 `{id, slug}`;**自動建 1.0.0 draft** |
| `GET /modules?mine=true` | 我的模組 |
| `GET /modules/{mid}` | 詳情含 `versions[]`(id/version/state/metadata) |
| `PUT /modules/{mid}/versions/{vid}/metadata` | `{metadata: {...}}` 整包覆寫 |
| `PUT /modules/{mid}/versions/{vid}/files` | `{files:[{file_path,content,is_binary}]}` **全量取代**,自動記 deploy 事件 |
| `GET /modules/{mid}/versions/{vid}/preflight` | 靜態預檢(entry/imports/secrets/scopes/actions/manifest/references) |
| `GET/POST /modules/{mid}/versions/{vid}/events` | 查/記事件;POST 只收 `{kind:"test", detail:{}}` |
| `GET /modules/{mid}/versions/{vid}/files/content` | 取回版本全部檔案內容(`devportal.py pull`) |
| `POST /modules/{mid}/versions/{vid}/submit` | `{note}` → `{request_id, status}` |
| `POST /modules/{mid}/versions/{vid}/withdraw` | 撤回送審(`devportal.py withdraw`) |
| `POST /modules/{mid}/versions` | `{kind: major\|minor\|patch, copy_files}` 開新版本(`devportal.py bump`) |

注意:
- 建模組後**不要** `POST /versions`——存在進行中版本線(draft/rejected/submitted)會 409。
  已發布(approved)的模組要出下一版才用它,這也是唯一的路。
- 版本狀態機:draft → submitted → approved/rejected;approved 後舊版 superseded。
- **送審門檻(2026-07-28 更新)**:preflight ok + ≥1 筆 deploy 事件 + 最後 deploy 之後:
  (a) 一筆**無 detail.action** 的 test 事件(預覽測試,可手動 POST);
  (b) **每支 enabled action**(排除 `actions/_shared/`、扣 manifest `is_enabled:false`)
  至少一筆 `detail.status=="success"` 的 test 事件——由沙箱執行端點**伺服器自動記錄**,
  手動 POST 宣稱無效。跑不通的 action 只能補憑證跑通或停用。
- `actions/_shared/**.py` 是共用模組(issue #497):不要求 `execute(ctx)`,
  沙箱執行時自動隨行注入 runner;不可當 action 呼叫。
- 限制:MAX_FILES=500、50MB;路徑不得含 `\` 或 `..`;slug `^[a-z0-9][a-z0-9_-]*$`(底線正規化為 `-`)。
- **部署節奏**:CI 改由 release tag 觸發部署 prod——developer.ai-go.app 可能落後 main;
  skill 應容忍新舊兩種送審門檻行為。

## metadata 欄位

`name, description, long_description, icon_emoji, category, tags, access_mode,
vfs_factory_key, setup_schema, required_egress, data_center_schema,
data_references_schema, author, version`

- `custom_objects_schema` 非空會被 422 明確擋下(舊制退場)。
- `data_center_schema`:可存,且**存檔即驗**(`ctx_core.template_dsl`,與 AI GO
  upsert 同一套含成環偵測;不合法 PUT metadata 直接 422)。
- `required_egress`:`{slug: {label?, description?}}`——模板用到 `ctx.http.call(slug)`
  時必須宣告,租戶安裝時據此提示授權外部服務;preflight 會對比程式碼掃描結果(warn)。
- `category` 白名單 9 值;`tags` 必須取自 `GET /refs/tags`。
- `setup_schema`:`{KEY: {type: text|secret|select, label, required?, options?}}`。

## 沙箱(全部 `/sandbox/v/{version_id}` 前綴)

### ★ 資料面有兩組,不可互串(踩過的坑)

平台有兩組長得像、語意完全不同的資料端點。**餵錯表名 100% 404**:

| metadata 宣告 | 語意 | 沙箱端點 | 前端 SDK |
|---|---|---|---|
| `data_center_schema.tables[]` | 模板**自建**表 | `/data-center/tables/{key}/records` | data_table |
| `data_references_schema[]` | 引用 **AI GO 既有**表 | `/proxy/{app_id}/{table}` | proxy |

`/proxy` 與 `/tables/{t}/seed\|rows` 這一面在平台端有 `assert_table` 硬驗 AI GO 快照
(`ctx_core/sandbox.py`),自建表名打過去回 404「AI GO 無此表」;反之引用表打
`/data-center/tables` 則是進到「未宣告的表 = 空頁」的自建表語意,測不到真東西。
腳本一律經 `scripts/devportal_paths.py` 組路徑,不要手拼。

**自建表那一面的路徑換過**:舊的 `/data/objects/{slug}/records`(update/delete 走
`/data/records/{id}`、以 record id 全域反查)**已隨 AI GO 退場**,平台端不再提供,
見 ai-go-developer `backend/app/api/sandbox.py` 的 `_data_center_router` 檔頭。
現行面以 **(表, id)** 定位,update/delete **要帶表名**——不只是路徑字串換掉,是簽章層的差異。

| Method / Path | 說明 |
|---|---|
| `GET/POST /sandbox/v/{vid}/data-center/tables/{key}/records` | **自建表** CRUD;`ext/data-center/...` 為 external 變體 |
| `PATCH/DELETE /sandbox/v/{vid}/data-center/tables/{key}/records/{row_id}` | 同上;路徑**帶表名** |
| `GET /sandbox/v/{vid}/data-center/tables` | 列出自建表結構;宣告了但還沒資料的表也會列 |
| `GET/POST /sandbox/v/{vid}/proxy/{app_id}/{table}` | **引用表** CRUD(internal);沙箱以 vid 充當 app_id |
| `GET/POST /sandbox/v/{vid}/ext/proxy/{table}` | 引用表 CRUD(external,不帶 app_id) |
| `POST /sandbox/v/{vid}[/ext]/proxy/{table}/query` | 引用表查詢 |
| `PATCH/DELETE /sandbox/v/{vid}[/ext]/proxy/{table}/{row_id}` | 引用表單列更新/刪除 |
| `GET /sandbox/v/{vid}/tables` | 各表筆數 |
| `POST /sandbox/v/{vid}/tables/{table}/seed?count=N` | 灌假資料(**僅引用表**,會驗快照) |
| `GET /sandbox/v/{vid}/tables/{table}/rows` | 讀沙箱資料(僅引用表) |
| `GET/PUT /sandbox/v/{vid}/secrets` | 沙箱金鑰 |
| `GET/PUT/DELETE /sandbox/v/{vid}/egress[/{slug}]` | 沙箱 egress;PUT body 支援 `allow_dynamic_host`(wildcard,`ctx.http.fetch` 用) |
| `GET /sandbox/v/{vid}/custom-app-auth/{slug}/me`、`POST .../logout` | external 模板的沙箱登入態 |
| `POST /sandbox/v/{vid}/actions/apps/{app_id}/run/{name}` | 跑 action(internal);runner 未配置回 503;`is_enabled:false` 回 409;**執行結果由伺服器記成 test 事件(detail.action/status)** |
| `POST /sandbox/v/{vid}/ext/actions/run/{name}` | 跑 action(external);同上自動記錄 |

沙箱**寫入**與 test 事件回報需 `editor`(read_only 只能看)。新版 data_table SDK
(自建表)沙箱已支援;沙箱與 AI GO prod 的已知行為差距已於 2026-07-28 收斂(PR #30)。

前端 preview:`https://developer.ai-go.app/preview/{module_id}?v={version_id}`
(esbuild-wasm 瀏覽器端編譯,3 秒無錯自動 POST test 事件)。

## 參考資料端點

`GET /refs/tags`、`GET /refs/available-tables`、`GET /refs/tables/{t}/columns`、`GET /auth/me`

`available-tables` 回 `[{name, comment}]`,`columns` 回
`[{name, type, nullable, is_system}]`。`push` 會拿這兩支前置驗證
`data_references_schema`(表不存在直接擋下,不必等推完檔才被 preflight fail);
e2e 也用 `columns` 產引用表的樣本列。

> **`available-tables` 與 `columns` 不是每個部署都有**(2026-08-01 實測
> developer.ai-go.app:`GET /dev-docs/endpoints` 底下 `/refs/*` 只有
> `seed-tables` 與 `tags`)。**打之前先看 `/dev-docs/endpoints` 這份權威清單**,
> 別假設它們一定在。兩支都 404 時:push 印 WARN 但不擋(宣告正確性未驗),
> e2e 改走 `POST /sandbox/v/{vid}/tables/{t}/seed` 讓平台自己產樣本列。
>
> `/refs/seed-tables` **不能**拿來當可引用表的白名單——實測 `sale_order_lines`、
> `delivery_carriers`、`product_templates`、`product_products`、`stock_pickings`
> 都不在該清單的 30 張裡,但 proxy 與 seed 都正常。拿它擋會製造假失敗。

## 架上模板(`/live-templates`)

- `GET /live-templates` → **`{templates: [...], source}`**(不是裸陣列)。每支帶
  `slug/name/category/is_managed/state/can_adopt/module{...}`;可否接管看 `can_adopt`,
  不要自行從 `module` 推論。S0 候選判定比對重疊用(`devportal.py live-templates`)。
- `POST /live-templates/{slug}/adopt`(admin)→ 把未受管的架上模板納入平台管理:
  取回架上內容建成基準版本,並在 AI GO 端鎖住其他發布路徑。
  **不可逆、一支只能接管一次**;AI GO 那側失敗回 502(本地未寫入,可安全重試)。
  `devportal.py adopt` 帶人工確認閘。

## 來源側(AI GO 本體,`https://ai-go.app/api/v1`)

- `POST /auth/login {email,password}` → JWT(需 builder.access)
- `GET /builder/apps/{app_id_or_slug}` → 含 `vfs_state`(全量 {path: content})、`vfs_version`、`access_mode`
- `GET /data-center/tables`、`GET /data-center/tables/{key}` → 租戶自建表(key = 實體表名)
