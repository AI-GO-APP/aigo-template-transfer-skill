# Changelog

版本號採 [Semantic Versioning](https://semver.org/lang/zh-TW/)。
**每次改動 Skill 內容(SKILL.md / references / config / scripts)都要同步更新 `VERSION`**,
否則使用者端的更新檢查(`scripts/check_update.py`)不會提示。

## 0.3.1

白老鼠實測(FDE-URfit-FDE-task-manager,S0→S8 於正式平台全程通過)中的修正:

- `normalize_meta.py` 新增 `--data-references <json>`:SaaS 表(Data Reference 軌)
  的模板必須宣告 `data_references_schema`,平台 preflight 會驗表與欄位存在。
- `acquire.py` 目錄清理改 `_clear_dir`(只清內容+重試,不刪目錄本體):
  Windows 索引器/防毒短暫持有目錄 handle 時 rmtree 會 WinError 32。

已知待補(記錄於 session):audit 失敗項(emoji/devDependencies)目前走「回源修正
+ reset 重跑」,尚無 decisions 軌;掃描器 app_domain 規則吃不到大寫常數
(`export const APP_DOMAIN = ...`)。

## 0.3.0

同步 ai-go-developer 平台 2026-07-28 合入 main 的變更(PR #20–#32):

- **送審門檻更新**:每支 enabled action 必須在最後 deploy 後於沙箱成功跑過
  (伺服器自動記 test 事件,前端不可宣稱)。e2e full 檔新增 `submit-gate` 試算,
  列出會被平台擋下的 action;`--expect allow_fail` 明確標注擋不住平台端。
- **`required_egress` 宣告鏈**:inventory 新增 `egress_slugs` 盤點
  (`ctx.http.call/fetch` 的 service slug);normalize_meta 自動宣告進 metadata;
  devportal push 白名單加入該欄位;e2e 新增沙箱 egress 註冊 phase(`--egress-file`,
  支援 `allow_dynamic_host`)。
- **`actions/_shared/` 共用模組豁免**(issue #497):audit 不再要求 `execute(ctx)`
  與 sync_ 慣例(硬編碼金鑰/禁止 import 檢查仍適用)。
- **權威 DSL 驗證改首選 ai-go-developer 的 ctx-core**(`ctx_core.template_dsl`,
  零相依;與平台「metadata 存檔即驗」同一套),ai-go 後端降為次選。
- e2e 跳過 manifest `is_enabled:false` 的 action(沙箱執行會 409,且不列入送審門檻)。
- 文件同步:devportal-api.md(送審門檻、required_egress、_shared、沙箱自動記錄、
  editor 權限、release-tag 部署節奏)、template-contract.md、troubleshooting.md 新增三條。

## 0.2.0

對齊 aigo-app-builder-skill v1.1.1 的結構與嚴謹機制:

### 內容修正
- **移除 `ctx.http.call` 的遷移建議**(builder v1.1.0 已移除該路徑):對外呼叫一律
  改寫為 `import httpx` + `ctx.secrets.get()` + 強制 `timeout=`;新增 `legacy_ctx_http`
  掃描規則(high)。網域改記入「安裝後設定清單」(Egress 白名單)。
- **AI GO 憑證對齊 builder 紀律**:新增 `scripts/aigo_client.py`(token 快取 →
  refresh 換發 → .env 帳密),移除互動式密碼輸入;agent 不代填、不在對話中要密碼。
- **S1 盤點擴充**:webhook 宣告、對外網域、app 排程(`GET /app-crons`)、legacy 痕跡
  → `inventory.json`;normalize_meta 自動生成「安裝後設定」清單併入 long_description。
- **dc_extract 403 分流**:權限問題明確指引(不重試、不繞路),對齊 builder 的降級慣例。

### 可靠性
- **寫後回讀(★ 二次 GET 驗證)**:push 後回讀 metadata 關鍵欄位與檔數;
  submit 後回讀版本狀態 == submitted。
- **e2e 分級**:`--quick`(preflight+secrets+CRUD)/ full(預設,含全部 action +
  冪等重跑 + test 事件);S9 送審要求最後一次 e2e 為 full。
- **簽核攔截語義**:e2e 中 `approval_status: pending` 記 WARN 不記 FAIL,且不重試。

### 治理
- 新增 `VERSION` / `CHANGELOG.md` / `scripts/check_update.py`(零相依、永不阻斷、
  24h 節流、不自動覆寫)與 SessionStart hook 範例(`resources/hooks/`)。
- 新增 `references/troubleshooting.md` 錯誤速查表;SKILL.md 增 Phase -1 自我更新檢查、
  錯誤處理章節(狀態碼語義、「設定問題不要改 code」)。

## 0.1.0

- 初版:S0–S9 狀態機 + 內容雜湊閘、污染掃描與逐條裁決、data_center_schema 抽取與驗證、
  本地 audit 11 閘、Developer 平台建草稿 + 沙箱 e2e + 送審。
