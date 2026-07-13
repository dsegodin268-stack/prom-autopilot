#!/usr/bin/env python3
"""
add_positions.py — ЄДИНИЙ скрипт додавання позицій BM Parts (2 режими).
Замінює bulk_add.py + enrich_selected.py. Наповнення СУВОРО за ПРАВИЛА_PROM
(перевикористовує build_fields з enrich_add.py — не дублюємо).

MODE=review  : один bulk-виклик /prices/prom/{brand} → нові (нема в Export) → «Огляд_Додавання»
               (фото-мініатюра, назва, ціна, читабельна наявність, характеристики, ☐«Взяти»).
MODE=enrich  : читає «Огляд_Додавання» → рядки з «Взяти»=TRUE → per-article get_product →
               build_fields (ПРАВИЛА_PROM) → повний рядок Prom → «Export Products Sheet».

ENV: GCP_SA_KEY, BMPARTS_TOKEN, MODE(review|enrich), BRAND(=BMW),
     TARGET(export|staging, для enrich; =export), MAX(опц.), HUB_ID(опц.)
"""
import os, io, csv, json, re
import gspread
from google.oauth2.service_account import Credentials
from bmparts import BMParts
from enrich_add import build_fields                     # rules-builder, не дублюємо

HUB    = os.environ.get("HUB_ID", "1pesHiOHDq2Y4FYQECakfhIJlq08bg5_Pkm9e2YEDoic")
MODE   = os.environ.get("MODE", "review").strip().lower()
BRAND  = os.environ.get("BRAND", "BMW").strip()
TARGET = os.environ.get("TARGET", "export").strip().lower()
MAX    = int(os.environ.get("MAX", "0"))
REVIEW_TAB = "Огляд_Додавання"
keyf = lambda s: re.sub(r"\s+", " ", str(s or "").strip().lower())
TRUE = {"true", "1", "так", "yes", "on", "✓"}

def gc_open():
    creds = Credentials.from_service_account_info(
        json.loads(os.environ["GCP_SA_KEY"]),
        scopes=["https://www.googleapis.com/auth/spreadsheets"])
    return gspread.authorize(creds).open_by_key(HUB)

def find_ws(sh, name, create_cols=0):
    want = keyf(name)
    for ws in sh.worksheets():
        if keyf(ws.title) == want: return ws
    for ws in sh.worksheets():
        if want in keyf(ws.title): return ws
    if create_cols:
        return sh.add_worksheet(name, rows=2000, cols=create_cols)
    raise SystemExit(f"вкладку {name!r} не знайдено")

def avail_h(v):
    v = str(v or "").strip()
    if v in ("+", "!", "true", "True"): return "✅ в наявності"
    if v.isdigit() and v != "0":        return f"під замовл. ~{v} дн"
    if v in ("0", "-", ""):             return "немає"
    return v

