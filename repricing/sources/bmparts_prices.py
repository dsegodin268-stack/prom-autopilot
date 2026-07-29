# -*- coding: utf-8 -*-
"""Джерело 6 (останній щабель водоспаду): BM Parts API.
Основний шлях — POST /prices/list (УСІ бренди одним запитом, ~125k позицій).
Fallback — per-brand /prices/prom/{brand} (історично віддає 0, лишений про запас)."""
import io
import os

from common.normalize import num, _nkey
from repricing.sources.base import keep_best


def _bmparts_list_map():
    """{article(UPPER,нормалізований): {'price','qty','presence'}} з /prices/list."""
    token = os.environ.get("BMPARTS_TOKEN")
    if not token:
        return {}
    import csv as _csv
    try:
        from common.bmparts_client import BMParts
        bm = BMParts(token)
        whs = [w.get("uuid") for w in bm.warehouses() if w.get("uuid")]
    except Exception as e:
        print(f"[bmparts] list init FAIL: {str(e)[:100]}")
        return {}
    try:
        r = bm.s.post("https://api.bm.parts/prices/list",
                      json={"warehouses": whs, "format": "csv", "products_type": "code"}, timeout=180)
        if r.status_code != 200:
            print(f"[bmparts] /prices/list HTTP {r.status_code}")
            return {}
        text = r.text
    except Exception as e:
        print(f"[bmparts] /prices/list FAIL: {str(e)[:100]}")
        return {}
    sample = text[:2000]
    delim = ";" if sample.count(";") >= sample.count(",") else ","
    rows = list(_csv.reader(io.StringIO(text), delimiter=delim))
    if len(rows) < 2:
        print("[bmparts] /prices/list порожній")
        return {}
    head = [h.strip().lower() for h in rows[0]]

    def col(*keys):
        for i, h in enumerate(head):
            if any(k in h for k in keys):
                return i
        return -1

    ci = col("код_товару", "код товару", "артикул", "article", "код", "ідентифікатор")
    cp = col("ціна", "price")
    cav = col("наявн", "availab", "presence")
    cq = col("кільк", "quantity", "qty", "залиш", "остат")
    if ci < 0 or cp < 0:
        print(f"[bmparts] /prices/list: колонки не розпізнані {head[:8]}")
        return {}
    # Окремої колонки «наявність/кількість» у /prices/list НЕМА (проба #9, 29.07):
    # шапка = ІД,Артикул,Бренд,Назва,Ціна ГРН, далі ПО КОЛОНЦІ НА СКЛАД
    # («Київ Бровари ДАГ», …), значення «-» = нема, число = залишок.
    # Саме тому нічний прогін бачив «у наявності: 0». Рахуємо суму по складах.
    wh_cols = list(range(cp + 1, len(head)))
    out = {}
    for r in rows[1:]:
        if ci >= len(r) or cp >= len(r):
            continue
        art = _nkey(r[ci])
        price = num(r[cp])
        if not art or price <= 0:
            continue
        qty = num(r[cq]) if 0 <= cq < len(r) else 0
        if qty <= 0 and wh_cols:
            qty = sum(num(r[j]) for j in wh_cols if j < len(r))
        av = (r[cav].strip().lower() if 0 <= cav < len(r) else "")
        available = ("наявн" in av or av in ("+", "true", "1", "в наявності", "у наявності")) or qty > 0
        if art not in out or price < out[art]["price"]:
            out[art] = {"price": price, "qty": int(qty), "presence": "available" if available else "order"}
    print(f"[bmparts] /prices/list: {len(out)} унікальних артикулів (одним запитом)")
    return out


