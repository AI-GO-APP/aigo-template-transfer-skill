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

### 自動更新檢查(建議)

Skill 內建 `scripts/check_update.py`(零相依、離線靜默、24h 節流、絕不自動覆寫)。
把 `resources/hooks/claude-code.settings.example.json` 的 hooks 區塊合併進
`~/.claude/settings.json`,SessionStart 時自動檢查;或每次觸發 skill 時由
Phase -1 手動執行。更新一律 `git pull --ff-only`,有本地修改不會被覆蓋。

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

S1 會同時盤點不隨 VFS 走的資源(webhook 宣告、Egress 網域、app 排程)→
`inventory.json`,並在 S6 自動轉成「安裝後設定清單」寫入模板 long_description——
確保安裝租戶知道要補哪些租戶級設定,模板裝完即可用。

## 測試

```bash
python -m unittest discover -s tests -v
```

## 相關系統

- [ai-go-templates](https://github.com/AI-GO-APP/ai-go-templates):模板 repo 與
  template-develop/deploy/audit skills(本 skill vendor 其 audit 四閘)
- ai-go-developer:Developer 平台(本 skill 的發布目的地)
- ai-go:AI GO 本體(來源 app 與 Data Center;`data_center_schema` 權威 parser 所在,
  以 `--ai-go-backend` 指向可做真驗證)
