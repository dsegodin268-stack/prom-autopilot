#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""МОДУЛЬ «ДОДАВАННЯ ПОЗИЦІЙ» — точка входу (запуск: python -m adding.run).
MODE=review : bulk-фід BM Parts -> нові коди -> «Огляд_Додавання» (чекбокс «Взяти»).
MODE=enrich : відмічені «Взяти» -> get_product -> card_builder -> ВАЛІДАТОР -> Export.
2026-07-24: validator підключено на ворота — CRITICAL-картки в Export НЕ пишуться."""
import os

import gspread

from common.bmparts_client import BMParts
from common.config import ID_HUB, EXPORT_TAB, STAGING_TAB, REVIEW_TAB
from common.sheets import find_ws, keyf, open_hub
from adding.card_builder import build_fields
from adding.review import do_review, fetch_stock
from adding.validator import CRITICAL, summarize, validate_card, worst_level

MODE = os.environ.get("MODE", "review").strip().lower()
TARGET = os.environ.get("TARGET", "export").strip().lower()
MAX = int(os.environ.get("MAX", "0"))
TRUE = {"true", "1", "так", "yes", "on", "✓"}


def _row_from_fields(ex_head, f, chars):
    """Скаляри — за назвою колонки; характеристики — позиційно у трійки
    Назва_Характеристики | Одиниця | Значення."""
    row = [f.get(h, "") for h in ex_head]
    ci = 0
    i = 0
    while i < len(ex_head) and ci < len(chars):
        if keyf(ex_head[i]) == keyf("Назва_Характеристики"):
            nm, unit, val = chars[ci]
            ci += 1
            row[i] = nm
            if i + 1 < len(ex_head):
                row[i + 1] = unit
            if i + 2 < len(ex_head):
                row[i + 2] = val
            i += 3
        else:
            i += 1
    return row


def do_enrich(sh):
    rv = find_ws(sh, REVIEW_TAB)
    rows = rv.get_all_values()
    if not rows:
        raise SystemExit("огляд порожній")
    head = rows[0]

    def ci(name, d=None):
        for i, h in enumerate(head):
            if keyf(h) == keyf(name):
                return i
        return d

    c_art, c_take, c_stat = ci("Артикул", 1), ci("Взяти"), ci("Статус")

    export = find_ws(sh, EXPORT_TAB)
    ex_vals = export.get_all_values()
    ex_head = ex_vals[0]
    ex_codes = {keyf(r[0]) for r in ex_vals[1:] if r and r[0]}

    selected = []
    for rn, r in enumerate(rows[1:], start=2):
        if c_take is None or len(r) <= c_take:
            continue
        art = r[c_art].strip() if len(r) > c_art else ""
        if keyf(r[c_take]) in TRUE and art:
            selected.append((rn, art))
    if MAX:
        selected = selected[:MAX]
    print(f"[add] відмічено «Взяти»: {len(selected)}")
    if not selected:
        print("[add] нема відмічених — постав галки «Взяти»")
        return

    bm = BMParts()
    stock = fetch_stock(bm)
    new_rows = []
    mark = {}
    seen = set()
    for rn, art in selected:
        k = keyf(art)
        if k in ex_codes or k in seen:
            mark[rn] = "вже в Export"
            print(f"[add] {art}: вже в Export — пропуск")
            continue
        try:
            prod = bm.get_product(art)
            if not prod:
                mark[rn] = "нема в BM Parts"
                print(f"[add] {art}: не знайдено в BM Parts")
                continue
            prod.setdefault("article", art)
            f, name_ua, imgs, details, price = build_fields(prod)
            av, qt = stock.get(k, ("", ""))
            if av:
                f["Наявність"] = av
            if qt != "":
                f["Кількість"] = qt
            # --- ВАЛІДАТОР на воротах (ПРАВИЛА §10) ---
            card = {"name": f.get("Назва_позиції_укр"), "description": f.get("Опис_укр"),
                    "chars": details, "images": imgs, "price": price,
                    "product_id": art, "group_id": f.get("Номер_групи")}
            flags = validate_card(card, is_part=True)
            verdict = summarize(flags)
            if worst_level(flags) == CRITICAL:
                mark[rn] = f"відхилено валідатором: {verdict[:90]}"
                print(f"[add] ⛔ {art}: {verdict}")
                continue
            new_rows.append(_row_from_fields(ex_head, f, details))
            seen.add(k)
            mark[rn] = "додано" if verdict == "OK" else f"додано ({verdict[:80]})"
            print(f"[add] ✅ {art} | {name_ua[:40]} | ціна {price} | наяв {f.get('Наявність','')} "
                  f"к-ть {f.get('Кількість','')} | х-к {len(details)} | фото {len(imgs)} | {verdict}")
        except Exception as e:
            mark[rn] = "помилка"
            print(f"[add] {art}: ПОМИЛКА {e}")

    if new_rows:
        dest = export if TARGET == "export" else find_ws(sh, STAGING_TAB)
        dest.append_rows(new_rows, value_input_option="RAW")
        print(f"[add] ✅ дописано {len(new_rows)} карток (ПРАВИЛА_PROM + валідатор) у «{dest.title}»")
    else:
        print("[add] нових карток нема (усе вже в Export / без даних / відхилено валідатором)")

    if mark and c_stat is not None:
        rv.batch_update([{"range": gspread.utils.rowcol_to_a1(rn, c_stat + 1), "values": [[st]]}
                         for rn, st in mark.items()], value_input_option="RAW")


def main():
    sh = open_hub(os.environ.get("HUB_ID", ID_HUB))
    if MODE == "enrich":
        do_enrich(sh)
    else:
        do_review(sh)


if __name__ == "__main__":
    main()
