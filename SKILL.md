---
name: aigo-template-transfer
description: >
  Use when converting an AI GO Custom App (live app on ai-go.app or an FDE repo)
  into a marketplace template：抽取正規化 → 去租戶化 → Data Center schema →
  本地 audit → 在 AI GO Developer 平台(developer.ai-go.app)建立 dev_module 草稿 →
  沙箱端到端測試 → 送審。每階段有硬閘,人工裁決不可代填。
---

# AI GO Custom App → Template 轉換 Skill

本 Skill 協助 AI Agent 把 custom app 轉化為可上架的 template。
支援 Claude Code / Antigravity / Cursor。

## Phase -1:Skill 自我更新檢查(每次觸發時執行)

> 若已裝 SessionStart hook(見 README「保持更新」;Claude Code 與 Codex 都有範本),
> 本階段會自動被跳過(節流),不必重複執行。

```bash
python scripts/check_update.py     # macOS / Linux 用 python3
```

- **無輸出 = 沒事**:已最新、離線、或 24 小時內已檢查過都會靜默結束,直接進 Phase 0。
- **有輸出 = 有新版**:把版本落差與變更摘要告知使用者,**詢問是否更新**;
  同意 → 執行腳本印出的更新指令,完成後**重新讀取 SKILL.md 與相關 references**,
  讓新版規則在本回合就生效(舊版已在 context 裡,不重讀會沿用舊教義)。
- **絕不自動覆寫**:使用者可能改過本地檔案;未取得同意前不要執行更新指令。
- 需要機器可讀結果時用 `--json`(一律輸出,`status` 為
  `skipped`/`unknown`/`current`/`outdated`)。

## 鐵律(先讀)

1. **AI 只做判斷與提議,腳本做修改。** 所有對 template 內容的變更必須經由
   `apply_decisions.py` 依 decisions.json 套用——不得直接編輯 `work/<slug>/template/` 下的檔案。
   唯二例外:Phase 5 起草 `actions/seed_demo_data.py`(新檔,仍需用戶 gate 確認)、
   Phase 4 後由 `normalize_meta.py` 生成 `_template_meta.json`。
2. **人工閘不可代填。** decisions.json 內 `decided_by: "user"` 的紀錄只能在用戶明確確認後寫入;
   `transfer_cli.py gate` / `confirm-source` / `confirm-meta` 與 `devportal.py submit`(及
   `adopt`)的互動確認必須由用戶親自輸入。AI 的提議一律先以 `decided_by: "proposed"` 呈現給用戶。
   人工閘共六道:S0 候選判定、**S1 前來源身分**、S3 逐條裁決、S5 demo 資料、
   **S6 前 meta 門面文案**、S9 送審。
3. **階段不可跳。** 狀態機(S0→S9)由腳本強制;內容雜湊閘會擋下任何閘外變更。
4. **一律新制。** 只產 `data_center_schema`(version=1);舊制 custom_objects_schema
   不讀、不轉、不輸出。掃到舊制 API(`ctx.db.*_object`)一律改寫為新制。
5. **C 層不做。** 非 custom app(獨立 Next.js/Express/Flutter 等)不進本流程;
   轉換它們等於重寫,直接向用戶說明排除。
6. **對外呼叫一律走 egress 閘道 `ctx.http.call`,金鑰由 action 自己帶。** action 呼叫
   第三方 API 的正解是 `ctx.http.call("<egress-slug>", "<path>", method=..., body=...,
   headers=...)`,並在 `_template_meta.json` 的 `required_egress` 宣告該 slug
   (normalize_meta.py 會自動補)。
   **憑證自帶才是正道(2026-08-03 反轉,ADR 0010 domain-only)**:閘道只驗域名與政策,
   **不注入也不剝除** `Authorization`——AI GO `connector_proxy._sanitize_headers` 與
   Developer 平台 `dev_ctx._STRIPPED` 現在都只剝 hop-by-hop(`host`/`content-length`/
   `proxy-*`)。金鑰走 `setup_schema` 收編、action 端 `ctx.secrets.get(...)` 讀出來組
   headers;EgressService 只提供 base_url 與白名單,`auth_type` 一律 `none`
   (沙箱端填別的值會 400)。
   **舊教義(v0.6.x 以前)寫「憑證不可自帶、金鑰歸 EgressService 注入」,那已經是錯的**
   ——照舊寫法產出的模板沙箱測得過、上線後 401,而且錯誤浮現在「租戶新增渠道」
   離部署最遠的地方。看到舊模板是注入式寫法,改成自帶。
   **`import httpx` 打不出去**:runner pod 是 default-deny egress(ADR-0003,SG 只放行
   ctx-only service),raw httpx/requests 會直接 timeout,沙箱測不過。
