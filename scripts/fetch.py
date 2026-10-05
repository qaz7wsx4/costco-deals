#!/usr/bin/env python3
"""抓取 Costco 台灣官網的特價商品，輸出網站要用的 JSON。

資料來源是官網商品列表頁自己在用的查詢介面（非正式公開 API）：
  - Wallet   ：會員護照（線上與賣場同步折扣）
  - hot-buys ：限時優惠（包含會員護照與線上限定特價）
另外讀會員護照頁（/savings）的優惠券圖片，取得「賣場售價」與賣場限定商品，見 coupons.py。

輸出：
  site/data/latest.json  ：目前所有特價商品
  site/data/history.json ：每個商品出現過的每一檔特價（用來查「上次特價」）

只用標準函式庫，GitHub Actions 上不需要安裝任何套件。
"""
import json
import sys
import traceback
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import coupons

API = "https://www.costco.com.tw/rest/v2/taiwan/products/search"
SITE = "https://www.costco.com.tw"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/128 Safari/537.36"
TPE = timezone(timedelta(hours=8))
DATA = Path(__file__).resolve().parent.parent / "site" / "data"

SOURCES = {"Wallet": "wallet", "hot-buys": "hot"}

# 商品網址第一段 → 大分類
URL_GROUPS = {
    "Food-Dining": "食品飲料",
    "Household-Baby-Toys": "日用品・母嬰玩具",
    "Health-Beauty": "保健美妝",
    "Clothing-Accessories": "服飾配件",
    "Furniture-Kitchen": "家具廚具",
    "Televisions-Appliances": "家電",
    "Televisions-TV-Accessories": "家電",
    "Digital-Mobile": "3C 數位",
    "Sports-Lifestyle": "運動休閒",
    "Lawn-Garden": "戶外庭園",
    "Jewelry-Gold": "珠寶黃金",
    "Office-School": "辦公文具",
    "Business-Delivery": "商業採購",
    "Tire": "汽車輪胎",
    "Bridgestone": "汽車輪胎",
    "Pirelli": "汽車輪胎",
}


# 賣場限定商品的網址是 /Warehouse-Only/第二層/…，用第二層分類
WAREHOUSE_GROUPS = {
    "Food-Beverages": "食品飲料",
    "Wine-Liquor": "食品飲料",
    "Household-Supplies": "日用品・母嬰玩具",
    "Health-Beauty": "保健美妝",
}


def group_from_leaf(code):
    """網址不是分類路徑（品牌頁等）時，用細分類代碼推大分類。"""
    if code.startswith("BD"):
        return "商業採購"
    if len(code) == 6:
        return {"10": "服飾配件", "11": "珠寶黃金", "12": "運動休閒", "13": "日用品・母嬰玩具",
                "15": "辦公文具", "16": "運動休閒"}.get(code[:2])
    if len(code) == 5:
        if code.startswith("915"):
            return "日用品・母嬰玩具"
        return {"1": "3C 數位", "2": "3C 數位", "3": "家電", "4": "戶外庭園", "5": "家具廚具",
                "6": "家具廚具", "7": "保健美妝", "8": "保健美妝", "9": "食品飲料"}.get(code[0])
    return None


def api_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception as e:  # 網路抖動就重試，三次都失敗才放棄
            print(f"  {url} 失敗（{e}），重試…", file=sys.stderr)
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"無法取得 {url}")


def get(category, page):
    return api_get(API + f"?category={category}&fields=FULL&pageSize=100&currentPage={page}&lang=zh_TW&curr=TWD")


def get_product(code):
    return api_get(API.replace("/search", f"/{code}") + "?fields=FULL&lang=zh_TW&curr=TWD")


def fetch_category(category):
    products, leaves, page = [], {}, 0
    while True:
        d = get(category, page)
        products += d.get("products", [])
        for f in d.get("facets", []):
            if f["name"] == "category":
                leaves.update({v["code"]: v["name"] for v in f["values"]})
        total = d["pagination"]["totalPages"]
        page += 1
        if page >= total:
            break
        time.sleep(1)
    print(f"{category}: {len(products)} 項")
    return products, leaves


