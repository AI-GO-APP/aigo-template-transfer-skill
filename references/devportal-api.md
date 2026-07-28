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
| `POST /modules/{mid}/versions/{vid}/submit` | `{note}` → `{request_id, status}` |
| `POST /modules/{mid}/versions/{vid}/withdraw` | 撤回送審 |

注意:
- 建模組後**不要** `POST /versions`——存在進行中版本線(draft/rejected/submitted)會 409。
- 版本狀態機:draft → submitted → approved/rejected;approved 後舊版 superseded。
- 送審門檻:preflight ok + ≥1 筆 deploy 事件 + 最後 test 事件不早於最後 deploy。
- 限制:MAX_FILES=500、50MB;路徑不得含 `\` 或 `..`;slug `^[a-z0-9][a-z0-9_-]*$`(底線正規化為 `-`)。

## metadata 欄位

`name, description, long_description, icon_emoji, category, tags, access_mode,
vfs_factory_key, setup_schema, data_center_schema, data_references_schema, author, version`

- `custom_objects_schema` 非空會被 422 明確擋下(舊制退場)。
- `data_center_schema` **可以**存(validate_metadata 無 key 白名單;adopt 流程的
  `_ADOPT_METADATA_KEYS` 也包含它)。
- `category` 白名單 9 值;`tags` 必須取自 `GET /refs/tags`。
- `setup_schema`:`{KEY: {type: text|secret|select, label, required?, options?}}`。

## 沙箱(全部 `/sandbox/v/{version_id}` 前綴)

| Method / Path | 說明 |
|---|---|
| `GET /sandbox/v/{vid}/tables` | 各表筆數 |
| `POST /sandbox/v/{vid}/tables/{table}/seed?count=N` | 灌假資料 |
| `GET/PUT /sandbox/v/{vid}/secrets` | 沙箱金鑰 |
| `GET/PUT/DELETE /sandbox/v/{vid}/egress[/{slug}]` | 沙箱 egress |
| `POST /sandbox/v/{vid}/actions/apps/{app_id}/run/{name}` | 跑 action(internal);runner 未配置回 503 |
| `POST /sandbox/v/{vid}/ext/actions/run/{name}` | 跑 action(external) |
| `POST/GET /sandbox/v/{vid}/proxy/{app_id}/{table}` | SDK 相容 CRUD(internal) |
| `POST/GET /sandbox/v/{vid}/ext/proxy/{table}` | SDK 相容 CRUD(external) |

前端 preview:`https://developer.ai-go.app/preview/{module_id}?v={version_id}`
(esbuild-wasm 瀏覽器端編譯,3 秒無錯自動 POST test 事件)。

## 參考資料端點

`GET /refs/tags`、`GET /refs/available-tables`、`GET /refs/tables/{t}/columns`、`GET /auth/me`

## 來源側(AI GO 本體,`https://ai-go.app/api/v1`)

- `POST /auth/login {email,password}` → JWT(需 builder.access)
- `GET /builder/apps/{app_id_or_slug}` → 含 `vfs_state`(全量 {path: content})、`vfs_version`、`access_mode`
- `GET /data-center/tables`、`GET /data-center/tables/{key}` → 租戶自建表(key = 實體表名)
