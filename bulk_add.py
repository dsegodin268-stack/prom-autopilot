#!/usr/bin/env python3
"""
bulk_add.py — ПРАВИЛЬНЕ додавання позицій: один bulk-виклик BM Parts /prices/prom/{brand}
повертає весь бренд у форматі імпорту Prom (назва, опис, фото, ціна, наявність, характеристики).
Далі: дедуп проти «Export Products Sheet» і запис НОВИХ рядків.

Ніякого per-article search/enrich, ніякого rate-limit — 1 виклик на бренд.

ENV: GCP_SA_KEY, HUB_ID, BMPARTS_TOKEN, BRAND(=BMW), TARGET(staging|export, =staging),
     MAX(опц. ліміт нових рядків), WAREHOUSES(опц. CSV UUID; інакше всі склади)
"""
import os, io, csv, json, re
import gspread
from google.oauth2.service_account import Credentials
from bmparts import BMParts

HUB   = os.environ.get("HUB_ID", "1pesHiOHDq2Y4FYQECakfhIJlq08bg5_Pkm9e2YEDoic")
BRAND = os.environ.get("BRAND", "BMW").strip()
TARGET= os.environ.get("TARGET", "staging").strip().lower()
MAX   = int(os.environ.get("MAX", "0"))

keyf = lambda s: re.sub(r"\s+", " ", str(s or "").strip().lower())

def find_ws(sh, name):
    want = keyf(name)
    for ws in sh.worksheets():
        if keyf(ws.title) == want:
            return ws
    for ws in sh.worksheets():
        if want in keyf(ws.title):
            return ws
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

    # --- bulk-фід BM Parts ---
    bm = BMParts()
    whs = bm.warehouses()
    wh = os.environ.get("WAREHOUSES", "").split(",") if os.environ.get("WAREHOUSES") else [w["uuid"] for w in whs]
    wh = [w for w in wh if w]
    print(f"[bulk_add] складів={len(wh)}, бренд={BRAND}")
    raw = bm.prom_price_csv(BRAND, wh)
    rows = list(csv.reader(io.StringIO(raw)))
    if not rows:
        raise SystemExit("порожній фід")
    feed_header = rows[0]
    print(f"[bulk_add] фід: {len(rows)-1} рядків, {len(feed_header)} колонок")

    # індекс колонок фіду за іменем заголовка (перше входження)
    fidx = {}
    for i, h in enumerate(feed_header):
        fidx.setdefault(keyf(h), i)
    code_col = fidx.get(keyf("Код_товару"), 0)

    # мапимо КОЖЕН заголовок Export ← значення фіду з тим самим іменем
    ex_map = [fidx.get(keyf(h)) for h in ex_header]

    new_rows = []
    seen = set()
    for r in rows[1:]:
        if not r or len(r) <= code_col:
            continue
        code = keyf(r[code_col])
        if not code or code in ex_codes or code in seen:
            continue
        seen.add(code)
        out = [(r[j] if (j is not None and j < len(r)) else "") for j in ex_map]
        new_rows.append(out)
        if MAX and len(new_rows) >= MAX:
            break

    print(f"[bulk_add] НОВИХ (нема в Export): {len(new_rows)}")
    if not new_rows:
        print("[bulk_add] нема що додавати"); return

    if TARGET == "export":
        export.append_rows(new_rows, value_input_option="RAW")
        print(f"[bulk_add] ✅ дописано {len(new_rows)} у «Export Products Sheet»")
    else:
        stg = find_ws(sh, "Staging_Prom")
        stg.append_rows(new_rows, value_input_option="RAW")
        print(f"[bulk_add] ✅ дописано {len(new_rows)} у «Staging_Prom» (на огляд)")

    for r in new_rows[:5]:
        print("  +", r[0], "|", (r[1] or "")[:50])

if __name__ == "__main__":
    main()