def _bmparts_price_map(brands=None):
    """Спершу /prices/list; якщо 0 — fallback на per-brand /prices/prom."""
    if not brands and not os.environ.get("BMPARTS_BRANDS"):
        _m = _bmparts_list_map()
        if _m:
            return _m
        print("[bmparts] /prices/list дав 0 — fallback на per-brand /prices/prom")
    token = os.environ.get("BMPARTS_TOKEN")
    if not token:
        print("[bmparts] нема BMPARTS_TOKEN — пропуск")
        return {}
    import csv as _csv
    try:
        from common.bmparts_client import BMParts
    except Exception as e:
        print(f"[bmparts] import не вдався: {str(e)[:90]}")
        return {}
    try:
        bm = BMParts(token)
        whs = [w.get("uuid") for w in bm.warehouses() if w.get("uuid")]
    except Exception as e:
        print(f"[bmparts] warehouses FAIL: {str(e)[:100]}")
        return {}
    if not brands:
        env = os.environ.get("BMPARTS_BRANDS")
        if env:
            brands = [b.strip() for b in env.split(",") if b.strip()]
        else:
            try:
                rr = bm.s.get("https://api.bm.parts/catalog/cars/brands/", timeout=60)
                rr.raise_for_status()
                brands = [b.get("name") for b in (rr.json().get("car_brands") or []) if b.get("name")]
                print(f"[bmparts] авто-марок у каталозі: {len(brands)}")
            except Exception as e:
                print(f"[bmparts] список авто-марок FAIL: {str(e)[:100]} — лишаю BMW")
                brands = ["BMW"]
    out = {}
    brands_hit = 0
    for brand in brands:
        try:
            text = bm.prom_price_csv(brand, whs)
        except Exception:
            continue
        sample = text[:2000]
        delim = ";" if sample.count(";") >= sample.count(",") else ","
        rows = list(_csv.reader(io.StringIO(text), delimiter=delim))
        if len(rows) < 2:
            continue
        head = [h.strip().lower() for h in rows[0]]

        def col(*keys):
            for i, h in enumerate(head):
                if any(k in h for k in keys):
                    return i
            return -1

        ci = col("код_товару", "код товару", "артикул", "article", "ідентифікатор")
        cp = col("ціна", "price")
        cav = col("наявн", "availab", "presence")
        cq = col("кільк", "quantity", "qty", "залиш", "остат")
        if ci < 0 or cp < 0:
            continue
        n = 0
        for r in rows[1:]:
            if ci >= len(r) or cp >= len(r):
                continue
            art = _nkey(r[ci])
            price = num(r[cp])
            if not art or price <= 0:
                continue
            qty = num(r[cq]) if 0 <= cq < len(r) else 0
            av = (r[cav].strip().lower() if 0 <= cav < len(r) else "")
            available = ("наявн" in av or av in ("+", "true", "1", "в наявності", "у наявності")) or qty > 0
            if art not in out or price < out[art]["price"]:
                out[art] = {"price": price, "qty": int(qty), "presence": "available" if available else "order"}
            n += 1
        if n:
            brands_hit += 1
            print(f"[bmparts] {brand}: {n}")
    print(f"[bmparts] мапа: {len(out)} унікальних артикулів по {brands_hit} марках (із {len(brands or [])})")
    return out


def pull_bmparts(codes, best, instock, brands=None):
    """Матч по нормалізованому коду: цілий код, потім номер до тире."""
    import re as _re
    pm = _bmparts_price_map(brands)
    if not pm:
        print("[bmparts] мапа порожня — нічого не додано")
        return
    n_ok = n_avail = 0
    for code in codes:
        rec = pm.get(_nkey(code)) or pm.get(_nkey(_re.split(r"[-–—]", str(code))[0]))
        if not rec:
            continue
        av = (rec["presence"] == "available" and rec["qty"] > 0)
        # BM Parts /prices/list не віддає термін для позицій під замовлення -> дефолт (15 у export)
        keep_best(best, str(code).strip().upper(),
                  {"name": "", "cost": rec["price"], "qty": int(rec["qty"]) if av else 0,
                   "days": 0, "presence": "available" if av else "order", "brand": "BM Parts"}, instock)
        n_ok += 1
        if av:
            n_avail += 1
    print(f"[bmparts] додано {n_ok} кодів (у наявності: {n_avail})")
