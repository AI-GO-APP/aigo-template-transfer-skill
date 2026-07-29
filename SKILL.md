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

> 若已裝 SessionStart hook(見 README「自動更新檢查」),本階段會自動被跳過(節流),
> 不必重複執行。

```bash
python scripts/check_update.py     # macOS / Linux 用 python3
```

- **無輸出 = 沒事**:已最新、離線、或 24 小時內已檢查過都會靜默結束。
- **有輸出 = 有新版**:把版本落差與變更摘要告知使用者,**詢問是否更新**;
  同意 → 執行腳本印出的更新指令,完成後重新讀取 SKILL.md 讓新版在本回合生效。
- **絕不自動覆寫**:未取得同意前不要執行更新指令。

## 鐵律(先讀)

1. **AI 只做判斷與提議,腳本做修改。** 所有對 template 內容的變更必須經由
   `apply_decisions.py` 依 decisions.json 套用——不得直接編輯 `work/<slug>/template/` 下的檔案。
   唯二例外:Phase 5 起草 `actions/seed_demo_data.py`(新檔,仍需用戶 gate 確認)、
   Phase 4 後由 `normalize_meta.py` 生成 `_template_meta.json`。
2. **人工閘不可代填。** decisions.json 內 `decided_by: "user"` 的紀錄只能在用戶明確確認後寫入;
   `transfer_cli.py gate` 與 `devportal.py submit` 的互動確認必須由用戶親自輸入。
   AI 的提議一律先以 `decided_by: "proposed"` 呈現給用戶。
3. **階段不可跳。** 狀態機(S0→S9)由腳本強制;內容雜湊閘會擋下任何閘外變更。
4. **一律新制。** 只產 `data_center_schema`(version=1);舊制 custom_objects_schema
   不讀、不轉、不輸出。掃到舊制 API(`ctx.db.*_object`)一律改寫為新制。
5. **C 層不做。** 非 custom app(獨立 Next.js/Express/Flutter 等)不進本流程;
   轉換它們等於重寫,直接向用戶說明排除。
6. **對外呼叫一律走 egress 閘道 `ctx.http.call`。** action 呼叫第三方 API 的正解是
   `ctx.http.call("<egress-slug>", "<path>", method=..., body=...)`,並在
   `_template_meta.json` 的 `required_egress` 宣告該 slug(normalize_meta.py 會自動補)。
   **憑證不可自帶**:`Authorization` header 會被閘道剝掉(AI GO `connector_proxy._sanitize_headers`
   與 Developer 平台 `dev_ctx._STRIPPED` 兩邊都剝),金鑰由租戶註冊 EgressService 時填入、
   閘道注入;action 端不碰金鑰,故也不需要為它開 `setup_schema` 欄位。
   **`import httpx` 打不出去**:runner pod 是 default-deny egress(ADR-0003,SG 只放行
   ctx-only service),raw httpx/requests 會直接 timeout——沙箱測不過,而送審門檻要求
   每支 enabled action 至少一次 success,等於卡死。
7. **憑證紀律。** 密碼只存在 `.env`(gitignored)且由**用戶本人**填寫;agent 不代填、
   不在對話中詢問密碼、不把密碼放進指令列。用戶若在對話貼出密碼,提醒改填 `.env` 並更換。
8. **出錯先查表。** 任何失敗先讀原始 error message 再查
   `references/troubleshooting.md`,不要自行推測修法;權限與設定問題改 code 改不掉。

## Phase 0:前置檢查(每次開工先跑)

```bash
python scripts/devportal.py whoami
```

- 失敗或無 PAT → `python scripts/devportal.py setup` 依指引引導用戶:
  1. 登入/註冊 https://developer.ai-go.app(未登入先引導註冊)
  2. 設定頁 https://developer.ai-go.app/settings →「API Token(PAT)」→ 發行(只顯示一次)
  3. `python scripts/devportal.py set-pat` 貼入
- `level=read_only` → 告知用戶需請平台 admin 升級為 editor,**停在這裡**,不嘗試繞過。
- 來源側 AI GO 帳號(builder.access):請用戶**本人**在 `.env` 填 `AIGO_EMAIL` /
  `AIGO_PASSWORD`(或 `AIGO_TOKEN`)。`aigo_client.get_token()` 會走
  「token 快取 → refresh 換發 → 帳密登入」,正常情況全程無感;
  拋 RuntimeError 時把訊息原樣轉給用戶(內含設定指引)。

## Phase 0.5:候選判定(S0,人工閘)

先盤點,再讓用戶拍板:

1. 檢視來源 app 的功能與規模(actions 數、頁面數、自建表)。
2. 對照既有模板是否重疊:平台 `GET /live-templates`(架上清單即唯一權威)。
3. 向用戶呈報三選一建議(新開 new / 併入既有 merge / 排除 exclude)與理由,由用戶執行:

```bash
python scripts/transfer_cli.py init --slug <slug>
python scripts/transfer_cli.py gate --slug <slug> --stage S0 --decision new --notes "<理由>"
```

slug 規則:`^[a-z0-9][a-z0-9_-]*$`;撞 AI GO 架上 slug 會在 S7 得到 409。
category 白名單:starter/messaging/crm/catering/integration/ai/operations/productivity/analytics。
access_mode 建立後不可改,先想清楚。

## Phase 1:抽取正規化(S1)