# ---------------- MODE=review ----------------
def do_review(sh):
    export = find_ws(sh, "Export Products Sheet")
    ex_codes = {keyf(r[0]) for r in export.get_all_values()[1:] if r and r[0]}
    print(f"[add] Export: {len(ex_codes)} наявних кодів")
    bm = BMParts()
    wh = os.environ.get("WAREHOUSES", "").split(",") if os.environ.get("WAREHOUSES") else [w["uuid"] for w in bm.warehouses()]
    wh = [w for w in wh if w]
    rows = list(csv.reader(io.StringIO(bm.prom_price_csv(BRAND, wh))))
    fh = rows[0]; print(f"[add] фід {BRAND}: {len(rows)-1} рядків")
    fidx = {}
    for i, h in enumerate(fh): fidx.setdefault(keyf(h), i)
    def col(*ns, d=None):
        for n in ns:
            if keyf(n) in fidx: return fidx[keyf(n)]
        return d
    c_code, c_name = col("Код_товару", d=0), col("Назва_позиції_укр","Назва_позиції", d=1)
    c_price, c_avail, c_photo = col("Ціна"), col("Наявність"), col("Посилання_зображення")
    char_pairs = [(i, i+1) for i, h in enumerate(fh) if keyf(h)==keyf("Назва_Характеристики") and i+1 < len(fh)]
    g = lambda r, i: (r[i] if (i is not None and i < len(r)) else "")

    new, seen = [], set()
    for r in rows[1:]:
        if not r or len(r) <= c_code: continue
        code = keyf(r[c_code])
        if not code or code in ex_codes or code in seen: continue
        seen.add(code); new.append(r)
        if MAX and len(new) >= MAX: break
    print(f"[add] НОВИХ (нема в Export): {len(new)}")
    if not new: return

    rv = find_ws(sh, REVIEW_TAB, create_cols=8)
    out = [["Фото","Артикул","Назва","Ціна, ₴","Наявність","Характеристики","Взяти","Статус"]]
    for r in new:
        url = (g(r, c_photo) or "").split()[0] if g(r, c_photo) else ""
        photo = f'=IMAGE("{url}")' if url.startswith("http") else ""
        chars = []
        for ni, vi in char_pairs:
            nm, val = g(r, ni), g(r, vi)
            if nm and val: chars.append(f"{nm}: {val}")
            if len(chars) >= 4: break
        out.append([photo, g(r,c_code), g(r,c_name), g(r,c_price), avail_h(g(r,c_avail)),
                    "; ".join(chars), False, ""])
    rv.clear()
    rv.update(f"A1:H{len(out)}", out, value_input_option="USER_ENTERED")
    n = len(out)
    rv.spreadsheet.batch_update({"requests": [
        {"setDataValidation": {"range": {"sheetId": rv.id, "startRowIndex":1, "endRowIndex":n,
            "startColumnIndex":6, "endColumnIndex":7}, "rule": {"condition":{"type":"BOOLEAN"}, "strict":True}}},
        {"updateSheetProperties": {"properties": {"sheetId": rv.id, "gridProperties":{"frozenRowCount":1}},
            "fields": "gridProperties.frozenRowCount"}},
        {"updateDimensionProperties": {"range": {"sheetId": rv.id, "dimension":"ROWS", "startIndex":1, "endIndex":n},
            "properties": {"pixelSize":60}, "fields":"pixelSize"}},
        {"updateDimensionProperties": {"range": {"sheetId": rv.id, "dimension":"COLUMNS", "startIndex":0, "endIndex":1},
            "properties": {"pixelSize":70}, "fields":"pixelSize"}},
        {"updateDimensionProperties": {"range": {"sheetId": rv.id, "dimension":"COLUMNS", "startIndex":2, "endIndex":3},
            "properties": {"pixelSize":320}, "fields":"pixelSize"}},
        {"updateDimensionProperties": {"range": {"sheetId": rv.id, "dimension":"COLUMNS", "startIndex":5, "endIndex":6},
            "properties": {"pixelSize":300}, "fields":"pixelSize"}},
    ]})
    print(f"[add] ✅ {len(new)} кандидатів у «{REVIEW_TAB}»: фото + наявність + характеристики + ☐«Взяти»")
    print(">>> Постав «Взяти» → запусти MODE=enrich → обрані з якісними картками (ПРАВИЛА_PROM) у Export.")

# ---------------- MODE=enrich ----------------
def do_enrich(sh):
    rv = find_ws(sh, REVIEW_TAB); rows = rv.get_all_values()
    if not rows: raise SystemExit("огляд порожній")
    head = rows[0]
    def ci(name, d=None):
        for i,h in enumerate(head):
            if keyf(h)==keyf(name): return i
        return d
    c_art, c_take, c_stat = ci("Артикул",1), ci("Взяти",6), ci("Статус",7)
    selected = []
    for rn, r in enumerate(rows[1:], start=2):
        if len(r) <= c_take: continue
        art = r[c_art].strip() if len(r)>c_art else ""
        done = keyf(r[c_stat] if len(r)>c_stat else "").startswith("додан")
        if keyf(r[c_take]) in TRUE and not done and art: selected.append((rn, art))
    if MAX: selected = selected[:MAX]
    print(f"[add] відмічено «Взяти»: {len(selected)}")
    if not selected:
        print("[add] нема відмічених — постав галки «Взяти»"); return

    export = find_ws(sh, "Export Products Sheet"); ex_head = export.get_all_values()[0]
    bm = BMParts(); new_rows, done_rn = [], []
    for rn, art in selected:
        try:
            prod = bm.get_product(art)
            if not prod: print(f"[add] {art}: не знайдено в BM Parts"); continue
            prod.setdefault("article", art)
            f, name_ua, imgs, details, price = build_fields(prod)          # ПРАВИЛА_PROM
            new_rows.append([f.get(h, "") for h in ex_head]); done_rn.append(rn)
            print(f"[add] ✅ {art} | {name_ua[:40]} | опис {len(f.get('Опис_укр',''))}c | тегів {f.get('Пошукові_запити_укр','').count(',')+1} | фото {len(imgs)} | ціна {price}")
        except Exception as e:
            print(f"[add] {art}: ПОМИЛКА {e}")
    if not new_rows: print("[add] нічого не зібрано"); return
    dest = export if TARGET=="export" else find_ws(sh, "Staging_Prom")
    dest.append_rows(new_rows, value_input_option="RAW")
    print(f"[add] ✅ дописано {len(new_rows)} ЯКІСНИХ карток (ПРАВИЛА_PROM) у «{dest.title}»")
    for rn in done_rn: rv.update_cell(rn, c_stat+1, "додано")

def main():
    sh = gc_open()
    if MODE == "enrich": do_enrich(sh)
    else:                do_review(sh)

if __name__ == "__main__":
    main()
