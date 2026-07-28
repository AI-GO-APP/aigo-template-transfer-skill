# 租戶污染訊號(S2 掃描規則的依據)

整理自 aigo-builder 實碼與 ctx SDK(action_context.py)的高風險簽名(2026-07-28)。
機器可判的規則落在 config/scan_rules.json;本檔補充「為什麼」與人工判讀要點。

## 必除(blocker)

- **硬編碼憑證**:`api_key/secret/token/password = "長字串"`、LINE channel secret/token 樣態。
  掃到即代表租戶憑證已洩入程式碼,一律 `ctx.secrets.get` + setup_schema 參數化。
- **沙箱禁用 import**:`os, sys, subprocess, ctypes, socket, shutil, importlib`——runtime 必炸。
- **舊制 CustomObject API**:`ctx.db.query_object / insert_object / update_object /
  remove_object / list_custom_objects`——本 skill 一律新制,必須改寫(對照表見
  references/template-contract.md)。

## 必裁決(high)

- **硬編碼 UUID**:最常見於 `submitRecord(objectId, ...)` 第一參數、寫死的 app_id/tenant_id。
  正解通常是改走新制表操作或執行期取得。
- **硬編碼網址**:客戶網域 → 刪或參數化;第三方 API 端點 → 改走 egress service
  (`ctx.http.call(service, path)`,租戶安裝後自行註冊 service)。
- **前端舊制 Custom Data SDK**(`submitRecord/listRecords/...`):綁 objectId 的舊資料通道。

## 逐條確認(medium)

- **`ctx.secrets.get("K")` 的 K**:每個 key 都要問——是產品功能(→ setup_schema 收編、
  通用化命名)還是這家客戶的怪癖(→ 連功能一起刪)?
- **`ctx.http.call(service, ...)` 的 service 名**:egress 是租戶級資源;模板要在說明文件
  告知安裝租戶需註冊哪些 service,service 名應通用化。
- **email / 電話**:客戶聯絡人 → 刪或換 demo 資料。
- **`print()` in actions**:規範用 `ctx.log()`。

## 結構性污染(掃描器之外,靠流程處理)

- **INJ 三檔**(`src/data.json`、`src/db.json`、`src/actions.json`):本身就是租戶資料快照
  (表定義含真實 id、Data Reference 含快取資料列)。S1 抽取時自動改空殼,原件留 raw/。
- **真實資料**:模板的 demo 資料必須是創作的(繁中、台灣在地化),不得沿用客戶資料——
  包括看似無害的名單、品項、對話紀錄。
- **app_domain**:SaaS 表 `custom_data.app_domain` 慣例值應統一改為新模板 slug。
- **兩份 meta**(`_template.json` + `_template_meta.json`):S1 移到 source_meta/,
  由 normalize_meta.py 收斂為單一合規 meta;repo 內部欄位(factory_key/template_version/
  generated_at/source)不上平台。
