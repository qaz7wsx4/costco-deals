"""會員護照優惠券：讀官網 /savings 頁，辨識每張優惠券圖片上印的「賣場售價」。

優惠券是圖片，文字只有商品名稱與連結，所以價格要靠 OCR（scripts/ocr.swift，macOS Vision）。
每張圖辨識兩次（原圖、綠色通道），每段文字取前三個候選讀法，
只有找得到「原價 − 折扣 = 售價」剛好成立的組合才採用，讀不準就只附圖片、不給數字。

辨識結果依圖片編號快取在 site/data/coupon-ocr.json，同一張圖只辨識一次。
沒有 OCR 工具（例如在 Linux 上）時照樣回傳優惠券清單，只是沒有價格。
"""
import html
import itertools
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

SITE = "https://www.costco.com.tw"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/128 Safari/537.36"
CACHE = Path(__file__).resolve().parent.parent / "site" / "data" / "coupon-ocr.json"

CARD = re.compile(
    r'<div class="col-xs-6[^"]*">\s*<a href="([^"]*)"[^>]*>\s*<img alt="([^"]*)" src="(/mediapermalink/[^"]+)"')
PERIOD = re.compile(r"(20\d\d)/(\d\d)/(\d\d)\s*[~～-]\s*(20\d\d)/(\d\d)/(\d\d)")
# 「269/公斤」「-54公斤」「$1,729」「- 84」；千分位逗號常被讀成小數點（價格不會有小數）
NUM = re.compile(r"^([-－–—])?\s*(\$)?\s*(\d{1,3}(?:[.,]\d{3})+|\d+)\s*(?:/?\s*(公斤|公克|100公克|磅))?")


def http_get(url, binary=False):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
                return data if binary else data.decode("utf-8", "ignore")
        except Exception as e:
            print(f"  {url} 失敗（{e}），重試…", file=sys.stderr)
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"無法取得 {url}")


def parse_page(page):
    """回傳 (檔期起, 檔期迄, 優惠券清單)。"""
    period = PERIOD.search(page)
    start = f"{period[1]}-{period[2]}-{period[3]}" if period else None
    end = f"{period[4]}-{period[5]}-{period[6]}" if period else None
    cards, seen = [], set()
    for href, alt, src in CARD.findall(page):
        img_id = src.rsplit("/", 1)[-1]
        if img_id in seen:
            continue
        seen.add(img_id)
        code = re.search(r"/p/(\d+)", href)
        cards.append({
            "id": img_id,
            "img": SITE + src,
            "code": code[1] if code else None,
            "name": html.unescape(alt).split("\n")[0].strip(),
        })
    return start, end, cards


def tokens(lines):
    """把大字的數字都列出來（含每段文字的候選讀法）。"""
    out, seen = [], set()
    for ln in lines:
        if ln["h"] < 0.07:  # 價格都是大字，小字（規格、編號）略過
            continue
        for rank, text in enumerate(ln.get("alts") or [ln["t"]]):
            m = NUM.match(text.replace(" ", ""))
            if not m:
                continue
            raw = re.sub(r"[.,]", "", m[3])
            tok = {"neg": bool(m[1]), "dollar": bool(m[2]), "v": int(raw), "raw": raw,
                   "unit": m[4], "y": ln["y"], "h": ln["h"], "rank": rank}
            key = (tok["neg"], tok["dollar"], tok["v"], round(tok["y"], 2))
            if key not in seen:
                seen.add(key)
                out.append(tok)
    return out


def one_digit_off(expected, raw):
    """算出來的值跟讀到的字是否只差一個數字（例如紅色的 8 被讀成 0）。"""
    e = str(expected)
    return expected > 0 and len(e) == len(raw) and sum(x != y for x, y in zip(e, raw)) == 1


def find_triple(toks, exact):
    """找「原價 − 折扣 = 售價」。exact=False 時允許其中一個數字差一位，用另外兩個算回來。"""
    best = None
    for a, b, c in itertools.permutations(toks, 3):
        # 版面固定是：原價在上、折扣（有負號）在中、售價在下
        if a["neg"] or c["neg"] or not b["neg"]:
            continue
        if not (a["y"] + 0.03 < b["y"] < c["y"] - 0.03):
            continue
        base, off, price = a["v"], b["v"], c["v"]
        if exact:
            if off <= 0 or price <= 0 or base - off != price:
                continue
            fix = 0
        # 最容易讀錯的是紅色折扣，其次原價，售價（有 $）最穩
        elif one_digit_off(base - price, b["raw"]):
            off, fix = base - price, 1
        elif one_digit_off(price + off, a["raw"]):
            base, fix = price + off, 2
        elif one_digit_off(base - off, c["raw"]):
            price, fix = base - off, 3
        else:
            continue
        if not (base > price > 0 and off > 0):
            continue
        score = (-fix, 2 * c["dollar"] - (a["rank"] + b["rank"] + c["rank"]) + a["h"] + b["h"] + c["h"])
        if not best or score > best[0]:
            best = (score, base, off, price, a["unit"] or b["unit"] or c["unit"])
    return best


