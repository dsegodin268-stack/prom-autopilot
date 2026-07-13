#!/usr/bin/env python3
"""
enrich_selected.py — ШАР ЯКОСТІ воронки додавання.
Читає «Огляд_Додавання», бере рядки з галкою «Взяти»=TRUE, і для КОЖНОГО обраного
робить per-article get_product → ПОВНА картка (назва, ЯКІСНИЙ опис з OEM/сумісністю/
характеристиками, фото) → пише в «Export Products Sheet». Тільки обрані → без rate-limit.

ENV: GCP_SA_KEY, HUB_ID, BMPARTS_TOKEN, TARGET(export|staging, =export), MAX(опц.)
"""
import os, json, re, math
import gspread
from google.oauth2.service_account import Credentials
from bmparts import BMParts, assemble_card

HUB    = os.environ.get("HUB_ID", "1pesHiOHDq2Y4FYQECakfhIJlq08bg5_Pkm9e2YEDoic")
TARGET = os.environ.get("TARGET", "export").strip().lower()
MAX    = int(os.environ.get("MAX", "0"))
REVIEW_TAB = "Огляд_Додавання"

keyf = lambda s: re.sub(r"\s+", " ", str(s or "").strip().lower())
TRUE = {"true", "1", "так", "yes", "on", "✓"}

def find_ws(sh, name):
    want = keyf(name)
    for ws in sh.worksheets():
        if keyf(ws.title) == want: return ws
    for ws in sh.worksheets():
        if want in keyf(ws.title): return ws
    raise SystemExit(f"вкладку {name!r} не знайдено")

def main():
    creds = Credentials.from_service_account_info(
        json.loads(os.environ["GCP_SA_KEY"]),
        scopes=["https://www.googleapis.com/auth/spreadsheets"])
    sh = gspread.authorize(creds).open_by_key(HUB)

    rv = find_ws(sh, REVIEW_TAB)
    rows = rv.get_all_values()
    if not rows: raise SystemExit("огляд порожній")
    head = rows[0]
    def ci(name, d=None):
        for i,h in enumerate(head):
            if keyf(h)==keyf(name): return i
        return d
    c_art, c_take, c_stat = ci("Артикул",0), ci("Взяти",5), ci("Статус",6)

    selected = []
    for rn, r in enumerate(rows[1:], start=2):
        if len(r) <= c_take: continue
        take = keyf(r[c_take]) in TRUE
        done = keyf(r[c_stat] if len(r)>c_stat else "").startswith("додан")
        if take and not done and r[c_art].strip():
            selected.append((rn, r[c_art].strip()))
    if MAX: selected = selected[:MAX]
    print(f"[enrich_sel] обрано галочкою: {len(selected)}")
    if not selected:
        print("[enrich_sel] нема відмічених — постав галки «Взяти»"); return

    export = find_ws(sh, "Export Products Sheet")
    ex_head = export.get_all_values()[0]
    def ex_i(*names):
        for n in names:
            for i,h in enumerate(ex_head):
                if keyf(h)==keyf(n): return i
        return None
    IX = {k: ex_i(*v) for k,v in {
        "code":["Код_товару"], "name":["Назва_позиції"], "name_ua":["Назва_позиції_укр"],
        "desc":["Опис"], "desc_ua":["Опис_укр"], "price":["Ціна"], "avail":["Наявність"],
        "qty":["Кількість"], "photo":["Посилання_зображення"], "unit":["Одиниця_виміру"],
    }.items()}

    bm = BMParts()
    new_rows, done_rn = [], []
    for rn, art in selected:
        try:
            prod = bm.get_product(art)
            if not prod:
                print(f"[enrich_sel] {art}: не знайдено в BM Parts"); continue
            card = assemble_card(prod)
            row = [""] * len(ex_head)
            def put(key, val):
                i = IX.get(key)
                if i is not None and i < len(row): row[i] = val
            put("code", art); put("name", card["name"]); put("name_ua", card["name"])
            put("desc", card["description"]); put("desc_ua", card["description"])
            put("price", card.get("price") or ""); put("avail", "+"); put("qty", "1")
            put("unit", "шт.")
            put("photo", ", ".join(card.get("images") or []))
            new_rows.append(row); done_rn.append(rn)
            print(f"[enrich_sel] ✅ {art} | {card['name'][:45]} | фото {len(card.get('images') or [])} | опис {len(card['description'])} симв.")
        except Exception as e:
            print(f"[enrich_sel] {art}: ПОМИЛКА {e}")

    if not new_rows:
        print("[enrich_sel] нічого не зібрано"); return
    dest = export if TARGET=="export" else find_ws(sh, "Staging_Prom")
    dest.append_rows(new_rows, value_input_option="RAW")
    print(f"[enrich_sel] ✅ дописано {len(new_rows)} ЯКІСНИХ карток у «{dest.title}»")
    # позначити статус
    for rn in done_rn:
        rv.update_cell(rn, c_stat+1, "додано")
    print(f"[enrich_sel] позначено {len(done_rn)} як «додано» в огляді")

if __name__ == "__main__":
    main()