7. **憑證紀律。** 密碼只存在 `~/.aigo-transfer/.env` 且由**用戶本人**填寫;agent 不代填、
   不在對話中詢問密碼、不把密碼放進指令列。用戶若在對話貼出密碼,提醒改填 `.env` 並更換。
8. **出錯先查表。** 任何失敗先讀原始 error message 再查
   `references/troubleshooting.md`,不要自行推測修法;權限與設定問題改 code 改不掉。

## 路徑約定

本文件寫的 `.env` 與 `work/<slug>/` 都在使用者資料目錄 `~/.aigo-transfer/` 底下
(可用 `AIGO_TRANSFER_HOME` 覆寫),**不在 skill 目錄內**——複製式安裝更新時
skill 目錄會被整個清掉重鋪。腳本輸出一律印絕對路徑,要給用戶路徑時照抄腳本輸出,
不要自己拼 `<skill>/work/...`。舊版留在 skill 目錄內的資料會在首次執行時自動搬遷。

## Phase 0:前置檢查(每次開工先跑)

```bash
python scripts/devportal.py whoami      # 目的地側:Developer 平台 PAT 與權限
python scripts/aigo_client.py whoami    # 來源側:AI GO 帳號與 builder.access(抽線上 app 才需要)
```

- 失敗或無 PAT → `python scripts/devportal.py setup` 依指引引導用戶:
  1. 登入/註冊 https://developer.ai-go.app(未登入先引導註冊)
  2. 設定頁 https://developer.ai-go.app/settings →「API Token(PAT)」→ 發行(只顯示一次)
  3. `python scripts/devportal.py set-pat` 貼入
- `level=read_only` → 告知用戶需請平台 admin 升級為 editor,**停在這裡**,不嘗試繞過。
- 來源側 AI GO 帳號(builder.access):請用戶**本人**在 `~/.aigo-transfer/.env` 填 `AIGO_EMAIL` /
  `AIGO_PASSWORD`(或 `AIGO_TOKEN`)。`aigo_client.get_token()` 會走
  「token 快取 → refresh 換發 → 帳密登入」,正常情況全程無感;
  拋 RuntimeError 時把訊息原樣轉給用戶(內含設定指引)。
  **在這裡把憑證問題解決掉**——不然它會在 S1 抽到一半才爆,錯誤混在抽取流程裡更難判讀。
  缺 `builder.access` 是權限設定問題,請租戶管理員授予,不要改 code 繞路
  (只有純 repo 來源的轉換用不到來源側憑證,可跳過這支)。

## Phase 0.5:候選判定(S0,人工閘)

先盤點,再讓用戶拍板:

1. 檢視來源 app 的功能與規模(actions 數、頁面數、自建表)。
2. 對照既有模板是否重疊(架上清單即唯一權威):

```bash
python scripts/devportal.py live-templates [--query <關鍵字>]
```

   若判定為「併入既有」且該支**未受管**(`can_adopt`),要先接管才能在本平台改:
   `python scripts/devportal.py adopt --template-slug <架上 slug>`(admin、**不可逆**、
   帶人工確認閘),接管後用 `pull` 取回內容當維護基準。

3. 向用戶呈報三選一建議(新開 new / 併入既有 merge / 排除 exclude)與理由,由用戶執行:

```bash
python scripts/transfer_cli.py init --slug <slug>
python scripts/transfer_cli.py gate --slug <slug> --stage S0 --decision new --notes "<理由>"
```

slug 規則:`^[a-z0-9][a-z0-9_-]*$`;撞 AI GO 架上 slug 會在 S7 得到 409。
category 白名單:starter/messaging/crm/catering/integration/ai/operations/productivity/analytics。
access_mode 建立後不可改,先想清楚。

## Phase 1:抽取正規化(S1)

**線上 app:先確認身分再抽**(人工閘)。app uuid 打錯不會 404、不會有任何警訊,
只會安靜地把**別支 app** 的內容做成模板,通常到上架才發現:

```bash
python scripts/acquire.py --list-apps                 # 列租戶下的 app(slug/status/更新時間/uuid)
# ↓ 由用戶執行:對著平台回傳的名稱、slug、uuid、檔數確認「就是這一支」
python scripts/transfer_cli.py confirm-source --slug <slug> --app <uuid_or_slug>
python scripts/acquire.py --slug <slug> --from-app <uuid_or_slug>
```

`acquire --from-app` 會先驗這道裁決存在,再把抓回來的 app id 與用戶確認過的比對;
不符即停(要換來源就重跑 confirm-source)。

**repo 來源:本地路徑或 URL 皆可**:

```bash
python scripts/acquire.py --slug <slug> --from-repo <path>
python scripts/acquire.py --slug <slug> --from-repo https://github.com/org/repo.git [--ref <branch|tag>]
# 多 app 佈局加 --vfs-subdir;全部偵測不中的自開發佈局:與用戶確認對映後提供 mapping 檔
python scripts/acquire.py --slug <slug> --from-repo <path> --mapping mapping.json
```

URL 來源會 `git clone --depth 1` 到 `work/<slug>/src_repo/`(唯讀取用,不會推回去),
狀態機記下 commit 短碼以利重現。**認證交給 git 本身**(gh auth login / SSH key /
credential helper);不要把 token 寫進 URL——真寫了,腳本在輸出與狀態檔會把 userinfo
遮掉,但它仍留在你的 shell 歷史裡。私有 repo 沒授權會 clone 失敗,依訊息設好認證再重跑。

> **只吃 custom app 形狀的 repo**(鐵律 5):偵測 VFS 佈局要看到 `src/main.tsx`
> 或 `src/App.tsx`。一般 web app(獨立 Next.js/Express/Flutter)clone 得下來也過不了
> 形狀檢查——那是重寫,不是轉換,直接向用戶說明排除。

INJ 三檔(data.json/db.json/actions.json)自動改空殼,原件在 `work/<slug>/raw/` 供 Phase 4 參考。
形狀檢查失敗(缺 entry / SDK 檔)→ 與用戶討論;缺 SDK 檔可從 starter 模板補 canonical 版本
(這屬於「腳本外修改」,補完跑 `transfer_cli.py reset --from-stage S1` 重新過 S1)。

S1 同時盤點**不隨 VFS 走的資源**(對齊 builder Phase 0)→ `work/<slug>/inventory.json`:
- webhook 宣告(manifest 的 `"webhook": true` + `receive_webhook`)——對外端點
- action 對外呼叫的網域——安裝租戶要設 Egress 白名單
- app 排程(`GET /app-crons`;repo 來源撈不到,會註記請人工確認)
- legacy CustomObject 痕跡

這份盤點會在 Phase 6 由 normalize_meta 轉成「安裝後設定清單」寫進 long_description。
**盤點結果要向用戶摘報**——排程與 webhook 是模板帶不走的能力,不講清楚 = 安裝後默默失效。

## Phase 2:污染掃描(S2)

```bash
python scripts/scan.py --slug <slug>
```

產出 `work/<slug>/scan_report.json`。**只報告,不改。**

## Phase 3:去租戶化(S3,人工逐條)

