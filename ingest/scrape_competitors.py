"""Скрапер конкурентних цін з Prom по OEM-артикулу.
Prom — React/Apollo (JS-рендер), тож потрібен headless-браузер (Playwright).
Логіка: відкрити пошук по артикулу → зчитати картки → виключити свій магазин →
взяти ціну ПЕРШОЇ позиції-конкурента (за рейтингом) + найдешевшого. Пише competitors.csv.
Селектори перевірені на живій видачі Prom (04.07.2026)."""
import re, time, csv
SELF_STORE = "Vision Dynamics"
SEARCH_URL = "https://prom.ua/ua/search?search_term={art}"
def parse_price(t):
    if not t: return None
    t=t.replace('\xa0',' ')
    m=re.search(r'(\d[\d ]*)\s*₴', t)
    if not m: return None
    n=re.sub(r'\D','',m.group(1))
    return int(n) if n else None
def _is_instock(a):
    a=(a or "").lower(); return ("наявн" in a) or ("відправк" in a)
def pick_competitors(cards, self_store=SELF_STORE):
    """cards: [{name,price,seller,avail}] у порядку видачі. -> (перший_конкурент, найдешевший)."""
    comp=[]
    for c in cards:
        s=(c.get("seller") or "")
        if not s or self_store.lower() in s.lower(): continue
        p=parse_price(c.get("price"))
        if not p: continue
        comp.append({"price":p,"seller":s,"avail":_is_instock(c.get("avail"))})
    if not comp: return None,None
    instock=[c for c in comp if c["avail"]] or comp
    return instock[0]["price"], min(c["price"] for c in instock)
def scrape(articles, out_csv="feed/competitors.csv", delay=2.5, headless=True):
    from playwright.sync_api import sync_playwright
    rows=[]
    with sync_playwright() as p:
        br=p.chromium.launch(headless=headless); pg=br.new_page()
        for art in articles:
            first=mn=None
            try:
                pg.goto(SEARCH_URL.format(art=art), timeout=30000)
                pg.wait_for_selector('[data-qaid="product_block"]', timeout=8000)
                cards=[]
                for c in pg.query_selector_all('[data-qaid="product_block"]'):
                    g=lambda sel:(c.query_selector(sel).inner_text().strip() if c.query_selector(sel) else None)
                    cards.append({"name":g('[data-qaid="product_name"]'),"price":g('[data-qaid="product_price"]'),
                                  "seller":g('[data-qaid="company_name"]'),"avail":g('[data-qaid="presence"]')})
                first,mn=pick_competitors(cards)
            except Exception as e:
                print(f"[scrape] {art}: {str(e)[:60]}")
            rows.append({"article":art,"competitor_first":first or "","competitor_min":mn or ""})
            time.sleep(delay)
        br.close()
    with open(out_csv,"w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=["article","competitor_first","competitor_min"]); w.writeheader(); w.writerows(rows)
    print(f"[scrape] готово: {len(rows)} артикулів → {out_csv}")
    return rows
