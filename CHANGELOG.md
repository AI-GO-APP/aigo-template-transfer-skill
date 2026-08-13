# Changelog

版本號採 [Semantic Versioning](https://semver.org/lang/zh-TW/)。
**每次改動 Skill 內容(SKILL.md / references / config / scripts)都要同步更新 `VERSION`**,
否則使用者端的更新檢查(`scripts/check_update.py`)不會提示。

## 0.7.3

安裝後設定清單只告訴租戶「加入網域」,但 `ctx.http.call` 是以 **slug** 解析服務的。

`build_post_install_checklist` 只渲染 `inventory["egress_domains"]`,**從來沒印過
`egress_slugs`**。租戶照著清單做,會建出一個名字不對的 EgressService,然後 action
依然連不出去——而錯誤訊息說的是「egress service 'openai' 未註冊」,對不上清單裡
那條「加入網域 api.openai.com」的指示,等於自己看自己的文件找不到答案。

更糟的是網域這份清單的來源不可靠:2026-08-12 改寫白老鼠時,`api.openai.com`
之所以還在清單裡,只是因為我在程式碼註解裡寫了那個 URL。把 URL 換成 path 常數
(這正是鐵律 6 要的寫法)之後,`egress_domains` 可能整個是空的,清單於是**連
一條 egress 指示都不會出現**——但模板照樣非註冊服務不可。

- 有 `egress_slugs` 時改印「**以完全相同的 slug 建立服務**」,並點明 slug 不符
  即視為未註冊;網域降為「供填 base_url 參考」
- 明講**金鑰不要填在服務上**(ADR 0010 domain-only,閘道不注入,填了不生效),
  金鑰歸安裝表單欄位
- 沒有 `ctx.http.call`、只有前端打外部 URL 時維持舊的「白名單」措辭
- 新增 2 例:slug 優先、以及只有網域時的退回措辭

## 0.7.2

egress slug 放在常數裡就盤點不到,`required_egress` 因此少宣告。

`_EGRESS_SLUG_RE` 只認第一個參數是**字串字面值**的寫法。把 slug 抽成模組級常數
——`OPENAI_EGRESS = "openai"` 然後 `ctx.http.call(OPENAI_EGRESS, OPENAI_PATH, ...)`
——是很自然的寫法,但盤點會完全漏掉,`normalize_meta` 於是不會補進 `required_egress`。

漏掉的後果不在轉換階段:平台 preflight 只給 warn、audit 全綠、S8 也照樣過,
但**租戶安裝時不會被提示授權該服務**,裝完 action 一律連不出去。錯誤浮現在
離部署最遠的地方,而且看起來像 app 壞了。

0.7.0 把 `ctx.http.call` 定為對外呼叫的唯一正解之後,這種寫法只會更多。
2026-08-12 改寫白老鼠的 `github_webhook.py` 時實際踩到。

- 新增 `_egress_slugs(text)`:字面值之外,再解析同檔案的模組級字串常數
  (`NAME = "literal"`)並比對 `ctx.http.call(NAME, ...)`
- **解不出來就不報**:`ctx.http.call(slug, ...)` 這種執行期決定的、以及跨檔 import
  的常數都不追。誤報會讓模板宣告一個不存在的服務,租戶被要求授權用不到的東西
  ——在這裡漏報比誤報安全
- `TestInventory` 新增 3 例(常數、字面值與常數混用、解不出來不得亂猜)

## 0.7.1

VERSION 檔帶 BOM 會讓**所有安裝者的自動更新從此靜靜地不再提示**。

2026-08-12 驗證 0.7.0 的更新通道時,用 PowerShell 的 `Set-Content -Encoding utf8`
造了一份假的舊安裝,`check_update.py --json` 回 `"local": "﻿0.6.4"`——BOM 沒被
`.strip()` 剝掉(它只處理空白)。`_parse_version` 對非數字段一律歸零,於是
`"﻿1"` 被判成 `0`:**`1.0.0` 變成 `(0,0,0)`,比 0.7.0 還舊,更新提示永遠不會出現。**

這次是測試腳本自己寫的 BOM(repo 的 VERSION 乾淨,遠端也是),但觸發條件一點都不
罕見:Windows PowerShell 的 `Set-Content -Encoding utf8` 與 `Out-File` **預設就寫 BOM**,
誰在 Windows 上 bump 一次 VERSION 就中。而失效方式是靜默的——沒有錯誤訊息,
只是從此再也不提示更新,連「漏報」都不會被發現。

- 新增 `_clean_version()`:`lstrip("﻿")` + 取第一行,本地讀檔改 `utf-8-sig`,
  遠端內容也過同一支(BOM 可能來自任何一邊)
- 遠端 VERSION 剝完是空字串時回 `unknown`,不再讓空值往下走
- 新增 `TestBomTolerance` 4 例,含「BOM 不得讓主版號歸零」這條斷言本身

### 0.7.0 更新通道實測(git 與 copy 兩條路)

- **git 安裝**:clone 到 44dde9a(0.6.4)→ `check_update.py --force` 正確報
  `0.6.4 → 0.7.0` 並帶 CHANGELOG 摘要 → `--apply` 跑 `git pull --ff-only` →
  VERSION 變 0.7.0、新檔到位 → 再檢查回 `current`。exit code 全程 0(SessionStart
  hook 不可阻斷)
- **複製式安裝**(無 `.git`):正確判為 `install_method: copy`,**不嘗試 pull**,
  回 `npx skills update aigo-template-transfer-skill` 交給使用者

## 0.7.0

同步 Developer 平台 `origin/main`(對到 2026-08-11,24c958a);上次同步是 2026-08-01。
**鐵律 6 的憑證歸屬反轉**,故走 minor 而非 patch。

### 已對正式平台實測(2026-08-12,developer.ai-go.app)

prod 的 `GET /dev-docs/endpoints` 共 89 支,已含 `slug-check`/`restore`/`ext/storage`
——**線上就是 main 的行為,沒有落後**。逐項實打:

| 主張 | 實測 |
|---|---|
| 沙箱 egress domain-only | 帶 `auth_type=bearer` → **400**(訊息逐字為平台的 domain-only 說明);只帶 `base_url` → **200** |
| metadata 型別閘 | `data_center_schema: []` → **400**「必須是物件(dict),收到 list:[]」 |
| 建置產物靜默丟棄 | 送 28 檔(含 1 個 `.pyc`)→ 200,**回讀只有 27 檔**;這正是 0.6.4 會爆的假失敗。先濾再送 27 檔 → 回讀 27,相符 |
| `assert_deployed` 放寬 | 全新版本、**0 筆 test 事件**、preflight ok → `POST submit` **200**(舊門檻會 422)。已立即 withdraw |
| `GET /modules/slug-check` | 200 → `{slug, valid, available, reason, checked_live}` |

驗證用的 scratch module 已 `DELETE` 並回讀確認 404;白老鼠的 metadata 逐欄比對與備份一致。

**實測揪出的文件錯誤:metadata 的驗證失敗是 400 不是 422。**
`api/modules.py` 的 `validate_metadata` ValueError → 400、`validate_tags_allowed` → 400;
422 在本平台只留給**送審擋門**(preflight 有 fail、送審時無 deploy 紀錄、adopt 的架上
metadata 不合規)。skill 的狀態碼表從 0.6.4 起就把 metadata 標在 422 那一行,查表會走錯行
——SKILL.md「錯誤處理」、troubleshooting 狀態碼表、devportal-api.md 三處同步更正。

### 反轉:憑證由 action 自帶,不再是「閘道注入」

v0.4.0 立的「憑證不可自帶 `Authorization`,金鑰歸租戶註冊的 EgressService、由閘道注入」
**已經是錯的**。AI GO ADR 0010(AI-GO#832)把 connector_proxy 改為 **domain-only**,
Developer 平台 2026-08-03 跟上(ai-go-developer `34b2a7d`):

- `dev_ctx._STRIPPED` 從「含 authorization」縮成 hop-by-hop only
  (`host`/`content-length`/`proxy-*`),與 `connector_proxy._sanitize_headers` 逐字同語意
- `_inject_auth` 注入路徑**兩邊都整支移除**;既有 service row 的 `auth_type`/`auth_config`
  於 runtime 一律忽略

照舊教義產出的模板,失效方式特別惡劣:**沙箱測得過、上線後 401**,而且錯誤浮現在
「租戶新增渠道」這個離部署最遠的地方(平台 commit 訊息點名 line-cs-manager 1.1.0
就是這樣)。反過來,自帶金鑰的模板(omni-cs-hub 1.1.0)先前是沙箱測不過。

新寫法:金鑰進 `setup_schema` → action `ctx.secrets.get(...)` → 自組
`headers={"Authorization": ...}` 傳給 `ctx.http.call`。EgressService 只剩 base_url 與政策。

- SKILL.md 鐵律 6 重寫,並明講舊教義是錯的(舊版 SKILL.md 可能還在別人的 context 裡)
- Phase 3 的 `ctx.http.call` 範例改為自帶憑證,加註位置參數順序
  `(service, path, method, body, headers, params)`——SDK 走 positional list 過 RPC,
  順序錯不報錯、只會把 body 塞進 headers
- pollution-signals:「自帶 Authorization」從**必裁決項**改為「靠閘道注入的舊寫法」才是
  必裁決項;`scan_rules.json` 的 `raw_http_outbound` suggestion 同步
- troubleshooting 拆成兩條:「egress 未註冊」與「填了金鑰卻 401」,後者指向改寫

### e2e:`--egress-file` 帶憑證會被平台 400,改為在門口擋掉

平台 `21a5d28` 對非 `none` 的 `auth_type` 直接 400、`auth_config` 強制清空。
`e2e_devportal.py` 先前照送這兩個鍵(`--egress-file` 的文件也明文教用戶填),
真填了就是 S8 hard_fail。

現在:body 只送 `base_url`/`is_active`/`allow_dynamic_host`/`timeout_ms`;egress 檔裡
還留著 `auth_type`/`auth_config` 時**在註冊前就 SystemExit**,訊息指向 `--secrets-file`。
刻意不靜靜丟掉——收下一份永遠不生效的憑證設定,等於讓用戶以為金鑰帶上了,
然後在沙箱綠燈、上線 401 的地方才發現(與平台選擇「擋在門口」同一個理由)。

### 送審門檻放寬,skill 的警告改為覆蓋率報告

平台 `71cc866`(2026-08-04)把 `assert_deployed_and_tested` 收回成 `assert_deployed`:
硬門檻只剩 preflight ok + 該版本至少一筆 deploy 事件。預覽測試與「每支 enabled action
至少一次 success」都改為非強制——2026-07-28 那版加嚴在實務上把送審卡死在測試儀式
(bump 不改碼也得逐支重跑)。

skill 的 `submit-gate` 只是 warn,不會擋,但訊息說「送審會被平台擋下……或在 manifest 設
`is_enabled:false` 停用」——那是**假警報**,會逼用戶去停用其實可以送審的 action。

- phase 名 `submit-gate` → `action-coverage`、`submit-gate-events` →
  `action-coverage-events`、`submit-gate-preview` → `preview-coverage`
- 語氣改為「等於沒驗過就要上架——平台不擋了,所以摘報時要逐支點名並說明風險」。
  **門檻放寬不等於品質放寬**:這件事改由本 skill 的 S9 人工閘把關
- `devportal.py events` 把輸出拆成「送審硬門檻」與「覆蓋率(非門檻)」兩段
- troubleshooting 的 S9 422 條目改標為「線上平台仍是舊門檻」(prod 由 release tag
  觸發,可能落後 main),另補「佈署 0 次」條目——平台 `b7eab17` 起 bump 複製檔案會
  補記 deploy 事件(`detail.source=bump`)

### 其他平台同步

- **建置產物**(平台 `d44d0ca`):`collect_files` 排除 `__pycache__/`、`*.pyc`/`*.pyo`、
  `.DS_Store`、`Thumbs.db`。平台端是**靜默丟棄**,而 push 的寫後回讀拿檔數比對——
  不先濾就是假失敗。判定函式 `common.is_build_artifact()`,清單照平台的保守版
  (該規則來自事故:`.pyc` 進了版本檔案,AI GO 讀取端硬解 UTF-8 失敗,租戶建 App 500)
- **AI GO 型別契約**(平台 `b7c985b`):`normalize_meta.aigo_type_problems()` 在 S6 就驗
  容器型別與 `tags` 每一項是字串,`devportal.build_metadata` 在 S7 再驗一次
  (pull/adopt 進來的 meta 沒走過 normalize_meta)。擋的是「Developer 端全綠、按下發布
  才 422」——那一刻版本已 submitted、不能再編輯。實例:`data_center_schema: []`
  (零自建表的模板很自然會這樣寫,因為 `data_references_schema` 就是陣列)
- **`unpublished` 狀態**(平台 `c47b3a5`):模組狀態多一個值,下架不再落回 `draft`,
  且全部版本轉 `superseded`;新增 `POST /modules/{id}/restore`(→ `draft`,**不會復架**)。
  SKILL.md Phase 7 與 devportal-api.md 記入,並點明 `withdraw` 與「下架」是兩回事
- **沙箱 `/ext/storage/*`**(平台 `d3ffe1f`、`d5d76f0`):upload/url/list/delete 四支補齊,
  external 模板的檔案上傳週期現在在沙箱跑得完(先前整條路徑一步都測不到,而且
  前端零網路請求、按鈕沒 disabled,看起來像 app 壞了)。已知偏差:`/url` 的 `url` 恆為
  `None`(沒有位元組可簽);`list` 是單層不遞迴
- **`GET /modules/slug-check`**(平台 `5ffb001`)、模組/版本刪除的三道限制
  (平台 `caf4f1c`:發布過一律 409、admin 無後門)寫入 devportal-api.md
- devportal-api.md 的基準日改標為「對到 origin/main 2026-08-11」

## 0.6.4

修正「任何帶自建表的模板,S8 必然 hard_fail」——e2e 打的是已退場的端點面。

### 成因:自建表那一面的路徑在平台端整組換掉了

不是 0.3.4 那種「餵錯面」(把自建表名餵給 `/proxy`),這次是**這一面本身被替換**。
ai-go-developer `backend/app/api/sandbox.py` 的 `_data_center_router` 檔頭寫明:
舊的 `/data/objects/{slug}/records` 已隨 AI GO 退場,「留著只會讓用舊面的模組在沙箱
測得過、上架後打不到」。現行契約:

    GET|POST    /sandbox/v/{vid}/data-center/tables/{table}/records
    PATCH|DEL   /sandbox/v/{vid}/data-center/tables/{table}/records/{row_id}
    GET         /sandbox/v/{vid}/data-center/tables

且 update/delete **要帶表名**——舊面是以 record id 全域反查,這是簽章層的差異,
不只是路徑字串換掉。external 走 `ext/data-center` 前綴。

前三批模板剛好都零自建表,所以這條路徑到現在才第一次被踩到;症狀是
`[FAIL] crud:自建表 tbl:insert HTTP 404:{'detail': 'Not Found'}`,而
`GET /data-center/tables` 回 200 且列得出該表——宣告是對的,面是錯的。

### 修正

- `devportal_paths`:新增 `_dc_prefix()` 統一 internal / external 前綴;
  `data_records()` 改走新面;`data_record()` 簽章加 `object_key`;
  新增 `data_tables()`(列出自建表結構,宣告了但還沒資料的表也會列)
- `e2e_devportal` 呼叫端跟著帶 `tkey`(預設引數綁定,避免 late binding)
- `references/devportal-api.md`、`SKILL.md`、各處檔頭註解一併改掉舊面
  ——文件留著舊路徑,等於繼續教人寫上架後打不到的碼
- 回歸護欄 `test_retired_object_surface_is_gone`:任何自建表路徑都不該再出現
  `/data/objects/` 或 `/data/records/`

平台是單一部署(`DEVPORTAL_DEFAULT_API` → developer.ai-go.app),舊面在平台端
已無對應 route,故直接切換、不做兩面偵測。與 0.6.1 的 `/refs` 降級不同:那支是
端點被刻意移除且無替代品才要降級,這支有明確的替代面。

## 0.6.3

補上自建表的三條契約細節。三條都是實際轉換時踩到、且**症狀與成因對不起來**的類型:
錯誤訊息指向的地方是對的,真正的成因在別處。

### 欄位的 key 就是實體名——執行期反查一律刪掉

`template-contract.md` 原本只寫了「表名對照 helper 必須刪除」,漏了欄位那一半。安裝時
AI GO 直接拿宣告的 key 當實體名(`template_install.py`:表 `physical_name=table.key`、
欄 `physical_name=f.key`),換租戶也不變。從 `custom_objects` 時代帶過來的
`f.physical_name || f.display_name` 反查因此是多餘的,而且會把自己綁在 `list_tables`
的回應形狀上。

失敗長相:寫入被擋成「未宣告的欄位:['報單號', …]」,但 schema 宣告完全正確——送出的
是顯示名,因為反查取到 undefined 退回了顯示名。

### `list_tables` 兩面的實體名鍵不同名

`GET /data-center/tables` 回 `physical_name`(沒有 `key`),`ctx.db.list_tables()` 回
`key`(沒有 `physical_name`)。這是 AI GO 兩個各自穩定的契約,不是筆誤。共用碼要兩邊都
跑就自己收斂:`f.physical_name ?? f.key`。

### unique 是真的 SQL UNIQUE,違反是 409

欄位級 `CONSTRAINT ... UNIQUE`,不是應用層檢查也不是 partial index:NULL 不佔用唯一性,
但空字串 `''` 是一般值、兩列 `''` 照樣違反;違反回 409 `unique_violation`(422 是輸入
不合法類,兩者不同碼)。

### 引用表的值型別以正式環境為準,不可從沙箱 fixture 反推

沙箱 fixture 是平台維護的近似值,與正式環境有過不一致的前例
(`hr_leave_types.requires_allocation` 正式是 `"yes"`/`"no"` 字串,沙箱曾給 bool)。
兩個方向都很安靜:照正式環境寫在沙箱測不到該分支,照沙箱寫則上線後恆 false。
查法:`GET /proxy/{app_id}/{table}` 實讀一筆,或查 `ai-go/backend/app/models/`
(該租戶剛好無資料時仍有答案)。

平台側對應的修正:urfit-tech/aigo-developer-platfom#73(fixture 型別)、
#75(沙箱補驗 unique)、#76(沙箱兩面各自對齊實體名鍵)。

## 0.6.2

修正「更新或重裝 skill 會清掉用戶憑證與轉換進度」的資料遺失問題。

### 成因:使用者資料放在 skill 目錄內,而複製式安裝的更新會清空該目錄

`.env`(PAT + AI GO 帳密)、`.aigo/token.json`、`work/<slug>/`(抽取產物、
`decisions.json`、狀態機)原本都掛在 `common.REPO_ROOT` 底下,也就是 skill 目錄裡。

- **git 安裝**:`git pull --ff-only` 不碰未追蹤檔案,這些檔案安全——原本的行為沒問題。
- **複製式安裝**(`npx skills add` / `npx skills update`):`skills` CLI 的
  `update` 會轉呼叫 `add`,而 `installer.ts` 在複製前先跑
  `cleanAndCreateDirectory()` → `rm(path, { recursive: true, force: true })`。
  整個 skill 目錄砍掉重鋪,沒有任何 backup 或 preserve 邏輯,
  三類資料**全部無聲消失**。掉 `work/` 比掉 `.env` 更痛:那是全部人工閘裁決紀錄,
  重建要用戶把 S0–S9 的確認再走一遍。

README 原本寫「任一情況都不會覆寫你的本地修改」,對複製式安裝是錯的,一併更正。

### 修正:使用者資料搬到 `~/.aigo-transfer/`

`common.py` 新增 `USER_DIR`(預設 `~/.aigo-transfer/`,可用 `AIGO_TRANSFER_HOME`
覆寫),`ENV_FILE` / `WORK_ROOT` / `TOKEN_CACHE_FILE` 全部改掛在它底下——
與 `check_update.py` 的節流狀態同一個家目錄。兩種安裝法共用同一條路徑規則,
不因安裝方式分岔。skill 目錄從此只剩「更新時本來就該被替換」的內容
(`config/`、`vendor/`、`references/`、`scripts/`)。

新增 `common.bootstrap()`(UTF-8 輸出 + 備妥資料目錄 + 搬遷舊資料),
取代各 CLI `main()` 開頭的 `common.utf8_stdout()`,10 支腳本統一入口。

### 舊版自動搬遷

首次執行任何腳本時把舊的 `.env`、`.aigo/token.json`、`work/<slug>/` 搬到新家,
搬遷紀錄印在 **stderr**(多支腳本的 stdout 是機器可讀 JSON,不能污染)。

- 冪等:搬完舊路徑不存在,再跑是零成本的 `exists()` 檢查。
- **永不覆蓋、永不刪除**:新舊同名時兩份都留著,只印衝突提示讓用戶自己決定。
- 搬移失敗(唯讀家目錄、跨磁碟)只回報不拋出;`load_env()` 與 `work_dir()`
  保留讀取舊位置的後備路徑,進行中的轉換不會憑空消失。

`.env` 寫入改走 `common.write_env()`,會建父目錄並盡量 chmod 600。

### 驗證

新增 `tests/test_user_data_dir.py`(19 例,全部把新舊路徑關進 tmpdir,
避免測試去搬開發者本機真實的 `work/`)。另在拋棄式副本上實跑:
造舊資料 → 跑 CLI 確認搬遷 → `rm -rf` 整個 skill 目錄重鋪 → 憑證與工作區都還在。

## 0.6.1

修正「平台沒有某支 `/refs` 端點」時被誤判成模板宣告錯誤的兩處問題。
實測環境:developer.ai-go.app,12 支純 Data Reference 模板、71 張引用表。
該部署的 `GET /dev-docs/endpoints` 底下 `/refs/*` 只有 `/refs/seed-tables` 與 `/refs/tags`。

### 修正:S8 引用表週期在缺 `/refs/tables/{t}/columns` 時全數 fail

`e2e_devportal.py` 取欄位型別是為了組樣本列;該端點 404 時原本直接判
「AI GO 無此表或不可引用」,於是**每一張**引用表都 fail、S8 不可能過——
但表其實好好的(`GET /sandbox/v/{vid}/proxy/{vid}/{table}` 回 200)。

改為 404 時走 seed 週期:`POST /sandbox/v/{vid}/tables/{t}/seed` 讓平台自己產生
合法樣本列(平台知道 schema,免去照型別組樣本),週期為
seed(代 insert)→ list → query → update → delete,涵蓋面與原 crud_cycle 相同。
只刪自己 seed 出來的列(seed 前後 id 差集),不動既有沙箱資料;
表真的不存在時 seed 回 4xx,鑑別力與原本的 columns 查詢一致。

seed 本身回 5xx 時再降一級:實測 `hr_employees`、`hr_payroll_runs` 的
`POST /sandbox/v/{vid}/tables/{t}/seed` 回 500,但同一張表的 proxy list/query 都是 200——
平台產樣本列的問題,判成模板宣告錯誤會冤枉模板。改為唯讀驗證(list + query)並記 **WARN**,
報告裡明寫「寫入路徑未驗」;list/query 也掛才判 fail。
seed 回 4xx 仍是 hard fail——那是真的沒宣告或不可引用(平台的 404 訊息本身就說得很清楚)。

### 修正:`push` 在略過引用前置檢查後仍印「引用宣告已驗證」

`[OK] 引用宣告已驗證(N 張 AI GO 表)` 原本在 `if/else` 之外無條件執行,
`/refs/available-tables` 404 走 WARN 分支時照樣印——讀起來像 N 張表都對過了,
實際上一張都沒驗。已移進 else 分支,WARN 文案改為明講「引用宣告**未經驗證**」
並指出驗證改由 S8 承擔。

註:`/refs/seed-tables` 不能拿來當可引用表白名單——實測 `sale_order_lines`、
`delivery_carriers`、`product_templates` 等表不在該清單內,但 proxy 與 seed 都正常。

### seed 週期的護欄(審查後補)

- **before 快照不可信時不准刪。** seed 前的 list 若回非 200(`http_call` 對非 2xx
  不拋錯,5xx/429 會安靜地走過去),id 差集就等於整張表,原本會把**既有沙箱資料全刪光**。
  改為另存 `before_ok` 旗標,拿不到可信快照就記 WARN 並保留 seed 出來的那列。
- **沒有 id 的列不算自己的。** 舊寫法 `r.get("id") not in before_ids` 會把不帶 id 的列
  收進待刪清單,`r["id"]` 隨即 KeyError——整支 e2e 中斷而不是記 fail。
- 差集判定抽成 `devportal_paths.row_ids/is_row_list/new_rows/updatable_field` 四支純函式
  (該模組本來就「純函式、不做 I/O,可單元測試」),補 6 個單元測試。
- WARN 文案補上「沙箱可能留有 1 列 seed 資料」——`crud_cycle` 的契約是不留髒資料,
  降級路徑留了就要講。
- **更正一個先前的說法**:seed 週期不等於「不動既有沙箱資料」。平台的 seed 預設
  `replace=True`(`ctx_core.sandbox.seed` → `_replace_all`),呼叫當下該表在這一版的
  既有列就被清光了;差集只保證不會再多刪別的。**跑過 S8 的引用表 = 該表沙箱資料被重種**,
  摘報時要向用戶講明。

### `push` 的欄位驗證同款誤報

`available-tables` 有、但 `GET /refs/tables/{t}/columns` 讀不到時,原本靜靜 `continue`
再印「引用宣告已驗證」——跟上面修的是同一種誤報,只是低一層。改為分流文案:
表名已驗、欄位未驗的張數與表名都列出來。

## 0.6.0

補上三處「錯了也不會有錯誤訊息」的缺口:抽錯 app、憑證問題延到 S1 才爆、
AI 自行拍板模板門面文案。外加 repo URL 直接當來源。

### 新增:來源側預檢 `aigo_client.py whoami`

Phase 0 先前只驗 Developer PAT,來源側(AI GO)憑證要拖到 S1 抽取到一半才爆,
錯誤還混在抽取流程裡。新增 `GET /auth/me` 預檢,順帶檢查 `builder.access`——
判定對齊平台 `require_permission`:`system.admin` 是萬能鑰匙,不可誤判成無權限。

### 新增:來源 app 身分閘(S1 前置,人工)

app uuid 打錯**不會 404、不會有任何警訊**,只會安靜地把別支 app 的內容做成模板。

- `acquire.py --list-apps`:列租戶下可見的 custom app(slug/status/更新時間/uuid),
  不進行抽取,純粹是找 uuid 用。
- `transfer_cli.py confirm-source --slug <slug> --app <uuid_or_slug>`:對著平台**實際回傳**
  的名稱/slug/uuid/檔數/action 列表確認,互動輸入 yes 才寫 `decided_by: "user"`。
- `acquire.py --from-app` 先驗這道裁決存在(不必連線就能擋),再把抓回來的 app id
  與用戶確認過的比對,不符即停。身分沒確認前不會動到既有的 `template/`。

### 新增:repo URL 直接當來源

`--from-repo` 現在同時吃本地路徑與 URL(https / ssh / scp 形式),URL 走
`git clone --depth 1`(可 `--ref <branch|tag>`)到 `work/<slug>/src_repo/`,
狀態機記下 commit 短碼。認證交給 git 本身;URL 若含 userinfo,輸出、錯誤訊息與
狀態檔一律遮掉,避免 token 隨 log 外流。找不到 git、clone 失敗、逾時各有明確處置指引。

> 範圍不變(鐵律 5):只吃 custom app 形狀的 repo。一般 web app clone 得下來也過不了
> 形狀檢查——那是重寫,不是轉換。

### 新增:meta 人工閘(S6 前置)

name / description / category / tags / long_description 是上架後第三方唯一看得到的門面,
先前全由 AI 以 CLI 參數填,decisions.json 不留任何用戶確認紀錄。

- `normalize_meta.py` 寫檔後把內容登記為 `decided_by: "proposed"`;
  內容與既有用戶確認**逐位元組相同**時沿用原確認(同參數重跑不必重按)。
- `transfer_cli.py confirm-meta`:呈報全部欄位與 long_description 全文後互動確認。
- `audit_local.py` 新增「meta 人工閘」項:未確認、或確認後又被改過(雜湊不符)都擋下 S6,
  連帶擋住 S7 push。

### 其他

- 人工閘統一走 `transfer_cli.confirm()`:非互動環境讀到 EOF 回明確的 `[ABORT]`
  訊息(「此步驟必須由用戶親自執行」),不再拋 traceback 讓人誤以為程式壞了。
- 新增 23 例測試(URL 判定與憑證遮罩、真實 clone 與失敗路徑、身分閘四種情境、
  builder.access 判定含 system.admin、meta 閘六種情境)。

## 0.5.1

### 修正:e2e 表 CRUD 打錯端點面(帶自建表的模板 S8 必然失敗)

平台的資料面有兩組:`data_center_schema` 宣告的**自建表**走 data_table SDK 面
(`/data/objects/{key}/records`),`data_references_schema` 宣告的**引用表**走
proxy SDK 面(`/proxy/...`,平台端有 `assert_table` 硬驗 AI GO 快照)。

0.3.4 以前的 `e2e_devportal.py` Phase 3 把 `data_center_schema` 的表名餵給
`/proxy`,一律回 404「AI GO 無此表」→ `hard_fail` → **任何帶自建表的模板 S8 都過不了**,
而真正該測的 `/data/objects/` 從沒被呼叫過;`data_references_schema` 宣告的表則
完全沒被 CRUD 測到。已於正式平台實測復現與修復。

- 新增 `scripts/devportal_paths.py`:兩個面的路徑組裝與樣本列產生,純函式、有單元測試。
- Phase 3 拆成 3a 自建表 / 3b 引用表,各自打正確端點。
- CRUD 由 `insert+list` 加深為 `insert→list→(query)→update→delete`,
  並刪掉自己插入的列,不再留測試髒資料。
- 引用表的樣本列改依 `GET /refs/tables/{t}/columns` 的真實欄位型別產生
  (只填 NOT NULL 非系統欄,跳過 UUID 外鍵)。

### 修正:submit 成功之後才炸的 TypeError

`common.mark_stage()` 的 `status` 是位置參數,`cmd_submit` 又從 `**extra` 傳同名鍵
→ `TypeError`。發生在**送審已經成功之後**,用戶只看到 traceback,會誤以為沒送出去
(實際上已進審核佇列)。改名為 `review_status`。

### 新增:補上會擋住真實工作流的端點

| 指令 | 端點 | 先前的處境 |
|---|---|---|
| `devportal.py bump` | `POST /modules/{mid}/versions` | 已發布模組要出下一版無路可走,只能叫用戶回 Web UI |
| `devportal.py withdraw` | `POST .../withdraw` | 錯誤訊息叫用戶「先 withdraw」,但 skill 沒實作 |
| `devportal.py events` | `GET .../events` | 只 POST 不讀,送審門檻只能靠本地推算 |
| `devportal.py pull` | `GET .../files/content` | 無法取回平台上的內容(ai-go-templates 已關閉後尤其要緊) |
| `devportal.py live-templates` | `GET /live-templates` | SKILL.md 叫 agent 看,但沒有腳本 |
| `devportal.py adopt` | `POST /live-templates/{slug}/adopt` | 完全沒提;**不可逆**,故帶人工確認閘 |

- `push` 前置驗證 `data_references_schema`(`GET /refs/available-tables` +
  `.../columns`):引用不存在的表/欄位直接擋下,不必等推完檔才被 preflight fail。
- e2e 的 `submit-gate` 改為跟伺服器對帳(讀事件、比對最後一次 deploy 之後的
  `detail.status==success`),取代原本用本地報告推算的作法。
- `bump` 會重置 S8/S9——新版本沒測過,舊綠燈不可沿用。
- 修正 `GET /live-templates` 的回應解析:形狀是 `{templates: [...], source}`
  而非裸陣列,可否接管以 `can_adopt` 為準(對齊 0.3.3 讀錯 `/refs/tags` 回應鍵的教訓)。

## 0.5.0

更新檢查機制與 aigo-app-builder-skill 對齊(使用者持續拿到最新版的保證機制):

- **修正:離線會燒掉節流。** 舊版在抓遠端**之前**就寫 `last_check`,使用者斷網一次
  就要等 24 小時才會再檢查。改為**抓取成功才記節流**,離線時下次仍會嘗試。
- **修正:`--json` 在已是最新/離線時完全不輸出**,機器可讀模式形同失效。改為一律輸出,
  含 `status`(`skipped`/`unknown`/`current`/`outdated`)與版本資訊。
- **修正:`--apply` 無逾時與失敗判讀。** 補 60 秒逾時、`returncode` 檢查、
  分岔/未提交修改的明確訊息;非 git(skills CLI 複製)安裝改回報「無法就地 pull」
  而不是靜默無事。
- **新增 Codex CLI SessionStart hook 範本**(`resources/hooks/codex.config.example.toml`),
  與既有 Claude Code 範本並列;README 改寫「保持更新」章節說明兩種安裝路徑與時序差異
  (hook 在 Skill 載入前跑,Phase -1 在載入後跑、更新後需重讀 SKILL.md)。
- 重構為 `check()` 回傳結構化結果(對齊 builder 的 status 語義),行為可測。
- 新增 `tests/test_check_update.py`(21 例):版號比較與 pre-release 排序、
  CHANGELOG 區段擷取、節流/離線/損毀狀態檔、更新指令分流、repo 指向自我檢查
  (vendor 自 builder 時最易漏改 REPO 常數)。
  含一條回歸鎖:遠端拿到非版號字串(抓到 HTML/404 頁)一律靜默,不對使用者誤報更新。

## 0.4.0

- **鐵律 6 反轉:對外呼叫回到 `ctx.http.call` 閘道,不是 raw httpx。** 原規則
  (0.1.x 起)依據「builder skill v1.1.0 移除 `ctx.http.call` 記述」推論該路徑已廢,
  但那是**另一份 skill 的文件改動**,不是平台能力下架。實測(2026-07-28,
  Developer 平台 prod 沙箱):
  - `ctx.http.call("openai", ...)` 成功回應 3/3(aigo-finance-os / -management-core / -people-os)
  - raw `httpx.get(...)` **20 秒 timeout**——runner pod 是 default-deny egress
    (ADR-0003:SG 只放行 ctx-only service),連線被黑洞
  raw httpx 產出的模板因此**測不過沙箱**,而送審門檻要求每支 enabled action 至少
  一次 success,等於卡死在 S7。
- **新增:憑證不可自帶 `Authorization` header。** 即使用了 `ctx.http.call`,自組
  `headers={"Authorization": ...}` 也會被剝掉(AI GO `connector_proxy._sanitize_headers`、
  Developer 平台 `dev_ctx._STRIPPED` 兩邊都剝),實測回 **401**。金鑰歸 EgressService,
  action 不碰,連帶不需要為它開 `setup_schema` 欄位。此缺陷已實際流出:
  上述 3 支模板皆為此寫法,沙箱與正式環境都無法認證。
- `config/scan_rules.json`:`legacy_ctx_http`(把 `ctx.http.call` 當污染)→
  `raw_http_outbound`(把 `import httpx/requests/urllib.request` 當污染),
  suggestion 改為 `ctx.http.call` + `required_egress` + 不自帶憑證。
- `SKILL.md` Phase 3 範例、`references/pollution-signals.md` 同步改寫;
  「安裝後設定清單」的 egress 條目改以 slug 為主、網域為輔。
- 審查補齊(PR #1 review):`hardcoded_url` suggestion、troubleshooting 三列
  (egress 401/timeout/真憑證歸 EgressService)、SKILL Phase 8 判讀、
  template-contract 的 required_egress 敘述——清除殘留的舊 httpx 教義;
  新增 `raw_http_outbound` 掃描規則測試 ×2。


## 0.3.4

- 對照平台 PR #35–#39:契約零變動,skill 程式無需更新。
  - #38(沙箱 ctx.log shim)暴露判讀盲點:dummy 金鑰下 action 的 pass 可能只覆蓋
    早退路徑——SKILL.md e2e 判讀規則新增「淺層通過」標注要求。
  - #39 修正 preflight 對 data_center_schema.tables(陣列)的解析,帶 DSL 表的
    模板現在可正常過 preflight(本 skill 產出的一直是正式陣列形狀,不受影響)。
  - #36/#37:平台 API 手冊的「既有應用轉模組」入口正式指向本 skill repo。

## 0.3.3

- 對照 developer 平台 PR #33(admin tag 治理):修正 push 前置 tags 驗證解析
  `GET /refs/tags` 的回應鍵(`tags`,先前誤讀 `items` 會把合法 tag 全判不合法);
  錯誤訊息補充 tag 候選集規則(registry ∪ 架上 ∪ 本地,新 tag 需 admin 於標籤總覽建立)。

## 0.3.2

- ai-go-templates 已棄用:移除 SKILL.md 候選判定與 README 相關系統中指向該 repo 的
  操作性引用(候選重疊判定改以平台 `GET /live-templates` 為唯一權威);
  vendor 檔頭與 PLAN/CHANGELOG 的歷史出處註記保留。

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