1. 逐條閱讀 scan_report,對每筆 finding 起草裁決提議(`decided_by: "proposed"`)寫入
   decisions.json 的 `findings` 區。裁決三種:
   - `replace`:精確字串 old→new(參數化→`ctx.secrets.get` + setup_schema;或改為執行期取得)
   - `delete_file`:整檔是客戶專屬雜物
   - `keep`:確認無害(blocker 不可 keep)
2. 向用戶完整呈現提議清單(檔案、行、內容、動作、理由),請用戶逐條或整批確認。
3. 用戶確認後,把確認過的條目改為 `decided_by: "user"`(僅限用戶明確同意的條目)。
4. 套用:

```bash
python scripts/apply_decisions.py --slug <slug> --check   # 先驗完整性
python scripts/apply_decisions.py --slug <slug>           # 套用 + 複掃收斂
```

參數化時同步規劃 setup_schema:key 命名通用化(例:`LINE_CHANNEL_ACCESS_TOKEN`,
不要 `URFIT_LINE_TOKEN`),Phase 4 後由 normalize_meta 寫入 meta。

改寫對外呼叫時遵守鐵律 6:硬編碼第三方端點與 raw httpx/requests 一律改為 `ctx.http.call`

```python
def execute(ctx):
    # slug 對應租戶註冊的 EgressService,那裡只有 base_url(domain-only,ADR 0010);
    # 金鑰由 action 自己帶——閘道不注入也不剝除 Authorization。
    token = ctx.secrets.get("EXAMPLE_API_TOKEN")
    resp = ctx.http.call(
        "example-api",
        "/v1/send",
        method="POST",
        body={"text": ctx.params.get("text")},
        headers={"Authorization": f"Bearer {token}"},
    )
    if int(resp.get("status") or 500) >= 400:
        ctx.response.json({"error": "外部服務暫時無法使用", "status": resp.get("status")})
        return
    ctx.response.json(resp.get("data") or {})
```

> `ctx.http.call` 的位置參數順序是 `(service, path, method, body, headers, params)`
> ——SDK 走 positional list 過 RPC,順序錯不會報錯,只會把 body 塞進 headers。
> 用具名參數寫就不會踩到。

金鑰記入 `setup_schema`(`{"EXAMPLE_API_TOKEN": {"type": "secret", ...}}`),
slug 記入「安裝後設定清單」:租戶要在後台 `/dashboard/settings/integrations` 以**同名 slug**
註冊 EgressService(只需填 base_url),否則 action 連不出去——這是設定問題,
改 code 改不掉。`required_egress` 宣告會讓安裝流程主動提示租戶完成這一步。

webhook / 排程觸發的 action 改寫時**必須保持冪等**(平台 at-least-once,可能重複執行);
去重 key 優先用事件本身的業務 id,其次 `ctx.params["delivery_id"]`。

## Phase 4:Data Center schema(S4,人工挑表)

```bash
python scripts/dc_extract.py --slug <slug> --list          # 列租戶表(* 標記 actions 有引用)
python scripts/dc_extract.py --slug <slug> --tables k1,k2  # 用戶挑定後執行
python scripts/dc_extract.py --slug <slug> --none          # 此 app 無自建表
# 建議加 --ai-go-backend <ai-go repo 路徑> 用權威 parser 驗證
```

- 哪張表屬於此 app、哪張是隔壁 app 共用——**必須由用戶判斷**,`--tables` 即裁決。
- 欄位 key 不得用系統欄名(id/created_at/updated_at),腳本會自動剔除並驗證。
- repo 來源沒有線上租戶可撈時:從 `raw/src/data.json` 與 action 程式碼推導表結構,
  以 `--from-file` 提供表定義草稿,並向用戶確認。

## Phase 5:demo 資料(S5,人工閘)

為業務型模板起草(integration 類可 skip):

1. `actions/seed_demo_data.py`:冪等(先查主表有資料即跳出)、繁中台灣在地化示範資料、
   相對日期(`date.today() + timedelta`)、用 `ctx.log()` 不用 `print()`、
   新制 API(`ctx.db.query_table` 預設升冪,要顯式 `"sort": "-created_at"`)。