```bash
# 線上 app
python scripts/acquire.py --slug <slug> --from-app <app_id_or_slug>
# 本地 repo(A 層自動偵測;B 層 vfs/ aigo/ app/ 依 profiles;多 app 加 --vfs-subdir)
python scripts/acquire.py --slug <slug> --from-repo <path>
# 全部偵測不中的自開發佈局:與用戶確認對映後提供 mapping 檔
python scripts/acquire.py --slug <slug> --from-repo <path> --mapping mapping.json
```

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
    # service slug 對應租戶註冊的 EgressService(base_url + 憑證都在那裡);
    # 這裡只寫 slug 與 path,不碰金鑰、不自帶 Authorization(閘道會剝掉)。
    resp = ctx.http.call(
        "example-api",
        "/v1/send",
        method="POST",
        body={"text": ctx.params.get("text")},
    )
    if int(resp.get("status") or 500) >= 400:
        ctx.response.json({"error": "外部服務暫時無法使用", "status": resp.get("status")})
        return
    ctx.response.json(resp.get("data") or {})
```

slug 記入「安裝後設定清單」:租戶要在後台 `/dashboard/settings/integrations` 以**同名 slug**
註冊 EgressService(填 base_url 與該租戶自己的金鑰),否則 action 連不出去——這是設定問題,
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
python scripts/audit_local.py --slug <slug> [--ai-go-backend <path>]
```

- normalize_meta 會以最終內容重盤 inventory:自動生成「安裝後設定清單」入
  long_description,並把殘留的 `ctx.http.call(slug)` 自動宣告進 `required_egress`
  (缺宣告 = 租戶安裝不被提示授權,裝了也跑不動)。
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

## Phase 8:沙箱端到端測試(S8)

```bash
python scripts/e2e_devportal.py --slug <slug>              # full(送審必須)
python scripts/e2e_devportal.py --slug <slug> --quick      # 快速檔(迭代中重驗用)
```

分級(對齊 builder 的變更範圍分級):

| 檔位 | 內容 | 用途 |
|---|---|---|
| `--quick` | preflight + 沙箱 secrets + 每張表 CRUD | 只改文案/CSS 後的快速重驗;不記 test 事件、不推進狀態機 |
| full(預設) | quick + 沙箱 egress 註冊 + 全部 enabled action 執行 + `seed_demo_data` 冪等重跑 + test 事件 | **送審前必須**;S9 會檢查最後一次 e2e 是 full |

**送審門檻(平台 2026-07-28 更新)**:每支 enabled action 必須在最後 deploy 後
於沙箱**成功跑過一次**——執行紀錄由伺服器自動記,前端不可宣稱。這代表:
- `--expect allow_fail_actions` 只影響本地報告判讀,**擋不住平台端**;
  真跑不通的 action 只有兩條路:補真憑證(`--secrets-file`/`--egress-file`)重跑,
  或 manifest 設 `is_enabled:false` 停用後重新 push。
- e2e 報告的 `submit-gate` 條目會列出會被擋的 action,向用戶摘報時務必帶到。
- prod 部署改由 release tag 觸發,線上平台可能尚未套用此門檻——以實際送審回應為準。

判讀規則(寫進報告,向用戶摘報時逐條說明):
- **dummy 金鑰下的 pass 不等於完整可用性**:action 可能只走到早退路徑
  (如驗簽失敗即回)就回 2xx,深層邏輯並未執行。向用戶摘報時凡以 dummy 值
  通過的 action 都要標注「淺層通過」;正式上架品質以真值測試為準。
- 需要真實第三方連線的 action:第三方憑證歸 EgressService——用 `--egress-file`
  給 slug 的真實 base_url/auth_config;業務型金鑰(非 Authorization 用途)才走
  `--secrets-file`。都給不了就在 `--expect` 的 `allow_fail_actions` 宣告並說明。
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
  scan 複掃 → apply_decisions → audit_local → push → e2e --quick
里程碑 / 送審前:
  audit_local 全綠 → push(寫後回讀)→ e2e full(actions + 冪等 + test 事件)
  → 摘報 e2e_report + 安裝後設定清單 → 用戶 submit
```

## 錯誤處理

> 任何一步失敗 → **先完整讀出原始 error message**,再查
> `references/troubleshooting.md` 速查表,不要自行推測修法。

常見狀態碼語義:**401** 認證失效(PAT 撤銷/過期)|**403** 權限
(Developer 端 read_only / AI GO 端缺 builder.access,**不重試不繞路**)|
**409** slug 撞名或版本線衝突|**422** metadata/preflight 輸入不合法|
**400** 業務規則|**503** 沙箱 runner 未配置(平台設定,非程式問題)。

**Egress / 權限類錯誤 = 設定問題**:立刻停止改 code,把原始訊息轉給用戶,
引導到後台 `/dashboard/settings/integrations`(或請租戶管理員/平台 admin 處理)。

## 參考文件

| 檔案 | 內容 |
|------|------|
| `references/template-contract.md` | 模板目錄佈局、meta 契約、DSL 規則、新舊 API 對照 |
| `references/devportal-api.md` | Developer 平台 API 子集(權威:`GET /dev-docs/endpoints`) |
| `references/pollution-signals.md` | 租戶污染訊號與人工判讀要點 |
| `references/troubleshooting.md` | **出錯時**:症狀→成因→處置速查表 |
