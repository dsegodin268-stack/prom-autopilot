#!/usr/bin/env python3
"""
bulk_add.py — ВОРОНКА додавання позицій BM Parts:
  1) review (дефолт): один bulk-виклик /prices/prom/{brand} → КОМПАКТНИЙ список кандидатів
     (артикул, назва, ціна, наявність, фото) з чекбоксом «Взяти» у вкладці «Огляд_Додавання».
     Ти тікаєш потрібні → Apps Script onEdit збагачує обрані per-article і кладе в Export.
  2) staging / export: (за потреби) повний Prom-рядок одразу у Staging_Prom або Export.

Дедуп проти «Export Products Sheet». Один виклик на бренд, без rate-limit.

ENV: GCP_SA_KEY, HUB_ID, BMPARTS_TOKEN, BRAND(=BMW), TARGET(review|staging|export, =review),
     MAX(опц.), WAREHOUSES(опц. CSV UUID)
"""
import os, io, csv, json, re
import gspread
from google.oauth2.service_account import Credentials
from bmparts import BMParts

HUB   = os.environ.get("HUB_ID", "1pesHiOHDq2Y4FYQECakfhIJlq08bg5_Pkm9e2YEDoic")
BRAND = os.environ.get("BRAND", "BMW").strip()
TARGET= os.environ.get("TARGET", "review").strip().lower()
MAX   = int(os.environ.get("MAX", "0"))
REVIEW_TAB = "Огляд_Додавання"

keyf = lambda s: re.sub(r"\s+", " ", str(s or "").strip().lower())


def avail_h(v):
    v = str(v or "").strip()
    if v in ("+", "!", "true", "True"): return "✅ в наявності"
    if v.isdigit() and v != "0":        return f"під замовл. ~{v} дн"
    if v in ("0", "-", ""):             return "немає"
    return v

def find_ws(sh, name, create_cols=0):
    want = keyf(name)
    for ws in sh.worksheets():
        if keyf(ws.title) == want:
            return ws
    for ws in sh.worksheets():
        if want in keyf(ws.title):
            return ws
    if create_cols:
        return sh.add_worksheet(name, rows=2000, cols=create_cols)
    raise SystemExit(f"вкладку {name!r} не знайдено")

def main():
    creds = Credentials.from_service_account_info(
        json.loads(os.environ["GCP_SA_KEY"]),
        scopes=["https://www.googleapis.com/auth/spreadsheets"])
    sh = gspread.authorize(creds).open_by_key(HUB)

    export = find_ws(sh, "Export Products Sheet")
    ex_vals = export.get_all_values()
    ex_header = ex_vals[0] if ex_vals else []
    ex_codes = {keyf(r[0]) for r in ex_vals[1:] if r and r[0]}
    print(f"[bulk_add] Export: {len(ex_header)} колонок, {len(ex_codes)} наявних кодів")

    bm = BMParts()
    whs = bm.warehouses()
    wh = os.environ.get("WAREHOUSES", "").split(",") if os.environ.get("WAREHOUSES") else [w["uuid"] for w in whs]
    wh = [w for w in wh if w]
    print(f"[bulk_add] складів={len(wh)}, бренд={BRAND}")
    rows = list(csv.reader(io.StringIO(bm.prom_price_csv(BRAND, wh))))
    if not rows:
        raise SystemExit("порожній фід")
    fh = rows[0]
    print(f"[bulk_add] фід: {len(rows)-1} рядків, {len(fh)} колонок")

    fidx = {}
    for i, h in enumerate(fh):
        fidx.setdefault(keyf(h), i)
    def col(*names, default=None):
        for n in names:
            if keyf(n) in fidx: return fidx[keyf(n)]
        return default
    c_code  = col("Код_товару", default=0)
    c_name  = col("Назва_позиції_укр", "Назва_позиції", default=1)
    c_price = col("Ціна")
    c_avail = col("Наявність")
    c_photo = col("Посилання_зображення")
    char_pairs = []                                   # (idx назви, idx значення) характеристик
    for i, h in enumerate(fh):
        if keyf(h) == keyf("Назва_Характеристики") and i + 1 < len(fh):
            char_pairs.append((i, i + 1))

    # відбір нових
    new = []
    seen = set()
    for r in rows[1:]:
        if not r or len(r) <= c_code: continue
        code = keyf(r[c_code])
        if not code or code in ex_codes or code in seen: continue
        seen.add(code); new.append(r)
        if MAX and len(new) >= MAX: break
    print(f"[bulk_add] НОВИХ (нема в Export): {len(new)}")
    if not new:
        print("[bulk_add] нема що додавати"); return

    def g(r, i):
        return r[i] if (i is not None and i < len(r)) else ""

    if TARGET == "review":
        rv = find_ws(sh, REVIEW_TAB, create_cols=8)
        header = ["Фото", "Артикул", "Назва", "Ціна, ₴", "Наявність", "Характеристики", "Взяти", "Статус"]
        out = [header]
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
            out.append([photo, g(r, c_code), g(r, c_name), g(r, c_price),
                        avail_h(g(r, c_avail)), "; ".join(chars), False, ""])
        rv.clear()
        rv.update(f"A1:H{len(out)}", out, value_input_option="USER_ENTERED")
        n = len(out)
        rv.spreadsheet.batch_update({"requests": [
            {"setDataValidation": {                              # чекбокс «Взяти» (кол. G)
                "range": {"sheetId": rv.id, "startRowIndex": 1, "endRowIndex": n,
                          "startColumnIndex": 6, "endColumnIndex": 7},
                "rule": {"condition": {"type": "BOOLEAN"}, "strict": True}}},
            {"updateSheetProperties": {                          # заморозити шапку
                "properties": {"sheetId": rv.id, "gridProperties": {"frozenRowCount": 1}},
                "fields": "gridProperties.frozenRowCount"}},
            {"updateDimensionProperties": {                      # висота рядків під фото
                "range": {"sheetId": rv.id, "dimension": "ROWS", "startIndex": 1, "endIndex": n},
                "properties": {"pixelSize": 60}, "fields": "pixelSize"}},
            {"updateDimensionProperties": {                      # ширина «Фото»
                "range": {"sheetId": rv.id, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 1},
                "properties": {"pixelSize": 70}, "fields": "pixelSize"}},
            {"updateDimensionProperties": {                      # ширина «Назва»
                "range": {"sheetId": rv.id, "dimension": "COLUMNS", "startIndex": 2, "endIndex": 3},
                "properties": {"pixelSize": 320}, "fields": "pixelSize"}},
            {"updateDimensionProperties": {                      # ширина «Характеристики»
                "range": {"sheetId": rv.id, "dimension": "COLUMNS", "startIndex": 5, "endIndex": 6},
                "properties": {"pixelSize": 300}, "fields": "pixelSize"}},
        ]})
        print(f"[bulk_add] ✅ {len(new)} кандидатів у «{REVIEW_TAB}»: фото + читабельна наявність + характеристики + чекбокс «Взяти»")
        print(">>> Постав галку «Взяти» → запусти workflow enrich-selected → обрані з якісними картками підуть у Export.")
    else:
        ex_map = [fidx.get(keyf(h)) for h in ex_header]
        full = [[g(r, j) for j in ex_map] for r in new]
        dest = export if TARGET == "export" else find_ws(sh, "Staging_Prom")
        dest.append_rows(full, value_input_option="RAW")
        print(f"[bulk_add] ✅ дописано {len(full)} у «{dest.title}»")

if __name__ == "__main__":
    main()