def rescue(toks, off):
    """讀不出來、但已知線上折扣時：折扣與售價讀對，原價允許差兩位數，就用「售價 + 折扣」當原價。"""
    for b in (t for t in toks if t["neg"] and t["v"] == off):
        for c in (t for t in toks if t["dollar"] and not t["neg"] and t["y"] > b["y"] + 0.03):
            base = c["v"] + off
            for a in (t for t in toks if not t["neg"] and t["y"] < b["y"] - 0.03):
                e = str(base)
                if len(e) == len(a["raw"]) and sum(x != y for x, y in zip(e, a["raw"])) <= 2:
                    return {"base": base, "off": off, "price": c["v"], "unit": c["unit"] or a["unit"], "corrected": True}
    return None


def read_prices(lines):
    """從 OCR 結果找出賣場售價。回傳 dict，讀不出來時只有 code。"""
    text = " ".join(ln["t"] for ln in lines)
    item = re.search(r"ITEM\s*(\d{4,8})", text)
    res = {"code": item[1] if item else None}
    toks = tokens(lines)

    best = find_triple(toks, exact=True) or find_triple(toks, exact=False)
    if best:
        _, base, off, price, unit = best
        res.update(base=base, off=off, price=price, unit=unit)
        if best[0][0]:
            res["corrected"] = True
    elif "活動售價" in text:
        # 「$419 專案活動售價」這種版面只有一個價格
        d = [t for t in toks if t["dollar"] and t["rank"] == 0]
        if d:
            res.update(price=max(d, key=lambda t: t["h"])["v"], special=True)
    else:
        # 留著數字，之後如果知道線上折扣，還能用 rescue() 再試一次
        res["toks"] = [{k: t[k] for k in ("neg", "dollar", "v", "raw", "unit", "y")} for t in toks]
    res["store"] = "賣場售價" in text or "活動售價" in text
    return res


def find_ocr():
    """回傳可執行的 OCR 工具路徑；沒有就回傳 None。"""
    exe = os.environ.get("OCR_BIN")
    if exe and Path(exe).exists():
        return exe
    src = Path(__file__).with_name("ocr.swift")
    if sys.platform != "darwin":
        return None
    out = Path(tempfile.gettempdir()) / "costco-ocr"
    if not out.exists() or out.stat().st_mtime < src.stat().st_mtime:
        print("編譯 OCR 工具…")
        r = subprocess.run(["swiftc", "-O", str(src), "-o", str(out)], capture_output=True, text=True)
        if r.returncode:
            print(r.stderr, file=sys.stderr)
            return None
    return str(out)


def ocr_new(cards, cache):
    todo = [c for c in cards if c["id"] not in cache]
    if not todo:
        return
    exe = find_ocr()
    if not exe:
        print(f"沒有 OCR 工具，{len(todo)} 張優惠券先不讀價格")
        return
    with tempfile.TemporaryDirectory() as tmp:
        paths = {}
        for c in todo:
            p = Path(tmp) / f"{c['id']}.jpg"
            p.write_bytes(http_get(c["img"], binary=True))
            paths[str(p)] = c["id"]
            time.sleep(0.3)
        r = subprocess.run([exe, *paths], capture_output=True, text=True, timeout=600)
        if r.returncode:
            print(r.stderr, file=sys.stderr)
        for line in r.stdout.splitlines():
            d = json.loads(line)
            cache[paths[d["file"]]] = read_prices(d["lines"])
    ok = sum("price" in cache[c["id"]] for c in todo if c["id"] in cache)
    print(f"辨識 {len(todo)} 張新優惠券，讀出價格 {ok} 張")


def fetch(known_offs=None):
    """回傳 {"start", "end", "coupons": [...]}；每張券附上辨識出的價格（如果有）。
    known_offs：{商品編號: 線上折扣}，用來補救讀不出來的券。"""
    start, end, cards = parse_page(http_get(SITE + "/savings"))
    cache = json.loads(CACHE.read_text("utf-8")) if CACHE.exists() else {}
    ocr_new(cards, cache)
    # 只保留目前頁面上的圖，舊檔期的自然淘汰
    cache = {c["id"]: cache[c["id"]] for c in cards if c["id"] in cache}
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=0, sort_keys=True), "utf-8")

    coupons = []
    for c in cards:
        r = cache.get(c["id"], {})
        code = c["code"] or r.get("code")
        if not code:
            continue  # 眼鏡、隱形眼鏡這類沒有單一商品的券
        if "price" not in r and r.get("toks") and (known_offs or {}).get(code):
            r = {**r, **(rescue(r["toks"], known_offs[code]) or {})}
        coupons.append({**c, "code": code, **{k: r[k] for k in ("base", "off", "price", "unit", "special") if r.get(k)}})
    print(f"會員護照 {start}～{end}：{len(coupons)} 張商品優惠券")
    return {"start": start, "end": end, "coupons": coupons}


if __name__ == "__main__":
    # 單獨執行時印出辨識結果，方便檢查
    d = fetch()
    for c in d["coupons"]:
        p = f"{c.get('base', ''):>6} {('-' + str(c['off'])) if c.get('off') else '':>6} {c.get('price', '—'):>6}"
        print(f"{c['code']:>8} {p} {c.get('unit') or '':3} {c['name'][:24]}")
