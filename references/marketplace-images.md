# 商城展示圖(banner + 介面截圖)

模板在 AI GO 商城的卡片與詳情頁靠這組圖說話。沒有圖的模板在架上只有文字,
點進去看不到任何畫面。

三段工程都已上線:AI-GO#1231(images 欄位與上傳/刪除 API)、
aigo-developer-platfom#135(平台代理與權限閘)、AI-GO-HOMEPAGE#77(官網渲染)。
**圖片上傳完即為可發布狀態,不需要額外的發布動作。**

## 端點(平台代理,用 PAT)

| 方法 | 路徑 | 說明 |
|---|---|---|
| `GET` | `/modules/{module_id}/images` | 回 `{slug, images:[{key,url}]}` |
| `POST` | `/modules/{module_id}/images` | multipart,**欄位名 `file`** |
| `DELETE` | `/modules/{module_id}/images?key=<key>` | key 逐字比對 |

平台端只做代理與權限閘,不落任何檔案;圖片本體在 AI GO 的公開 S3。
權限與內容編輯同一道閘(`assert_can_edit`,協作者可傳)。

## 硬限制

| 限制 | 值 | 違反時 |
|---|---|---|
| 單張大小 | 5 MiB | 平台先擋 413(不浪費跨服務往返) |
| 每模組張數 | **10 張** | AI GO 回 409 |
| 格式 | jpg / png / webp | AI GO 以 magic bytes 驗證,回 400 |
| 模組狀態 | **必須上架中** | 未上架一律 409,且完全不打 AI GO |

未上架就是不能傳:展示圖掛在架上模板,AI GO 的讀取端點只回 `is_active=True`
(單向可見性),對未上架模組操作只會得到一連串對面 404。

## ★ 上傳不可重試

`publish_client.upload_template_image` 刻意不重試——**結果不明時重打會多出一張分身圖**。
連線層失敗時無法分辨「沒送到」與「送到了但回應掉了」,所以:

- 一律停下來標記該模組,由人決定要不要清空重來
- 批次作業設成遇第一個失敗即停,不要讓錯誤往後累積
- 要重來就先 `DELETE` 清空該模組全部 key,再從頭上傳

## ★ 順序即上傳順序

AI GO 是**附加**語意,`GET` 回來的陣列順序就是上傳順序,也就是商城的顯示順序。
**第一張是封面。**

所以:banner 必須第一個送,之後才依序號送介面截圖。一次只能循序上傳,
不能並行,否則順序會亂。

## ★ 驗證不能用檔名

AI GO 會把檔名換成雜湊 key:

```
templates/<slug>/d93639015ee4.png
```

原始檔名不保留,所以「檢查 key 裡有沒有 -00-」這種驗法一定誤判。
正確做法是**比對內容**:

- 便宜版:對每個 `url` 送 `HEAD`,比對 `Content-Length` 與本地檔案大小,
  逐張對照順序(同一支模組內各張大小幾乎不可能重複,足以釘住順序)
- 嚴謹版:抽樣 `GET` 下載後比 SHA-256

## 檔名與 slug 對應

本 skill 的慣例:

```
<slug>-00-<情境詞>主視覺.png     ← banner(封面)
<slug>-01-<畫面概要>.png          ← 介面截圖,序號遞增
<slug>-02-<畫面概要>.png
...
```

**slug 比對要用「最長前綴精確比對」**:架上有 `food-order-pos` /
`food-order-center` / `food-order-hub`、`trad-*`、`cnst-*` 這種相似組合,
短的先比就會把長的檔案搶走,結果傳到錯的模組上。作法是把 slug 依長度由長到短排序後
逐一比對 `basename.startswith(slug + "-")`,第一個命中的才是擁有者。

## 截圖怎麼來:developer 預覽頁

「測試與佈署」的預覽頁就是最忠實的來源——那是真的把模板跑起來,
不是靜態圖:

```
https://developer.ai-go.app/preview/{module_id}?v={version_id}
```

要點:

- **認證**:把 PAT 直接寫進瀏覽器 `localStorage.dev_access_token` 即可開啟,
  不必另外登入(前端就是拿這個鍵當 Bearer token)
- **App 掛在 shadow DOM**:抓內容要先取宿主元素的 `shadowRoot`;
  該 root 的第一個子節點是 `<style>`,取「textContent 最長的非 style 子節點」才是 app 容器
- **右上角有預覽浮動列**(模組名 · 版號 · 存取模式 · 重新整理),
  選擇器 `div.fixed.inset-0 > div.absolute.right-3.top-3`,截圖前可隱藏
- **沙箱要先有資料**:`POST /sandbox/v/{vid}/actions/apps/{vid}/run/seed_demo_data`
  可直接對已上架版本跑(不必先開草稿)。沒有 `seed_demo_data` 的模板要自己灌
  引用表,注意沙箱不驗 CHECK 約束——列舉值填錯不會報錯,只會讓畫面篩不到
- **安裝期佔位符**:`{{APP_NAME}}` 在預覽不會被替換,截圖前就地換成模組名,
  才等同租戶安裝後所見

規格建議:16:9、寬度 ≥ 1366(實務上用 1600×900 @2x 輸出 3200×1800)。

## banner

banner 不限定怎麼生成——手繪、設計稿、AI 生成、截圖拼貼都可以。
**唯一要求是必須有一張序號 `00` 的圖當封面。**

## 常見錯誤

| 症狀 | 成因 | 處置 |
|---|---|---|
| 409「模組尚未上架」 | 該模組沒有 `current_live_version` | 等上架後再傳 |
| 409 張數上限 | 已達 10 張 | 先 `DELETE` 再傳,或減張數 |
| 413 | 單張超過 5 MiB | 壓縮或降解析度 |
| 400 格式 | magic bytes 不是 jpg/png/webp | 確認真的是該格式,不是改副檔名 |
| 封面不對 | banner 沒有第一個送 | `DELETE` 清空後依序重傳 |
| 傳到錯的模組 | slug 用短前綴比對 | 改最長前綴精確比對 |
