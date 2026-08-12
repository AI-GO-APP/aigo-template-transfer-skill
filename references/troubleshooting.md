# 錯誤速查

> 任何一步失敗、或收到非預期狀態碼 → 先查本表,**不要自行推測修法**。
> 多數症狀有明確成因,猜測通常會改錯地方。
> 鐵律:**權限與設定問題改 code 改不掉**——立刻停手,把原始 error message 轉給用戶。

## 狀態碼語義分野

| 狀態碼 | 語義 | 典型處置 |
|---|---|---|
| 401 | 認證失效 | PAT 已撤銷/過期 → 重新發行 + `set-pat`;AIGO token → 快取自動換發,仍失敗檢查 `~/.aigo-transfer/.env` 帳密(必要時刪 `~/.aigo-transfer/token.json` 重登) |
| 403 | 權限不足 | 分兩種:Developer 端 `read_only`(請 admin 升 editor)/ AI GO 端缺 `builder.access`(請租戶管理員開通)。**不重試、不繞路** |
| 409 | 衝突或配額 | slug 撞架上模板或他人模組 → 換 slug 重新 init;版本線衝突 → 已有進行中版本,不要 POST /versions;自建表寫入 `unique_violation` → 該欄宣告了 unique,值重複(**這是預期行為**,見下表) |
| 422 | **送審擋門**(不是 metadata!) | 只有三種:preflight 有 fail(detail 帶完整 preflight)、送審時該版本無 deploy 紀錄、adopt 的架上 metadata 不合規。**PUT metadata 的驗證失敗一律是 400**——2026-08-12 實測確認 |
| 400 | 輸入不合法或業務規則拒絕 | metadata 全家(AI GO 型別契約、category、access_mode、tags 白名單、custom_objects_schema)都在這裡;檔案 base64/檔數上限亦是。讀 detail 照改,不要瞎猜 |
| 503 | 服務未配置 | 沙箱 action → 平台 `RUNNER_URL` 未設,記 SKIP 並向用戶標注;不是你的 code 問題 |

## 各階段症狀速查

