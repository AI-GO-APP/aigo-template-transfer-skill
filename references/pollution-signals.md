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
- **硬編碼網址**:客戶專屬網域 → 刪或參數化;第三方 API 端點 → **改走 egress 閘道**
  `ctx.http.call("<slug>", "<path>")`,base_url 落在租戶註冊的 EgressService。
  slug 必須記入「安裝後設定清單」——安裝租戶要在後台 `/dashboard/settings/integrations`
  以同名 slug 註冊(填 base_url 與自己的金鑰),否則 action 一律連不出去
  (這是設定問題,改 code 改不掉)。
- **raw `httpx` / `requests` / `urllib.request`**:runner 是 default-deny egress
  (ADR-0003:SG 只放行 ctx-only service),raw 連線**直接 timeout**——沙箱測不過,
  而送審門檻要求每支 enabled action 至少一次 success,等於卡死。一律改 `ctx.http.call`。
- **自帶 `Authorization` header**:即使用了 `ctx.http.call`,自己組
  `headers={"Authorization": ...}` 也沒用——AI GO `_sanitize_headers` 與 Developer 平台
  `dev_ctx._STRIPPED` 兩邊都會剝掉,實測回 401。金鑰歸 EgressService,action 不碰;
  連帶地也不要為它開 `setup_schema` 欄位。
- **前端舊制 Custom Data SDK**(`submitRecord/listRecords/...`):綁 objectId 的舊資料通道。

## 逐條確認(medium)

- **`ctx.secrets.get("K")` 的 K**:每個 key 都要問——是產品功能(→ setup_schema 收編、
  通用化命名)還是這家客戶的怪癖(→ 連功能一起刪)?
- **email / 電話**:客戶聯絡人 → 刪或換 demo 資料。
- **`print()` in actions**:規範用 `ctx.log()`。

## 結構性污染(掃描器之外,靠流程處理)

- **Webhook 宣告與 App 排程**:`actions/manifest.json` 的 `"webhook": true` 是對外端點宣告,
  排程(app-crons)是 app 級設定、不在 VFS 裡——兩者都不會跟著 VFS 走。S1 盤點寫入
  inventory.json,轉換後由「安裝後設定清單」告知安裝租戶重新登記/重建;
  webhook/排程 action 必須冪等(平台 at-least-once,可能重複執行)。
- **Egress service**:action 對外呼叫走閘道,租戶要以**同名 slug** 註冊 EgressService
  (base_url + 該租戶自己的憑證)。S1 從 action 原始碼撈出全部對外網域與
  `ctx.http.call` 的 slug 寫入 inventory.json;轉換後 slug 進 `required_egress` 宣告
  (安裝流程會主動提示租戶),網域則進安裝後設定清單供租戶填 base_url。
- **INJ 三檔**(`src/data.json`、`src/db.json`、`src/actions.json`):本身就是租戶資料快照
  (表定義含真實 id、Data Reference 含快取資料列)。S1 抽取時自動改空殼,原件留 raw/。
- **真實資料**:模板的 demo 資料必須是創作的(繁中、台灣在地化),不得沿用客戶資料——
  包括看似無害的名單、品項、對話紀錄。
- **app_domain**:SaaS 表 `custom_data.app_domain` 慣例值應統一改為新模板 slug。
- **兩份 meta**(`_template.json` + `_template_meta.json`):S1 移到 source_meta/,
  由 normalize_meta.py 收斂為單一合規 meta;repo 內部欄位(factory_key/template_version/
  generated_at/source)不上平台。
