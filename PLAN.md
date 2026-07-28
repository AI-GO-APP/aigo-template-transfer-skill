# aigo-template-transfer-skill 實作計畫

> 狀態:已實作(2026-07-28)。本文件保留原計畫供追溯;實際用法見 SKILL.md 與 README.md。
> 實作期間的重要更正:
> - §10 #1「白名單問題」**不存在**:`validate_metadata` 無 key 白名單,只擋非空 `custom_objects_schema`;
>   `_ADOPT_METADATA_KEYS` 只用於 adopt 流程且本就包含 `data_center_schema`。DSL 可直接進 draft metadata。
> - §10 #2 已拍板:一律新制 `data_center_schema`,舊制不讀不轉(掃到舊 API 一律要求改寫)。
> - §2.1 提及的 cs_desk 系統欄名碰撞經查證不存在(探查誤報)。
> - 權威 parser 驗證(--ai-go-backend)需要該 repo 的相依套件(sqlalchemy);缺套件時自動降級本地鏡射驗證。
> - 階段編排微調:normalize_meta 併入 S6 前置(非獨立階段);雜湊閘對「閘內合法寫入」
>   (apply_decisions、S5 起草、normalize_meta)放行並由 S6 污染複掃兜底。
> Repo:https://github.com/AI-GO-APP/aigo-template-transfer-skill.git

## 1. 目標與範圍

