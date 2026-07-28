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

## 快速開始

```bash
uv sync                                        # 或 pip install httpx
python scripts/devportal.py setup              # 產生 .env + PAT 引導
python scripts/devportal.py set-pat            # 貼入 PAT
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
| S7 | Developer 建草稿 + preflight | `devportal.py push` |
| S8 | 沙箱端到端測試 | `e2e_devportal.py` |
| S9 | 送審 | `devportal.py submit`(人工確認) |

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