2. 在 manifest.json 註冊(`timeout_ms: 30000`)。
3. 小表可直接在 dc_schema.json 的表加 `seed` 區塊(僅新建表會灌)。
4. 給用戶審閱後由用戶執行:

```bash
python scripts/transfer_cli.py gate --slug <slug> --stage S5 --decision approved
# 或不需要 demo 資料:
python scripts/transfer_cli.py gate --slug <slug> --stage S5 --decision skipped --notes "<理由>"
```

## Phase 6:meta 與本地 audit(S6)

```bash
python scripts/normalize_meta.py --slug <slug> --name "<名稱>" --category <cat> \
    --description "<一句話>" --author "<作者>" [--setup-schema setup.json] [--tags a,b]
# ↓ 人工閘,由用戶執行:逐項讀過 meta 才放行(AI 可以起草,不能拍板)
python scripts/transfer_cli.py confirm-meta --slug <slug>
python scripts/audit_local.py --slug <slug> [--ai-go-backend <path>]
```

- normalize_meta 會以最終內容重盤 inventory:自動生成「安裝後設定清單」入
  long_description,並把殘留的 `ctx.http.call(slug)` 自動宣告進 `required_egress`
  (缺宣告 = 租戶安裝不被提示授權,裝了也跑不動)。
- **meta 人工閘**:name / description / category / tags / long_description 是上架後
  第三方唯一看得到的門面,錯字、殘留客戶名、category 選錯都要重送審。audit 的
  「meta 人工閘」項會擋到用戶確認為止;裁決綁定檔案雜湊——**確認後 meta 再被改過就要重確認**
  (重跑 normalize_meta 產出完全相同的內容則沿用原確認,不必重按)。
  向用戶呈報時把 long_description 全文帶上,別只報欄位名。
- `--ai-go-backend` 建議指向 **ai-go-developer** repo(ctx-core 的 DSL parser 零相依,
  且與平台「存檔即驗」跑的是同一套);指向 ai-go 亦可(需該 repo 相依套件)。
- `actions/_shared/**.py` 共用模組不要求 `execute(ctx)`(audit 已豁免)。

全數 PASS 才過。失敗項若需改 code:回 Phase 3 補裁決(`reset --from-stage S2` 後重跑),
不要手改。

## Phase 7:Developer 平台建草稿(S7)

```bash
python scripts/devportal.py push --slug <slug>
```

建模組(平台自動帶 1.0.0 draft)→ 推 metadata → 推 files(平台自動記 deploy 事件)
→ 平台 preflight 必須 ok。**push 內建寫後回讀(★)**:metadata 關鍵欄位
(name/category/setup_schema/data_center_schema)與檔數都會 GET 回來比對,
不符即失敗——不要靠 API 回傳的 200 就宣稱成功。

push 另會前置驗證 `data_references_schema`(`GET /refs/available-tables` /
`.../columns`):引用了 AI GO 不存在的表或欄位直接擋下,不必等推完檔才被 preflight fail。
**這兩支端點不是每個部署都有**(權威清單見 `GET /dev-docs/endpoints`);讀不到時
push 印 WARN 而非放行綠燈——那代表「引用宣告未經驗證」,正確性改由 S8 承擔。

**沒有可編輯版本時**(上一版已送審或已發布),push 會停下並指出該用哪一支:

```bash
python scripts/devportal.py withdraw --slug <slug>              # 送審中 → 撤回才能改
python scripts/devportal.py bump --slug <slug> --kind minor     # 已發布 → 開新版本
```

`bump` 會把新版本設為 S7 目標並**重置 S8/S9**(新版本沒測過,舊綠燈不可沿用)。
要核對平台實際存了什麼、或接手一支不是本機轉出來的模板:
`python scripts/devportal.py pull --slug <slug>`。