| 症狀 | 成因 | 處置 |
|---|---|---|
| 更新 skill 後憑證/工作區不見了 | 0.6.1 以前把 `.env`、`.aigo/`、`work/` 放在 skill 目錄內,複製式安裝(`npx skills add`)更新會 `rm -rf` 整個目錄重鋪 | 0.6.2 起已搬到 `~/.aigo-transfer/`,不會再發生。已經被清掉的只能重設 PAT 與重跑轉換;git 安裝從未受影響 |
| 啟動時出現「[!] … 新舊兩份都存在」 | 舊資料搬遷時新位置已有同名檔案,腳本一律不覆蓋 | 實際生效的是 `~/.aigo-transfer/` 那份。比對後自行刪掉不要的舊檔——留在 skill 目錄裡的那份下次更新會被清掉 |
| 啟動時出現「[!] … 搬移失敗」 | 家目錄唯讀、跨磁碟或權限問題 | 舊路徑仍可用(有後備讀取),但仍在被清掉的風險內。手動把檔案搬到 `~/.aigo-transfer/`,或設 `AIGO_TRANSFER_HOME` 指到可寫位置 |
| 「階段閘:S_x 尚未通過」 | 跳關 | 依序補完前置階段;人工閘用 `transfer_cli.py gate` |
| 「內容閘:雜湊不符」 | template/ 有閘外變更 | 找出變更來源;合法變更 → `reset --from-stage <變更點>` 重跑;不明變更 → 先查是誰改的 |
| S1「尚未確認來源 app 的身分」 | 未過來源身分閘 | `acquire.py --list-apps` 找出 uuid → **由用戶**跑 `transfer_cli.py confirm-source`;AI 不得代按 |
| S1「來源身分不符」 | `--from-app` 給的不是用戶確認過的那支 | 核對 uuid;確實要換來源就重跑 `confirm-source` 重新確認 |
| S1 clone 失敗(private repo) | git 認證未設 | `gh auth login` / SSH key / credential helper;**不要把 token 寫進 URL**(會留在 shell 歷史) |
| S1 clone 失敗(找不到分支) | 預設分支不是要的那條 | `--ref <branch|tag>` 指定 |
| S1 偵測不到佈局 | B 層自開發佈局;或根本不是 custom app | `--vfs-subdir` 或 `--mapping` 檔;完全非 custom app(C 層,一般 web app)→ 排除,不硬轉 |
| S1 缺 SDK 檔 | 來源 repo 不完整 | 從 starter 模板補 canonical 三檔後 `reset --from-stage S1` |
| S3「找不到 old 字串」 | 前一筆裁決已改掉同段內容 | 正常;確認複掃結果收斂即可 |
| S3 blocker 不可 keep | 憑證/舊制 API/禁用 import | 只能 replace 或 delete_file;舊制 API 改寫對照見 template-contract.md |
| S4 403 | 資料中心存取權 | 見上表 403;本 skill 只讀不建表,不需要 system.admin |
| S6 DSL 驗證失敗 | 系統欄名/relation/成環 | 錯誤訊息含位置,對照 template-contract.md 修 dc_schema |
| S6 secrets 覆蓋失敗 | `ctx.secrets.get` 的 key 未宣告 | 補進 setup_schema(經 normalize_meta --setup-schema),不要刪程式碼裡的讀取 |
| S6「meta 尚未經用戶確認」 | 門面文案是人工閘 | 向用戶完整呈報 meta(含 long_description 全文)後,**由用戶**跑 `transfer_cli.py confirm-meta` |
| S6「meta 在用戶確認後又被改過」 | 確認後 meta 又變動(重跑 normalize_meta 或手改) | 重新呈報差異並請用戶重跑 `confirm-meta`;內容完全相同時腳本會自動沿用原確認 |
| S7 preflight fail | entry/imports/secrets/scopes/actions/manifest | 讀 issues 逐條修;bare import 只支援 5 套件,別加第三方前端依賴 |
| S7 tags 422 | tags 不在平台白名單 | `GET /refs/tags` 取合法值 |
| S7 寫後回讀不符 | 平台改寫/丟棄欄位 | 人工比對送出與回讀內容;確認平台版本行為後回報 |
| S7「引用宣告未經驗證」WARN | 平台部署沒有 `/refs/available-tables` | 非錯誤:該端點不是所有部署都有(權威清單 `GET /dev-docs/endpoints`)。宣告正確性改由 S8 引用表週期實打確認 |
| S8 引用表**全部** fail | 平台部署沒有 `/refs/tables/{t}/columns`(非模板宣告有誤) | 0.6.1 起自動改走 seed 週期;仍全 fail 才是宣告問題。先自行打 `GET /sandbox/v/{vid}/proxy/{vid}/{table}` 確認:200 = 表沒問題 |
| S8 引用表 WARN「seed 前的 list 失敗」 | 該表的 proxy list 回非 200,無法辨識自己 seed 的列 | 護欄擋住「刪光整張表」而已,不是模板問題。沙箱可能留有 1 列 seed 資料,跑 `tables-count` 確認並自行清 |
| S8 引用表 WARN「seed HTTP 5xx」 | 平台產樣本列時出錯(實測 `hr_employees`、`hr_payroll_runs`) | 非模板問題:該表已用 list+query 確認可解析,但**寫入路徑未驗**。摘報時要帶到。根因已查明並送修:種子資料的固定 id 跨版本相同、撞沙箱主鍵(urfit-tech/aigo-developer-platfom#63) |
| S8 自建表寫入 422「未宣告的欄位:['報單號', …]」但宣告明明是對的 | 送出的鍵是**顯示名**不是實體名——模板用 `f.physical_name \|\| f.display_name` 之類的執行期反查取欄位鍵,在該面取到 undefined 而退回顯示名。訊息指向 schema 宣告,但宣告完全正確,所以很難連起來 | 刪掉反查:新制的表/欄 key 就是實體名,靜態就知道(見 template-contract.md「自建表:實體名與唯一鍵」)。共用碼真的要讀 list_tables 就寫 `f.physical_name ?? f.key`——兩面鍵名不同 |
| S8 自建表寫入 409 `unique_violation` | 該欄宣告了 `"unique": true`,值與既有列重複 | **預期行為**,不是平台問題。正式環境是真 SQL UNIQUE(NULL 不佔用唯一性,但空字串 `''` 算一般值,兩列 `''` 照樣違反)。測試資料換一個值即可 |
| 引用表的布林欄在沙箱是 `true/false`、正式環境卻是 `"yes"/"no"` | 沙箱 fixture 是平台維護的近似值,曾與正式環境不一致(已知:`hr_leave_types.requires_allocation`) | 值型別一律以正式環境為準:`GET /proxy/{app_id}/{table}` 實讀一筆,或查 `ai-go/backend/app/models/`(該租戶無資料時仍有答案)。**不要**照沙箱的值改 app 的判斷式——那會在上線後恆為 false |
| 跑完 S8 發現沙箱引用表資料變了 | 平台 seed 預設 `replace=True`,呼叫當下就清光該表這一版的既有列 | **預期行為,不是 bug**。跑 S8 前若沙箱有要留的手動測試資料,先自行備份;或改用 `POST .../tables/{t}/rows` 重貼 |
| S8 action 全部 503 | runner 未配置 | 平台側設定;e2e 記 SKIP,送審前向用戶明確標注此風險 |
| S8 approval_status: pending | 租戶簽核流程攔截 | **非失敗、不可重試**(重試 = 重複建單);記 WARN 即可 |
| S8 action 需要真實憑證 | ADR 0010 之後憑證歸 `setup_schema`,action 自己帶;dummy 值打不通第三方 | `--secrets-file` 給真金鑰;`--egress-file` 只給該 slug 的真實 `base_url`。或 `--expect` 宣告 allow_fail 並向用戶說明 |
| S8 egress 註冊 400「auth_type 僅接受 'none'」 | `--egress-file` 裡填了 `auth_type`/`auth_config`——沙箱 egress 是 domain-only(ADR 0010),閘道不注入認證 | 從 egress 檔移除這兩個鍵,金鑰改走 `--secrets-file`(action 端自組 Authorization) |
| S9 被擋:e2e 是 quick | 送審要求 full(**本 skill 的要求**,平台已不強制) | 重跑 `e2e_devportal.py --slug <slug>`(不帶 --quick) |
| S9 422「這些 action 尚未成功執行過」 | 線上平台仍是 2026-07-28 的舊門檻(prod 由 release tag 觸發,可能落後 main) | 依訊息補跑:`--secrets-file` 給真憑證重跑 full;真跑不通的在 manifest 設 `is_enabled:false` 停用後重新 push |
| S9 422「尚未佈署」/ 佈署 0 次 | 該版本沒有 deploy 事件——`PUT files` 才會記,純 bump 曾經不記 | 平台 2026-08-04 起 bump 複製檔案會補記(`detail.source=bump`);線上若仍是舊版,重跑一次 `devportal.py push --slug <slug>` 即可 |
| preflight warn:egress 未宣告 | 程式碼用了 `ctx.http.call(slug)` 但 metadata 缺 `required_egress` | 重跑 `normalize_meta.py`(會自動從盤點補宣告)→ 重新 push |
| 沙箱寫入/測試 403 | read_only 帳號(2026-07-28 起沙箱寫入需 editor) | 請 admin 升級帳號 |
| 對外呼叫被擋(egress 未註冊) | 租戶未以同名 slug 註冊 EgressService | **停止改 code**;引導用戶到後台 `/dashboard/settings/integrations` 註冊 slug(只需 base_url) |
| 對外呼叫 401,但 EgressService 明明填了金鑰 | ADR 0010 domain-only:閘道**不再注入** service 上的憑證,`auth_type`/`auth_config` runtime 一律忽略。舊模板靠注入的寫法沙箱測得過、上線就 401 | 改成自帶:金鑰進 `setup_schema`,action `ctx.secrets.get(...)` 後組 `headers={"Authorization": ...}` 傳給 `ctx.http.call`(回 Phase 3 補裁決) |
| action 對外連線 timeout(~20s) | action 用 raw httpx/requests 直連——runner 是 default-deny egress | 改寫為 `ctx.http.call("<slug>", "<path>")`(回 Phase 3 補裁決);這是架構限制,重試無效 |

## 查不到怎麼辦

1. 完整讀出 API 回傳的 error message(原文,不要摘要後腦補)。
2. 對 Developer API 疑義:`GET /api/v1/dev-docs/endpoints` 自省權威清單。
3. 仍不明 → 把原始訊息與重現步驟轉給用戶,不要試錯式亂改。
