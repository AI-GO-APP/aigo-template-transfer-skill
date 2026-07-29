# aigo-template-transfer-skill

把 AI GO custom app(線上 app 或 FDE repo)轉化為可上架的 template,
並直接在 [AI GO Developer 平台](https://developer.ai-go.app) 建立 dev_module 草稿、
跑沙箱端到端測試、送審。

## 特性

- **嚴謹的每階段判斷**:S0–S9 十階段狀態機,腳本強制順序;內容雜湊閘擋下任何閘外變更;
  人工裁決(候選判定、逐條去租戶化、挑表、demo 資料、送審)必須由用戶親自確認,AI 不得代填。
- **可重現**:所有修改由 decisions.json 驅動、`apply_decisions.py` 套用——同一份裁決重跑得到同一份模板。
- **相容標準 VFS 與自開發佈局**:A 層(標準形)自動偵測;B 層(`app/`、`vfs/`、`aigo/`、
  `aigo-app/`、多 app)依 layout profiles;完全自訂佈局用 mapping 檔。
- **一律新制**:只產 `data_center_schema`(version=1),舊制 CustomObject 不讀不轉,
  掃到舊 API 一律要求改寫。
- **Developer 平台整合**:PAT 引導設置、建模組推草稿、平台 preflight、沙箱 secrets/CRUD/actions
  端到端測試、test 事件與送審門檻。

## 安裝方式

```bash
# 專案內(或裝到 ~/.claude/skills/ 供全域使用)
git clone https://github.com/AI-GO-APP/aigo-template-transfer-skill.git
cd aigo-template-transfer-skill
uv sync          # 或 pip install httpx(scripts 唯一第三方相依)
```

Claude Code:把本目錄放進 `.claude/skills/` 或以 `--add-dir` 掛入;
Antigravity / Cursor:把 `SKILL.md` 加入 agent 的 rules/context。

## 保持更新

Skill 內含版本標記(`VERSION`)與更新檢查腳本(`scripts/check_update.py`),
比對本地與 GitHub 上的 `VERSION`,有新版才提示。腳本零相依(只用 Python 標準函式庫、
不經 uv),離線或逾時一律靜默略過,預設 24 小時內只檢查一次
(狀態存在 `~/.aigo-transfer/update_check.json`;**離線那次不算**,下次仍會嘗試)。

**任何 agent 都適用(預設)**:`SKILL.md` 的 Phase -1 會在每次 Skill 觸發時執行檢查,
有新版時由 AI 告知你並詢問是否更新。缺點是 `SKILL.md` 已載入 context,更新後需重新讀取
才會在當回合生效。

**Claude Code / Codex(推薦加裝)**:改用 SessionStart hook,在 Skill 載入**之前**完成檢查,
沒有上述時序問題。範本在 `resources/hooks/`,把 `<SKILL_DIR>` 換成本機 skill 路徑後合併進設定:

| Agent | 設定檔 | 範本 |
|-------|--------|------|
| Claude Code | `~/.claude/settings.json` 或 `<專案>/.claude/settings.json` | `resources/hooks/claude-code.settings.example.json` |
| Codex CLI(>= v0.124.0) | `~/.codex/config.toml` 或 `<repo>/.codex/config.toml` | `resources/hooks/codex.config.example.toml` |

手動檢查與更新:

```bash
python scripts/check_update.py --force   # 忽略節流立即檢查(macOS/Linux 用 python3)
python scripts/check_update.py --json    # 機器可讀輸出(一律輸出,含 status)
python scripts/check_update.py --apply   # git 安裝:就地 pull --ff-only
```

`--apply` 只在 skill 目錄是 git repo 時才會實際更新;用 `npx skills add` 安裝的複製式安裝
會印出 `npx skills update` 讓你自己執行。任一情況都**不會**覆寫你的本地修改
(`--ff-only` 遇到分岔會直接失敗)。

> 維護者注意:改動 Skill 內容後要同步 bump `VERSION` 並在 `CHANGELOG.md` 補一節,
> 否則使用者端不會收到更新提示。

## 快速開始

```bash
python scripts/devportal.py setup              # 產生 .env + PAT 引導
python scripts/devportal.py set-pat            # 貼入 PAT
# 用戶本人在 .env 填 AIGO_EMAIL / AIGO_PASSWORD(來源側,builder.access)
python scripts/transfer_cli.py init --slug my_template
```

之後依 [SKILL.md](SKILL.md) 的 Phase 0–9 執行。各階段速覽:

| 階段 | 內容 | 執行 |
|---|---|---|
| S0 | 候選判定(new/merge/exclude) | `transfer_cli.py gate --stage S0`(人工) |
| S1 | 抽取正規化 | `acquire.py --from-app / --from-repo` |
| S2 | 污染掃描(只報告) | `scan.py` |
| S3 | 去租戶化(逐條裁決→套用) | `apply_decisions.py`(人工裁決) |
| S4 | Data Center schema | `dc_extract.py --tables ...`(人工挑表) |
| S5 | demo 資料 | 起草 + `gate --stage S5`(人工) |
| S6 | 本地 audit 硬閘 | `normalize_meta.py` + `audit_local.py` |
| S7 | Developer 建草稿 + preflight(寫後回讀) | `devportal.py push` |
| S8 | 沙箱端到端測試(`--quick`/full 兩檔) | `e2e_devportal.py` |
| S9 | 送審(要求最後一次 e2e 為 full) | `devportal.py submit`(人工確認) |

版本線與診斷(不屬於階段,隨時可用):

| 指令 | 用途 |
|---|---|
| `devportal.py bump --kind minor` | 已發布模組開下一版(會重置 S8/S9) |
| `devportal.py withdraw` | 撤回送審——送審中不可改內容 |
| `devportal.py events` | 佈署/測試事件與送審門檻現況(伺服器真相) |
| `devportal.py pull` | 把平台上的版本檔案取回本機 |
| `devportal.py live-templates` | 架上清單(S0 比對重疊) |
| `devportal.py adopt --template-slug x` | 接管未受管的架上模板(admin,**不可逆**) |

S1 會同時盤點不隨 VFS 走的資源(webhook 宣告、Egress 網域、app 排程)→
`inventory.json`,並在 S6 自動轉成「安裝後設定清單」寫入模板 long_description——
確保安裝租戶知道要補哪些租戶級設定,模板裝完即可用。

## 測試

```bash
python -m unittest discover -s tests -v
```

## 相關系統

- [aigo-app-builder-skill](https://github.com/AI-GO-APP/aigo-app-builder-skill):
  custom app 開發 skill(本 skill 的憑證紀律、盤點面與驗證慣例與其對齊)
- ai-go-developer:Developer 平台(本 skill 的發布目的地;
  `--ai-go-backend` 指向其 repo 可用 ctx-core 的權威 DSL parser 做真驗證)
- ai-go:AI GO 本體(來源 app 與 Data Center)