> **模組狀態多了 `unpublished`**(平台 2026-08-11):曾上架後被下架的模組狀態是
> `unpublished` 而非 `draft`,且**全部版本會被設為 `superseded`**——所以下架後要繼續
> 開發,`push` 會告訴你先 `bump`。取消下架(`POST /modules/{id}/restore`,portal 上
> 的「取消下架」)只把狀態改回 `draft`,**不會復架**;要再上架只能重新送審核准。
> `withdraw`(撤回送審)與「下架」是兩件不同的事,別混用。

## Phase 8:沙箱端到端測試(S8)

```bash
python scripts/e2e_devportal.py --slug <slug>              # full(送審必須)
python scripts/e2e_devportal.py --slug <slug> --quick      # 快速檔(迭代中重驗用)
```

分級(對齊 builder 的變更範圍分級):

| 檔位 | 內容 | 用途 |
|---|---|---|
| `--quick` | preflight + 沙箱 secrets + 每張表 CRUD(insert→list→update→delete) | 只改文案/CSS 後的快速重驗;不記 test 事件、不推進狀態機 |
| full(預設) | quick + 沙箱 egress 註冊 + 全部 enabled action 執行 + `seed_demo_data` 冪等重跑 + test 事件 | **送審前必須**(本 skill 的要求,平台已不強制);S9 會檢查最後一次 e2e 是 full |

e2e 的表 CRUD **分兩個面跑**,兩者的端點不同、不可互串(細節見
`references/devportal-api.md`「資料面有兩組」):

- `data_center_schema` 宣告的**自建表** → `/data-center/tables/{key}/records`
  (舊的 `/data/objects/` 面已隨 AI GO 退場,平台回 404;update/delete 要帶表名)
- `data_references_schema` 宣告的**引用表** → `/proxy/...`(平台會驗 AI GO 快照)

引用表的樣本列依 `GET /refs/tables/{t}/columns` 的真實欄位型別產生;
宣告了 AI GO 不存在的表會在此 fail(而非等到上架後 runtime 才被擋)。
該端點不在此部署時(404)改走 seed 週期——`POST /sandbox/v/{vid}/tables/{t}/seed`
讓平台自己產樣本列,seed→list→query→update→delete,鑑別力不變(表不存在 seed 回 4xx)。
seed 回 5xx 是平台端產樣本列出錯,降為唯讀驗證並記 WARN,**寫入路徑未驗要向用戶帶到**。

**送審門檻(平台 2026-08-04 放寬)**:硬門檻只剩 **preflight ok + 該版本至少一筆
deploy 事件**(`assert_deployed`)。預覽測試與「每支 enabled action 至少一次 success」
**都已改為非強制**——2026-07-28 那版加嚴在實務上把送審卡死在測試儀式(bump 不改碼
也得逐支重跑),平台已收回。

**但門檻放寬不等於品質放寬。** e2e 的 `submit-gate` 條目仍跟伺服器對帳
(`GET .../events`),沒跑過的 action 照樣列出來——只是語氣從「會被平台擋下」改為
「未經驗證,送審前要向用戶交代」。**沒跑過就送審 = 沒人驗過的 code 上架**,
這件事由本 skill 的人工閘(S9)把關,不再指望平台擋。任何時候都可單獨查現況:

```bash
python scripts/devportal.py events --slug <slug>
```

這代表:
- `--expect allow_fail_actions` 宣告過的 action 不會擋住送審,但**必須在摘報時逐支
  點名**:哪支沒驗過、為什麼(缺真實憑證/外部服務不可達)、風險是什麼。
- 真跑不通又不想帶風險上架的,仍是那兩條路:補真憑證(`--secrets-file`)重跑,
  或 manifest 設 `is_enabled:false` 停用後重新 push。
- `bump` 出來的版本現在會自動記一筆 deploy 事件(`detail.source=bump`),不會再
  卡在「佈署 0 次」而送不出去。
- prod 部署由 release tag 觸發,線上平台可能落後 main——若送審意外被 422 擋下且
  訊息提到 action 未執行,那是舊門檻仍在線上,依舊訊息補跑即可。