def tpe_date(iso):
    """'2026-09-27T15:59:59.999Z' → '2026-09-27'（台灣時間）"""
    if not iso:
        return None
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return dt.astimezone(TPE).strftime("%Y-%m-%d")


def image(p):
    by_fmt = {i["format"]: i["url"] for i in p.get("images", [])}
    url = by_fmt.get("product-webp") or by_fmt.get("product") or by_fmt.get("thumbnail")
    return SITE + url if url else None


def meta(p, leaves):
    """商品本身的資料（名稱、圖、分類），跟價格無關。"""
    cats = [k["key"] for k in p.get("addToCartFromPLPCategories", [])]
    leaf = next((c for c in cats if c in leaves and len(c) >= 5), None)
    segs = (p.get("url") or "/").split("/")[1:3] + [""]
    group = (URL_GROUPS.get(segs[0]) or (segs[0] == "Warehouse-Only" and WAREHOUSE_GROUPS.get(segs[1]))
             or (group_from_leaf(leaf) if leaf else None) or "其他")
    return {
        "code": p["code"],
        "name": p.get("name", "").strip(),
        "en": p.get("englishName", "").strip(),
        "img": image(p),
        "url": SITE + p["url"] if p.get("url") else None,
        "group": group,
        "leaf": leaves.get(leaf) if leaf else None,
        "rating": p.get("averageRating") or None,
        "reviews": p.get("numberOfReviews") or 0,
    }


def simplify(p, leaves):
    cd = p.get("couponDiscount") or {}
    off = cd.get("discountValue")
    base = (p.get("basePrice") or {}).get("value")
    price = (p.get("price") or {}).get("value")
    if p.get("hidePriceValue") or not off or not base or price is None:
        return None  # 輪胎這類「進去才看得到價格」的商品略過

    ppu = p.get("pricePerUnit") if p.get("hasPricePerUnit") else None
    return {
        **meta(p, leaves),
        "online": True,
        "base": round(base),
        "price": round(price),
        "off": round(off),
        "pct": round(off / base * 100),
        "start": tpe_date(cd.get("discountStartDate")),
        "end": tpe_date(cd.get("discountEndDate")),
        "limit": cd.get("maxQtyDiscount") or 0,
        "unit": {"price": ppu["value"], "per": p.get("unitType") or ""} if ppu else None,
        "stock": (p.get("stock") or {}).get("stockLevelStatus") != "outOfStock",
        "store": None,
    }


def store_info(c):
    """優惠券上的賣場價格；讀不出來時只有優惠券圖片。"""
    info = {"coupon": c["img"]}
    for k in ("base", "off", "price", "unit", "special"):
        if c.get(k):
            info[k] = c[k]
    return info


