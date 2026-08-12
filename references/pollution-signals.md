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
  以同名 slug 註冊(填 base_url;domain-only,不填金鑰),否則 action 一律連不出去
  (這是設定問題,改 code 改不掉)。
- **raw `httpx` / `requests` / `urllib.request`**:runner 是 default-deny egress
  (ADR-0003:SG 只放行 ctx-only service),raw 連線**直接 timeout**——沙箱測不過。
  一律改 `ctx.http.call`。
- **靠閘道注入憑證的舊寫法**:`ctx.http.call` 不帶任何 `Authorization`、指望
  EgressService 上的 `auth_type`/`auth_config` 被閘道注入。**2026-08-03 起這條路已封**
  (AI GO ADR 0010 domain-only):`_inject_auth` 從 AI GO 與 Developer 兩邊的 runtime
  整支移除,既有 service row 上的憑證欄位一律忽略。這種寫法的可怕之處是
  **沙箱測得過、上線後 401**,錯誤浮現在「租戶新增渠道」離部署最遠的地方。
  改法:金鑰進 `setup_schema`,action 端 `ctx.secrets.get(...)` 讀出來自組
  `headers={"Authorization": ...}` 傳給 `ctx.http.call`——閘道現在只剝 hop-by-hop,
  Authorization 原樣轉送。
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
- **Egress service**:action 對外呼叫走閘道,租戶要以**同名 slug** 註冊 EgressService。
  ADR 0010 之後 service 上**只有 base_url 與政策**,憑證不在那裡——所以第三方金鑰
  是 `setup_schema` 的事,兩者都要進安裝後設定清單。S1 從 action 原始碼撈出全部
  對外網域與 `ctx.http.call` 的 slug 寫入 inventory.json;轉換後 slug 進
  `required_egress` 宣告(安裝流程會主動提示租戶),網域則供租戶填 base_url。
- **INJ 三檔**(`src/data.json`、`src/db.json`、`src/actions.json`):本身就是租戶資料快照
  (表定義含真實 id、Data Reference 含快取資料列)。S1 抽取時自動改空殼,原件留 raw/。
- **真實資料**:模板的 demo 資料必須是創作的(繁中、台灣在地化),不得沿用客戶資料——
  包括看似無害的名單、品項、對話紀錄。
- **app_domain**:SaaS 表 `custom_data.app_domain` 慣例值應統一改為新模板 slug。
- **兩份 meta**(`_template.json` + `_template_meta.json`):S1 移到 source_meta/,
  由 normalize_meta.py 收斂為單一合規 meta;repo 內部欄位(factory_key/template_version/
  generated_at/source)不上平台。
