# -*- coding: utf-8 -*-
"""MODE=review: bulk-фід BM Parts -> нові коди (нема в Export) -> вкладка «Огляд_Додавання»
з фото, ціною, наявністю і чекбоксом «Взяти»."""
import csv
import io
import os

from common.bmparts_client import BMParts
from common.config import EXPORT_TAB, REVIEW_TAB
from common.sheets import find_ws, keyf

BRAND = os.environ.get("BRAND", "BMW").strip()
MAX = int(os.environ.get("MAX", "0"))


def avail_h(v):
    v = str(v or "").strip()
    if v in ("+", "!", "true", "True"):
        return "✅ в наявності"
    if v.isdigit() and v != "0":
        return f"під замовл. ~{v} дн"
    if v in ("0", "-", ""):
        return "немає"
    return v


def _feed_index(fh):
    fi = {keyf(h): i for i, h in enumerate(fh)}

    def col(*ns, d=None):
        for n in ns:
            if keyf(n) in fi:
                return fi[keyf(n)]
        return d
    return col


def fetch_stock(bm):
    """{код: (Наявність, Кількість)} з bulk-фіду BM Parts (get_product їх не віддає)."""
    stock = {}
    try:
        wh = os.environ.get("WAREHOUSES", "").split(",") if os.environ.get("WAREHOUSES") \
            else [w["uuid"] for w in bm.warehouses()]
        wh = [w for w in wh if w]
        rows = list(csv.reader(io.StringIO(bm.prom_price_csv(BRAND, wh))))
        col = _feed_index(rows[0])
        ic, ia, iq = col("Код_товару", d=0), col("Наявність"), col("Кількість")
        g = lambda r, i: (r[i] if (i is not None and i < len(r)) else "")
        for r in rows[1:]:
            if len(r) > ic and r[ic]:
                stock[keyf(r[ic])] = (g(r, ia).strip(), g(r, iq).strip())
        print(f"[add] фід наявності: {len(stock)} кодів")
    except Exception as e:
        print(f"[add] фід наявності недоступний ({e}) — Наявність лишиться '+', Кількість порожня")
    return stock


def do_review(sh):
    export = find_ws(sh, EXPORT_TAB)
    ex_codes = {keyf(r[0]) for r in export.get_all_values()[1:] if r and r[0]}
    print(f"[add] Export: {len(ex_codes)} наявних кодів")
    bm = BMParts()
    wh = os.environ.get("WAREHOUSES", "").split(",") if os.environ.get("WAREHOUSES") \
        else [w["uuid"] for w in bm.warehouses()]
    wh = [w for w in wh if w]
    rows = list(csv.reader(io.StringIO(bm.prom_price_csv(BRAND, wh))))
    fh = rows[0]
    print(f"[add] фід {BRAND}: {len(rows)-1} рядків")
    col = _feed_index(fh)
    c_code, c_name = col("Код_товару", d=0), col("Назва_позиції_укр", "Назва_позиції", d=1)
    c_price, c_avail, c_qty, c_photo = col("Ціна"), col("Наявність"), col("Кількість"), col("Посилання_зображення")
    char_pairs = [(i, i + 1) for i, h in enumerate(fh)
                  if keyf(h) == keyf("Назва_Характеристики") and i + 1 < len(fh)]
    g = lambda r, i: (r[i] if (i is not None and i < len(r)) else "")

    new, seen = [], set()
    for r in rows[1:]:
        if not r or len(r) <= c_code:
            continue
        code = keyf(r[c_code])
        if not code or code in ex_codes or code in seen:
            continue
        seen.add(code)
        new.append(r)
        if MAX and len(new) >= MAX:
            break
    print(f"[add] НОВИХ (нема в Export): {len(new)}")
    if not new:
        return

    rv = find_ws(sh, REVIEW_TAB, create_cols=9)
    out = [["Фото", "Артикул", "Назва", "Ціна, ₴", "Наявність", "К-ть", "Характеристики", "Взяти", "Статус"]]
    for r in new:
        url = (g(r, c_photo) or "").split()[0] if g(r, c_photo) else ""
        photo = f'=IMAGE("{url}")' if url.startswith("http") else ""
        chars = []
        for ni, vi in char_pairs:
            nm, val = g(r, ni), g(r, vi)
            if nm and val:
                chars.append(f"{nm}: {val}")
            if len(chars) >= 4:
                break
        out.append([photo, g(r, c_code), g(r, c_name), g(r, c_price), avail_h(g(r, c_avail)),
                    g(r, c_qty), "; ".join(chars), False, ""])
    rv.clear()
    rv.update(values=out, range_name=f"A1:I{len(out)}", value_input_option="USER_ENTERED")
    n = len(out)
    rv.spreadsheet.batch_update({"requests": [
        {"setDataValidation": {"range": {"sheetId": rv.id, "startRowIndex": 1, "endRowIndex": n,
                                         "startColumnIndex": 7, "endColumnIndex": 8},
                               "rule": {"condition": {"type": "BOOLEAN"}, "strict": True}}},
        {"updateSheetProperties": {"properties": {"sheetId": rv.id, "gridProperties": {"frozenRowCount": 1}},
                                   "fields": "gridProperties.frozenRowCount"}},
        {"updateDimensionProperties": {"range": {"sheetId": rv.id, "dimension": "ROWS", "startIndex": 1, "endIndex": n},
                                       "properties": {"pixelSize": 60}, "fields": "pixelSize"}},
        {"updateDimensionProperties": {"range": {"sheetId": rv.id, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 1},
                                       "properties": {"pixelSize": 70}, "fields": "pixelSize"}},
        {"updateDimensionProperties": {"range": {"sheetId": rv.id, "dimension": "COLUMNS", "startIndex": 2, "endIndex": 3},
                                       "properties": {"pixelSize": 320}, "fields": "pixelSize"}},
        {"updateDimensionProperties": {"range": {"sheetId": rv.id, "dimension": "COLUMNS", "startIndex": 6, "endIndex": 7},
                                       "properties": {"pixelSize": 300}, "fields": "pixelSize"}},
    ]})
    print(f"[add] ✅ {len(new)} кандидатів у «{REVIEW_TAB}»")
    print(">>> Постав «Взяти» → MODE=enrich → якісні картки у Export.")