判讀規則(寫進報告,向用戶摘報時逐條說明):
- **dummy 金鑰下的 pass 不等於完整可用性**:action 可能只走到早退路徑
  (如驗簽失敗即回)就回 2xx,深層邏輯並未執行。向用戶摘報時凡以 dummy 值
  通過的 action 都要標注「淺層通過」;正式上架品質以真值測試為準。
- 需要真實第三方連線的 action:**憑證一律走 `--secrets-file`**(對應 setup_schema 的
  key,action 自己組 Authorization);`--egress-file` 只給 slug 的真實 `base_url`
  與 `allow_dynamic_host`——沙箱 egress 是 domain-only,填 `auth_type`/`auth_config`
  會被平台 400 擋下(鐵律 6)。都給不了就在 `--expect` 的 `allow_fail_actions`
  宣告並說明。
- runner 503 = 平台側未開 action runner → 記 SKIP;送審前向用戶明確標注此風險。
- `approval_status: "pending"` / 簽核例外 → 記 WARN,**非失敗、不可重試**
  (重試 = 重複建單 + 重複開簽核單)。
- webhook 宣告的 action 在沙箱以一般 action 驗證;**對外端點登記無法在沙箱測**,
  已列入安裝後設定清單,向用戶說明。
- 預設自動記 test 事件(滿足送審門檻);要走最真實的前端驗證改 `--no-event`,
  再開 `https://developer.ai-go.app/preview/<module_id>?v=<version_id>`(3 秒無錯自動記)。

## Phase 9:送審(S9,人工閘)

前置:最後一次 e2e 必須是 full(腳本會擋)。向用戶摘報 e2e_report.json 重點
(特別是 SKIP/WARN 項與安裝後設定清單),由用戶執行:

```bash
python scripts/devportal.py submit --slug <slug> --note "<給審核者的說明>"
```

submit 內建寫後回讀:確認版本狀態已轉 `submitted`。

## 驗證流程快速參照

```
每次改動 template 內容(回 Phase 3 補裁決後):
  scan 複掃 → apply_decisions → (meta 有動則 normalize_meta → confirm-meta)
  → audit_local → push → e2e --quick
里程碑 / 送審前:
  audit_local 全綠 → push(寫後回讀)→ e2e full(actions + 冪等 + test 事件)
  → 摘報 e2e_report + 安裝後設定清單 → 用戶 submit
```

## 錯誤處理

> 任何一步失敗 → **先完整讀出原始 error message**,再查
> `references/troubleshooting.md` 速查表,不要自行推測修法。

常見狀態碼語義:**401** 認證失效(PAT 撤銷/過期)|**403** 權限
(Developer 端 read_only / AI GO 端缺 builder.access,**不重試不繞路**)|
**409** slug 撞名或版本線衝突|**400** metadata 驗證失敗(型別契約、category、tags
白名單)與其他輸入不合法|**422** **送審擋門**(preflight 有 fail、或該版本無佈署紀錄)|
**503** 沙箱 runner 未配置(平台設定,非程式問題)。

> metadata 錯誤是 **400 不是 422**(2026-08-12 對正式平台實測確認:
> `PUT metadata` 的 `validate_metadata` ValueError → 400)。查表時別走錯行。

**Egress / 權限類錯誤 = 設定問題**:立刻停止改 code,把原始訊息轉給用戶,
引導到後台 `/dashboard/settings/integrations`(或請租戶管理員/平台 admin 處理)。

## 參考文件

| 檔案 | 內容 |
|------|------|
| `references/template-contract.md` | 模板目錄佈局、meta 契約、DSL 規則、新舊 API 對照、正式站行為與必帶防禦 |
| `references/devportal-api.md` | Developer 平台 API 子集(權威:`GET /dev-docs/endpoints`) |
| `references/pollution-signals.md` | 租戶污染訊號與人工判讀要點 |
| `references/troubleshooting.md` | **出錯時**:症狀→成因→處置速查表 |
