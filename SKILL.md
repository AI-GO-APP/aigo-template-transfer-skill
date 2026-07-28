---
name: aigo-template-transfer
description: 把 AI GO custom app(線上 app 或 FDE repo)轉化為可上架的 template:抽取→去租戶化→Data Center schema→本地 audit→在 AI GO Developer 平台建立草稿並跑沙箱端到端測試→送審。每階段有硬閘,人工裁決不可代填。
---

# AI GO Custom App → Template 轉換 Skill

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

## Phase 0:前置檢查(每次開工先跑)

```bash
python scripts/devportal.py whoami
```

- 失敗或無 PAT → `python scripts/devportal.py setup` 依指引引導用戶:
  1. 登入/註冊 https://developer.ai-go.app(未登入先引導註冊)
  2. 設定頁 https://developer.ai-go.app/settings →「API Token(PAT)」→ 發行(只顯示一次)
  3. `python scripts/devportal.py set-pat` 貼入
- `level=read_only` → 告知用戶需請平台 admin 升級為 editor,**停在這裡**,不嘗試繞過。
- 來源側需要 AI GO 帳號(builder.access):`.env` 填 `AIGO_EMAIL`(密碼互動輸入,不落檔)
  或 `AIGO_TOKEN`。

## Phase 0.5:候選判定(S0,人工閘)

先盤點,再讓用戶拍板:

1. 檢視來源 app 的功能與規模(actions 數、頁面數、自建表)。
2. 對照既有模板是否重疊:`ai-go-templates/templates/` 與平台 `GET /live-templates`。
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

全數 PASS 才過。失敗項若需改 code:回 Phase 3 補裁決(`reset --from-stage S2` 後重跑),
不要手改。

## Phase 7:Developer 平台建草稿(S7)

```bash
python scripts/devportal.py push --slug <slug>
```

建模組(平台自動帶 1.0.0 draft)→ 推 metadata(含 data_center_schema)→ 推 files
(平台自動記 deploy 事件)→ 平台 preflight 必須 ok。

## Phase 8:沙箱端到端測試(S8)

```bash
python scripts/e2e_devportal.py --slug <slug> [--secrets-file s.json] [--expect e.json]
```

- 需要真實第三方憑證的 action:向用戶要 e2e 用測試值(`--secrets-file`),
  或在 `--expect` 的 `allow_fail_actions` 宣告並向用戶說明。
- runner 503 = 平台側未開 action runner,會記 SKIP;送審前向用戶明確標注此風險。
- 預設自動記 test 事件(滿足送審門檻);要走最真實的前端驗證改 `--no-event`,
  再開 `https://developer.ai-go.app/preview/<module_id>?v=<version_id>`(3 秒無錯自動記)。

## Phase 9:送審(S9,人工閘)

向用戶摘報 e2e_report.json 重點(特別是 SKIP/WARN 項),由用戶執行:

```bash
python scripts/devportal.py submit --slug <slug> --note "<給審核者的說明>"
```

## 疑難排解

- 「內容閘:雜湊不符」:有閘外變更。找出變更來源,`transfer_cli.py reset --from-stage <變更點>` 重跑。
- S7 409:slug 撞架上模板或他人模組 → 換 slug(回 S0 重新 init)。
- PAT 401:已撤銷/過期 → 重新發行 + `set-pat`。
- 平台 API 疑義:以 `GET /api/v1/dev-docs/endpoints` 自省為準(見 references/devportal-api.md)。
