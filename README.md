# 好市多特價整理

每天自動整理 Costco 台灣官網的「會員護照」與「限時優惠」，出門前先查好價格。
會員護照的商品會顯示從優惠券圖片讀出的**賣場售價**。

## 運作方式

```
GitHub Actions（每天台灣時間 00:20、07:00；GitHub 排程常延遲 2～3 小時）
  fetch（macOS）
  └─ scripts/fetch.py 呼叫官網商品查詢介面
  └─ scripts/coupons.py 讀會員護照頁 /savings，用 scripts/ocr.swift（Vision）辨識優惠券圖片
        ├─ site/data/latest.json      目前的特價商品
        ├─ site/data/history.json     每個商品出現過的每一檔特價
        └─ site/data/coupon-ocr.json  優惠券辨識結果快取（同一張圖只辨識一次）
  deploy（Ubuntu）
  └─ 把 site/ 發佈到 GitHub Pages
```

- 資料來源：`https://www.costco.com.tw/rest/v2/taiwan/products/search?category=Wallet`（會員護照）
  與 `category=hot-buys`（限時優惠）。這是官網列表頁自己在用的介面，**不是正式公開 API**，改版時可能要調整。
- `hot-buys` 裡有些商品其實沒折扣（原價＝售價），抓取時會略過；輪胎這類隱藏價格的也略過。
- 抓到少於 20 項會視為異常、不覆寫資料，避免官網改版時把網站清空。

## 會員護照優惠券（賣場售價）

- `/savings` 頁上每張優惠券是一張圖，價格印在圖上（原價、紅色折扣、賣場售價），文字只有名稱與連結。
- 每張圖辨識兩次（原圖、只取綠色通道——紅字在綠色通道裡是深色），每段文字取前三個候選讀法。
- 只採用「原價 − 折扣 = 售價」成立的組合；若只有一個數字差一位（常見：紅色 8 讀成 0、千分位逗號讀成小數點），
  用另外兩個算回來。差更多就不給數字，網站只附優惠券圖片。
- 線上也有賣的商品，會再比對官網折扣金額，不一致就不採用（2026-10-05 首次上線 48 項全部一致）。
- 賣場限定商品（土雞、紅酒、鮮乳製品等）官網查詢介面沒有價格，只能從優惠券取得，網站上標「賣場限定」。
- 本機要測辨識：`python3 scripts/coupons.py`（第一次會自動編譯 ocr.swift）。

## 價格的限制

- 官網價格**已含運費**，通常比賣場貴。
- 會員護照的**折扣金額**線上與賣場相同，所以「賣場原價 − 折扣」才是賣場實際價格。
- 會員護照以外的商品，賣場原價官方沒有公開，網站讓使用者自己記錄（存在瀏覽器 localStorage，可匯出匯入）。
- 商品編號與賣場價格牌一致（已用網友現場照片對照確認）。

## 本機開發

```bash
python3 scripts/fetch.py                     # 更新資料
python3 -m http.server 8765 --directory site # 開 http://localhost:8765
```

只用 Python 標準函式庫，不需要安裝任何套件；網站是純 HTML/CSS/JS。

## 部署設定（只需做一次）

GitHub repo → Settings → Pages → Source 選 **GitHub Actions**。
之後每次 push 到 main 或排程執行都會自動發佈。
