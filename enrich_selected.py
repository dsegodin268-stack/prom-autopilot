#!/usr/bin/env python3
"""
enrich_selected.py — ШАР ЯКОСТІ воронки. Наповнення СУВОРО за ПРАВИЛА_PROM.md:
перевикористовує наявний build_fields() з enrich_add.py (rich HTML-опис з авто/сумісністю/
OEM/аналогами/характеристиками/CTA, пошукові теги, meta-заголовок/опис, чиста назва, тарифна ціна).

Читає «Огляд_Додавання» → рядки з галкою «Взяти»=TRUE → per-article get_product →
build_fields → повний рядок Prom → «Export Products Sheet». Тільки обрані → без rate-limit.

ENV: GCP_SA_KEY, HUB_ID, BMPARTS_TOKEN, TARGET(export|staging, =export), MAX(опц.)
"""
import os, json, re
import gspread
from google.oauth2.service_account import Credentials
from bmparts import BMParts
from enrich_add import build_fields          # ← rules-builder, не дублюємо

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
        take = keyf(r[c_take]) in TRUE
        done = keyf(r[c_stat] if len(r)>c_stat else "").startswith("додан")
        art = r[c_art].strip() if len(r)>c_art else ""
        if take and not done and art:
            selected.append((rn, art))
    if MAX: selected = selected[:MAX]
    print(f"[enrich_sel] відмічено «Взяти»: {len(selected)}")
    if not selected:
        print("[enrich_sel] нема відмічених — постав галки «Взяти» в «Огляд_Додавання»"); return

    export = find_ws(sh, "Export Products Sheet")
    ex_head = export.get_all_values()[0]

    bm = BMParts()
    new_rows, done_rn = [], []
    for rn, art in selected:
        try:
            prod = bm.get_product(art)
            if not prod:
                print(f"[enrich_sel] {art}: не знайдено в BM Parts"); continue
            prod.setdefault("article", art)
            f, name_ua, imgs, details, price = build_fields(prod)   # ПРАВИЛА_PROM
            row = [f.get(h, "") for h in ex_head]                    # мапимо за іменем колонки Prom
            new_rows.append(row); done_rn.append(rn)
            print(f"[enrich_sel] ✅ {art} | {name_ua[:42]} | опис {len(f.get('Опис_укр',''))} симв | тегів {f.get('Пошукові_запити_укр','').count(',')+1} | фото {len(imgs)} | ціна {price}")
        except Exception as e:
            print(f"[enrich_sel] {art}: ПОМИЛКА {e}")

    if not new_rows:
        print("[enrich_sel] нічого не зібрано"); return
    dest = export if TARGET=="export" else find_ws(sh, "Staging_Prom")
    dest.append_rows(new_rows, value_input_option="RAW")
    print(f"[enrich_sel] ✅ дописано {len(new_rows)} ЯКІСНИХ карток (за ПРАВИЛА_PROM) у «{dest.title}»")
    for rn in done_rn:
        rv.update_cell(rn, c_stat+1, "додано")
    print(f"[enrich_sel] позначено {len(done_rn)} як «додано»")

if __name__ == "__main__":
    main()