def add_coupons(items, leaves):
    """把會員護照優惠券併進來：線上有的商品加上賣場售價，賣場限定的商品另外新增。"""
    try:
        book = coupons.fetch({it["code"]: it["off"] for it in items})
    except Exception:
        traceback.print_exc()
        print("會員護照頁讀取失敗，這次只用線上資料", file=sys.stderr)
        return
    by_code = {it["code"]: it for it in items}
    added = 0
    for c in book["coupons"]:
        it = by_code.get(c["code"])
        if c.get("onlineOnly"):
            # 「僅限好市多線上購物」的券：線上資料已經有這個折扣，只標記一下
            if it:
                it["walletOnline"] = True
                if "wallet" not in it["src"]:
                    it["src"] = sorted(it["src"] + ["wallet"])
            continue
        if it:
            info = store_info(c)
            # 會員護照的折扣線上、賣場相同；對不上表示辨識有誤，只留圖片
            if info.get("off") and info["off"] != it["off"]:
                print(f"  #{c['code']} 優惠券折扣 {info['off']} ≠ 線上折扣 {it['off']}，不採用辨識結果")
                info = {"coupon": c["img"]}
            it["store"] = info
            if "wallet" not in it["src"]:
                it["src"] = sorted(it["src"] + ["wallet"])
            continue
        # 賣場限定（或線上沒在特價）的商品：名稱、圖片、分類向商品頁要
        try:
            base_info = meta(get_product(c["code"]), leaves)
            time.sleep(0.5)
        except Exception:
            base_info = {"code": c["code"], "name": c["name"], "en": "", "img": None,
                         "url": f"{SITE}/p/{c['code']}", "group": "其他", "leaf": None,
                         "rating": None, "reviews": 0}
        it = {**base_info, "online": False, "base": None, "price": None, "off": None, "pct": None,
              "start": book["start"], "end": book["end"], "limit": 0, "unit": None, "stock": True,
              "store": store_info(c), "src": ["wallet"]}
        items.append(it)
        by_code[it["code"]] = it
        added += 1
    online_only = sum(bool(c.get("onlineOnly")) for c in book["coupons"])
    print(f"會員護照：{len(book['coupons'])} 張（賣場券 {len(book['coupons']) - online_only}、線上券 {online_only}），新增賣場限定 {added} 項")


def deal_of(it):
    """這一檔特價的代表數字：有賣場價用賣場價，否則用線上價。"""
    s = it.get("store") or {}
    off = it["off"] or s.get("off")
    if not off:
        return None
    return {"start": it["start"], "end": it["end"], "off": off,
            "base": s.get("base") or it["base"], "price": s.get("price") or it["price"],
            "where": "store" if s.get("price") else "online"}


def update_history(items, today):
    path = DATA / "history.json"
    hist = json.loads(path.read_text("utf-8")) if path.exists() else {}
    for it in items:
        h = hist.setdefault(it["code"], {"deals": []})
        h["name"], h["img"], h["url"] = it["name"], it["img"] or (it["store"] or {}).get("coupon"), it["url"]
        h["lastSeen"] = today
        cur = deal_of(it)
        if not cur:
            continue
        key = (cur["start"], cur["end"], cur["off"])
        deal = next((d for d in h["deals"] if (d["start"], d["end"], d["off"]) == key), None)
        if deal:
            deal.update(base=cur["base"], price=cur["price"], where=cur["where"], lastSeen=today)
        else:
            h["deals"].append({**cur, "firstSeen": today, "lastSeen": today})
    path.write_text(json.dumps(hist, ensure_ascii=False, separators=(",", ":"), sort_keys=True), "utf-8")
    return hist


def main():
    merged, leaves = {}, {}
    for category, tag in SOURCES.items():
        products, lv = fetch_category(category)
        leaves.update(lv)
        for p in products:
            merged.setdefault(p["code"], (p, set()))[1].add(tag)
        time.sleep(1)

    now = datetime.now(TPE)
    today = now.strftime("%Y-%m-%d")
    items = []
    for p, tags in merged.values():
        it = simplify(p, leaves)
        if it:
            it["src"] = sorted(tags)
            items.append(it)

    # 官網改版或被擋時通常會回傳空資料；這時寧可不更新，也不要把網站清空
    if len(items) < 20:
        sys.exit(f"只抓到 {len(items)} 項，看起來不對勁，這次不寫入。")

    add_coupons(items, leaves)

    hist = update_history(items, today)
    for it in items:
        cur = deal_of(it)
        deal = cur and next((d for d in hist[it["code"]]["deals"]
                             if (d["start"], d["end"], d["off"]) == (cur["start"], cur["end"], cur["off"])), None)
        it["firstSeen"] = deal["firstSeen"] if deal else today

    items.sort(key=lambda x: -((x["store"] or {}).get("off") or x["off"] or 0))
    out = {"updated": now.isoformat(timespec="minutes"), "count": len(items), "items": items}
    (DATA / "latest.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), "utf-8")
    print(f"寫入 {len(items)} 項特價商品，歷史紀錄共 {len(hist)} 項商品")


if __name__ == "__main__":
    main()