把 AI GO custom app(線上 app 或 FDE repo)轉化為可上架的 template,並**直接在 AI GO Developer 平台(https://developer.ai-go.app)建立 dev_module 與 draft 版本、在其沙箱跑端到端測試**。

- 相容標準 VFS 形狀(A 層),並以佈局適配器支援自開發佈局(B 層:`app/`、`vfs/`、`vfs/<name>/`、`aigo/`、`aigo-app/`)
- 每階段嚴謹判斷:狀態機 + 人工閘,Skill 只做判斷、腳本做修改(可重現)
- C 層(非 custom app)明確排除,不在本 skill 範圍

## 2. 事實基礎(探查結論,含前提校正)

### 2.1 前提校正(推翻先前 session 的三個假設)

1. **`scripts/dc/crosscheck.py` 不存在**(全工作區零命中)。DC 交叉稽核要自己寫。
2. **`audit_cli.py` 是 4 類閘**(禁字串/Emoji/Action 結構/Meta 完整性),不是 7 類。且完全不驗 schema 內容。
3. **Developer 平台 metadata 白名單不收 `data_center_schema`,且明確封鎖 `custom_objects_schema`**(`_ADOPT_METADATA_KEYS`)。這是本計畫最大的待拍板問題(見 §10)。

### 2.2 三系統可複用資產

| 資產 | 位置 | 用法 |
|---|---|---|
| `download_vfs_to_local(vfs_state, path)` | `ai-go-templates/.agent/skills/aigo-builder/scripts/aigo_scaffold.py` | 線上 app VFS → 本地檔案樹(跳過 PROTECTED_FILES) |
| `aigo_auth.login()` / `get_app_info()` | 同上 `aigo_auth.py` | `POST https://ai-go.app/api/v1/auth/login`;`GET /api/v1/builder/apps/{app_id}` 回 `vfs_state` 全量 |
| `analyze_vfs()` | 同上 `aigo_review.py` | SDK/INJ/APP 檔分類、app_domain 統計 |
| audit 4 閘純函式 | `ai-go-templates/.agent/skills/template-audit/scripts/audit_cli.py` | `run_audit(template_dir, rules)` 等四支吃 `Path` 參數、零第三方相依 → vendor 複製 |
| `migrate_custom_objects_meta.py` | `aigot-wt-object-migration/scripts/` | 舊 `custom_objects_schema` → 新 `data_center_schema` 落盤轉換,零相依可直接抄 |
| `parse_data_center_schema()` | `ai-go/backend/app/services/data_center/template_dsl.py` | **外部權威、不複製**;以 `--ai-go-backend=<path>` import 做真驗證 |
| `devportal_auth.py` | `ai-go-developer/scripts/` | PAT/帳密認證 helper,`.env` 讀 `DEVPORTAL_API`/`DEVPORTAL_PAT` |
| `cli/aigodev.py` | `ai-go-developer/cli/` | 單檔、吃 PAT 的完整 CLI(create/pull/push/meta/submit) — 介面參考或直接叫用 |

`scripts/import_aigo_templates.py` **不採用**:硬性要求 admin、不吃 PAT、不送審不測試。

### 2.3 Developer 平台關鍵契約(實碼確認)

- **認證**:`Authorization: Bearer aigodev_...`(PAT)或 session JWT,所有端點一視同仁。無 scope,PAT 繼承使用者 level(`read_only`/`editor`/`admin`);建模組需 `editor`,新註冊預設 `read_only` 需 admin 升級。PAT 在 https://developer.ai-go.app/settings 發行,只顯示一次。
- **建立流程**:`POST /api/v1/modules {slug,name,category,access_mode}` 會**自動建 1.0.0 draft** → `GET /modules/{id}` 取 `versions[0].id` → `PUT .../versions/{vid}/metadata` → `PUT .../versions/{vid}/files`(全量取代,自動記 `deploy` 事件)。**不要再 `POST /versions`**(存在進行中版本會 409)。
- **限制**:MAX_FILES=500、50MB;`category` 白名單 9 值;`slug` 撞 AI GO 架上 slug 409;`tags` 必須取自 `GET /refs/tags`;`access_mode` 建立後不可改。
- **送審門檻**(`assert_deployed_and_tested`):preflight ok + 至少一筆 `deploy` 事件 + 最後 `test` 事件不早於最後 `deploy`。`test` 事件只有兩條路:前端 `/preview/{mid}?v={vid}` 觀察 3 秒無錯自動回報,或 `POST .../events {kind:"test"}` 手動回報。
- **preflight 檢查**:entry(`src/main.tsx`/`App.tsx`)、相對 import 可解析、bare import 僅限 5 套件、`ctx.secrets.get` 的 key 必須在 `setup_schema` 宣告、action 必須有 `execute(ctx)`、manifest 格式。
- **沙箱**:`/api/v1/sandbox/v/{vid}/...` — tables seed/rows、secrets、egress、`actions/apps/{app_id}/run/{name}`(internal)、`ext/actions/run/{name}`(external)。server action 需後端 `RUNNER_URL` 已設,否則 503。
- **API 自省**:`GET /api/v1/dev-docs/endpoints` 回權威端點清單(含 min_level),實作時以此為準。

### 2.4 污染掃描訊號(from aigo-builder/ctx 實碼)

- 硬編 UUID(app_id/tenant_id/object_id/table_id;`api.ts` 的 `submitRecord` 第一參數常被寫死)
- 硬編 `app_domain` 字串、寫死網域/LINE channel/客戶名
- `ctx.secrets.get("K")` 的 K 未在 `setup_schema` 宣告
- `ctx.http.call(service=...)` 的 service 名(租戶 egress,跨租戶不保證存在)
- `[INJ]` 三檔(`src/data.json`/`db.json`/`actions.json`)= 租戶資料快照,必須剔除
- 舊制 API(`ctx.db.query_object` 等 CustomObject 系)= 遷移標的;新制 `query_table` 預設**升冪**,轉換時要補 `"sort": "-created_at"`
- 系統欄名碰撞:DSL field key 不得 ∈ `{id, created_at, updated_at}`(cs_desk 已踩過此 bug)

## 3. 架構總覽

```
 來源                     本 skill(獨立 repo)                          Developer 平台
┌───────────────┐   ┌──────────────────────────────────────┐   ┌─────────────────────┐
│ 線上 app      │──▶│ S1 acquire+normalize(佈局適配)       │   │ S7 建 module+draft  │
│ (builder API) │   │ S2 scan(污染清單,只報告)           │   │    PUT metadata     │
│ A 層 repo     │──▶│ S3 decide+apply(人工逐條→腳本改)   │──▶│    PUT files        │
│ B 層 repo     │   │ S4 dc_extract(表→DSL 草稿)         │   │ S8 沙箱 e2e         │
└───────────────┘   │ S5 demo data(Skill 起草→人工確認)  │   │    + test event     │
                    │ S6 audit(4 閘 vendored + 新增閘)    │   │ S9 送審(人工閘)   │
                    └──────────────────────────────────────┘   └─────────────────────┘
        每階段寫入 work/<slug>/transfer_state.json,S(n) 未過不得跑 S(n+1)
```

## 4. Repo 結構設計

```
aigo-template-transfer-skill/
  SKILL.md                    # Phase 制 SOP + 人工閘定義(繁中,沿用 aigo-builder 慣例)
  README.md
  PLAN.md                     # 本文件
  config/
    scan_rules.json           # 污染掃描規則(可擴充,exclude 機制)
    audit_rules.json          # vendored 自 template-audit + 新增閘規則
    layout_profiles.json      # B 層佈局偵測規則(root/app/vfs/aigo/aigo-app + 自訂 mapping)
  references/
    template-contract.md      # _template_meta.json 契約 + data_center_schema DSL
    devportal-api.md          # Developer API 摘要(以 /dev-docs/endpoints 校準)
    pollution-signals.md      # §2.4 訊號全表
  scripts/                    # 全部 argparse CLI、從 repo root 呼叫;相依僅 httpx
    transfer_cli.py           # 總入口:stage runner + 狀態機閘(status/run/reset)
    acquire.py                # 拉 VFS(線上 app 或 repo)+ 佈局正規化 → work/<slug>/template/
    scan.py                   # 產 work/<slug>/scan_report.json(只報告不改)
    apply_decisions.py        # 讀 decisions.json 逐條套用(參數化/保留/刪除)
    dc_extract.py             # 撈租戶表(GET /api/v1/data-center/tables)→ DSL 草稿 + 驗證
    normalize_meta.py         # 合併 _template.json/_template_meta.json → 單一合規 meta
    audit_local.py            # vendored 4 閘 + 新增閘(見 §5 S6)
    devportal.py              # set-pat/whoami/create-module/push-meta/push-files/preflight/submit
    e2e_devportal.py          # 沙箱 e2e 全套 + test event 回報
  vendor/                     # 複製的純函式,每檔頭註記來源路徑與日期
  tests/                      # skill 自身的單元測試(狀態機、佈局偵測、掃描規則)
  work/                       # (gitignore)每次轉換的工作區 work/<slug>/
```

工作區約定:`work/<slug>/template/`(產出的 templates/<slug> 標準佈局)、`transfer_state.json`(狀態機)、`scan_report.json`、`decisions.json`(人工裁決紀錄)、`e2e_report.json`。

## 5. 階段流程設計(狀態機 + 閘)

`transfer_state.json` 記錄每階段 `{status, at, input_hash, notes}`;腳本強制順序,上游重跑(input_hash 變動)自動使下游失效。**人工閘 = decisions.json 裡必須存在明確裁決紀錄,Skill 不得代填。**

| 階段 | 內容 | 執行者 | 閘 |
|---|---|---|---|
| **S0 候選判定** | 新模板 / 併入既有(對照 AI GO 架上 + developer live-templates)/ 排除;定 slug、category、access_mode(不可逆) | Skill 分析 + **人工拍板** | decisions.json 需有 `candidate` 裁決 |
| **S1 抽取正規化** | 來源三選一:線上 app(builder API 拉 `vfs_state`)/ A 層 repo / B 層 repo(layout_profiles 偵測,偵測不到則要求人工提供 mapping 檔);剔除 `[INJ]` 三檔與 PROTECTED_FILES;正規化為 `work/<slug>/template/` | 腳本 | 產出通過形狀檢查(entry、SDK 三檔、package.json 5 依賴) |
| **S2 污染掃描** | 依 scan_rules 產 `scan_report.json`:每筆 = {檔、行、訊號類型、內容、建議處置}。**只報告不改** | 腳本 | 報告存在即過 |
| **S3 去租戶化** | Skill 逐條提議(參數化→setup_schema / 保留 / 刪除),**人工逐條確認**寫入 decisions.json → `apply_decisions.py` 套用 → 重跑 S2 直到清單歸零或全部裁決為「保留」 | Skill 提議 + **人工逐條** + 腳本改 | scan 殘餘皆有裁決 |
| **S4 DC schema** | 線上來源:`GET https://ai-go.app/api/v1/data-center/tables` 撈租戶表,**人工挑選**哪些表屬於此 app;repo 來源:從舊 `custom_objects_schema`/`data.json` 轉(抄 migrate 腳本)→ 產 `data_center_schema` 草稿 → 以 ai-go 後端 `parse_data_center_schema()` 真驗證(系統欄名、relation 目標、成環) | 腳本 + **人工挑表** | parser 零錯誤 |
| **S5 demo 資料** | Skill 起草 `seed_demo_data.py`(冪等、繁中在地化、相對日期、`_cfg` 走 secrets)+ DSL `seed` 區塊,**人工確認**內容 | Skill 起草 + **人工確認** | decisions.json 有 `demo_data` 裁決 |
| **S6 本地 audit** | vendored 4 閘 + **新增閘**:schema 內容驗證、`actions/manifest.json` ↔ `actions/*.py` 一一對應、package.json 依賴完整、SDK 三檔未被改、`setup_schema` 覆蓋所有 `ctx.secrets.get` key、bare import 白名單(鏡射 preflight,在本地先擋) | 腳本(硬閘) | 全數 PASS |
| **S7 發布草稿** | PAT 前置檢查(見 §6)→ `POST /modules`(或沿用既有 module 的 draft 版)→ `PUT metadata` → `PUT files` → `GET preflight` 必須 ok | 腳本 | preflight ok |
| **S8 Developer e2e** | 見 §7;產 `e2e_report.json` | 腳本(+ 選配瀏覽器) | 全數 PASS + test 事件已記 |
| **S9 送審** | 展示 e2e 報告 → **人工拍板** → `POST .../submit` | **人工閘** + 腳本 | — |

## 6. PAT 與登入引導(SKILL.md Phase 0)

1. 讀取設定(`.env` 的 `DEVPORTAL_PAT`,沿用 `devportal_auth.py` 的變數名與快取慣例;PAT 存 gitignored 檔,絕不入 git)
2. 缺 PAT → 引導:註冊/登入 https://developer.ai-go.app → `/settings` → 「API Token(PAT)」→ 發行(提醒只顯示一次)→ `python scripts/devportal.py set-pat`
3. `whoami`(`GET /auth/me`)驗證:level 為 `read_only` 時明確告知需請 admin 升級為 `editor`,並停在此(不嘗試繞過)
4. 來源側(ai-go.app)另需 `builder.access` 帳號:沿用 aigo-builder 慣例——email 入 config、**密碼每次臨時輸入不落檔**

## 7. Developer 端到端測試設計(S8)

純 API 可完成的部分(`e2e_devportal.py`):

1. `GET preflight` → 必須 `ok==true`
2. 沙箱 secrets:依 `setup_schema` `PUT /sandbox/v/{vid}/secrets`(測試值由人工提供或用 dummy,dummy 時對應 action 標記 SKIP)
3. 沙箱資料:依 DSL `seed` 寫入表(sandbox proxy/records 端點),或 `POST .../tables/{t}/seed`
4. Actions:逐一呼叫 manifest 宣告的 action(internal:`POST /sandbox/v/{vid}/actions/apps/{app_id}/run/{name}`;external:`.../ext/actions/run/{name}`),斷言非 5xx、回應形狀合理;`seed_demo_data` 跑兩次驗冪等。**RUNNER_URL 未設會 503** — 偵測到即回報「平台側未開 runner」而非測試失敗
5. CRUD:經 sandbox proxy 對每張 DSL 表做 insert/query/update/delete 各一輪
6. 前端:優先用瀏覽器開 `/preview/{mid}?v={vid}`(3 秒無錯 → 平台自動記 `test` 事件,最真實);無瀏覽器環境則 `POST .../events {kind:"test", detail:{e2e_report 摘要}}` 補記
7. 驗證送審資格:重打 `GET /modules/{mid}` 與 events,確認 deploy/test 順序滿足門檻

## 8. 相容性設計(B 層)

`layout_profiles.json` 定義偵測規則(依序嘗試):root 即 VFS → `app/` → `aigo/` → `aigo-app/` → `vfs/`(單 app)→ `vfs/<name>/`(多 app,要求人工指定哪一支)。每個 profile 定義:VFS 根、actions 位置、meta 檔位置。全部不中 → 產 mapping 樣板檔要求人工填寫(路徑對映),這就是「一定程度支援自開發系統」的邊界:**偵測自動化、對映可人工、超出即明確拒絕**(如自寫 deploy 腳本的邏輯不遷移,只遷 VFS 內容)。

## 9. 相依與 vendoring 策略

- 執行相依:僅 `httpx`(+ stdlib);Python ≥3.10;`pyproject.toml` + `uv.lock`(沿用 aigo-builder 慣例)
- vendor(複製 + 來源註記):audit 4 閘純函式、`download_vfs_to_local`、`analyze_vfs`、migrate 轉換邏輯 — 皆零相依純函式,複製成本低於跨 repo 引用
- 外部權威(不複製):`template_dsl.py` 以 `--ai-go-backend=<path>` 動態 import;找不到時降級為「本地結構檢查 + 警告」並在 audit 報告標注未做真驗證

## 10. 風險與待拍板問題

1. **【最重要】DSL 進不了 Developer metadata**:`validate_metadata` 白名單無 `data_center_schema` 且封鎖 `custom_objects_schema`。選項:(a) 改 ai-go-developer 後端把 `data_center_schema` 加入白名單(建議,小改);(b) schema 只放在 files 內的 `_template_meta.json`,靠 adopt 時處理。**需拍板,若選 (a) 是前置相依。**
2. **Schema 制式**:建議一律產新制 `data_center_schema`(relation/unique/options/seed 只有新制有;ai-go 後端已雙讀回退),舊制只做讀入轉換。需確認。
3. **產出落點**:本計畫以 Developer 平台 draft 為唯一目的地,`work/<slug>/template/` 為本地產物。是否同時要回灌 `ai-go-templates` repo(接 audit/deploy 既有管線)?需拍板。
4. **帳號前置**:Developer 帳號需 editor(admin 升級);來源側需 `builder.access`。白老鼠開跑前要備妥。
5. **沙箱 runner**:線上 developer 平台 `RUNNER_URL` 是否已配置未知,S8 第 4 步可能整段 503。首次驗證時確認,未配置則 server action 測試降級為靜態檢查 + preflight。
6. **test 事件語義**:API 補記 `test` 事件形式上滿足送審門檻但未真跑前端。建議規範:能開瀏覽器就走 preview,不能才補記並在 detail 註明。

## 11. 實作順序(里程碑)

- **M0 骨架**:repo scaffold、SKILL.md(Phase 0 + 狀態機定義)、`devportal.py`(set-pat/whoami/create-module 打通,用拋棄式 slug 驗證)、狀態機 + tests
- **M1 取得**:`acquire.py`(A 層 repo + 線上 app 兩條路)+ 形狀檢查
- **M2 掃描與裁決**:`scan.py` + `decisions.json` 格式 + `apply_decisions.py`
- **M3 schema 與 audit**:`dc_extract.py`、`normalize_meta.py`、`audit_local.py`(vendored + 新增閘)
- **M4 發布與 e2e**:`devportal.py` push-meta/push-files/preflight、`e2e_devportal.py` 全套
- **M5 白老鼠**:`FDE-URfit-FDE-task-manager` 走完 S0→S9,修流程;SKILL.md 定稿
- **M6 B 層**:layout_profiles + mapping 機制,以 `fde-echouse` 或 `fde-czone` 驗證

M0 開工前需先拍板 §10 的 #1(白名單)與 #2(schema 制式)。
