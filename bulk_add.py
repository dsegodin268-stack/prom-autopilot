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
        header = ["Артикул", "Назва", "Ціна", "Наявність", "Фото", "Взяти", "Статус", "Бренд"]
        out = [header]
        for r in new:
            photo = (g(r, c_photo) or "").split()[0] if g(r, c_photo) else ""
            out.append([g(r, c_code), g(r, c_name), g(r, c_price), g(r, c_avail),
                        photo, False, "", BRAND])
        rv.clear()
        rv.update(f"A1:H{len(out)}", out, value_input_option="USER_ENTERED")
        # чекбокси на колонку «Взяти» (F, індекс 5)
        rv.spreadsheet.batch_update({"requests": [{
            "setDataValidation": {
                "range": {"sheetId": rv.id, "startRowIndex": 1, "endRowIndex": len(out),
                          "startColumnIndex": 5, "endColumnIndex": 6},
                "rule": {"condition": {"type": "BOOLEAN"}, "strict": True}}}]})
        print(f"[bulk_add] ✅ {len(new)} кандидатів у «{REVIEW_TAB}» з чекбоксом «Взяти»")
        for r in new[:5]:
            print("  •", g(r, c_code), "|", (g(r, c_name) or "")[:50])
        print(">>> Постав галку «Взяти» на потрібних → обрані якісно збагатяться і підуть в Export.")
    else:
        ex_map = [fidx.get(keyf(h)) for h in ex_header]
        full = [[g(r, j) for j in ex_map] for r in new]
        dest = export if TARGET == "export" else find_ws(sh, "Staging_Prom")
        dest.append_rows(full, value_input_option="RAW")
        print(f"[bulk_add] ✅ дописано {len(full)} у «{dest.title}»")

if __name__ == "__main__":
    main()
