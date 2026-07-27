#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""МОДУЛЬ «ДОДАВАННЯ ПОЗИЦІЙ» — точка входу (запуск: python -m adding.run).

MODE=review : джерело з «Пульт_Додавання» -> кандидати -> «Огляд_Додавання»
              (фото, ціна, РІВЕНЬ повноти, чого бракує, галка «Взяти»).
MODE=enrich : відмічені «Взяти» -> контент BM Parts -> card_builder -> ВАЛІДАТОР
              -> Export (лише рівень 1) або Staging_Prom (рівні 2 і 3).
MODE=panel  : лише створити/оновити пульт і вийти.

Правила, які тут тримаються буквально:
  • ціна, валюта, наявність і кількість — від постачальника, у якого купуємо;
    довідник BM Parts дає лише контент;
  • CRITICAL від валідатора в Export не потрапляє НІКОЛИ;
  • картка без фото не потрапляє в Export НІКОЛИ (рівень 3 -> Staging)."""
import os

import gspread

from common.config import EXPORT_TAB, ID_HUB, LIVE, REVIEW_TAB, SRC_BMPARTS, STAGING_TAB
from common.normalize import num
from common.prom_format import write_chars
from common.sheets import find_ws, keyf, open_hub
from adding.ai_layer import audit_card, audit_line
from adding.card_builder import build_fields, product_from_candidate
from adding.completeness import level, route
from adding.panel import ensure_panel, read_panel, write_status
from adding.review import do_review, parse_avail
from adding.sources import candidate, key
from adding.sources.bmparts_feed import stock_map
from adding.sources.lookup import bm_lookup
from adding.validator import CRITICAL, summarize, validate_card, worst_level

MODE = os.environ.get("MODE", "review").strip().lower()
MAX = int(num(os.environ.get("MAX") or 0))
TRUE = {"true", "1", "так", "yes", "on", "✓", "+"}


def _row_from_fields(ex_head, f, chars):
    """Скаляри — за назвою колонки; характеристики — за розкладкою шапки
    (common/prom_format.py сам розбирає, трійки там чи пари)."""
    row = [f.get(h, "") for h in ex_head]
    return write_chars(ex_head, row, chars)


def _cand_from_row(head_i, r):
    """Рядок «Огляд_Додавання» -> candidate(). Огляд — контракт між етапами:
    усе, що потрібно для ціни й наявності, вже лежить у рядку, тому прайс
    постачальника вдруге не читається і переплутати джерело неможливо."""
    g = lambda name, d="": (r[head_i[name]].strip()
                            if head_i.get(name) is not None and head_i[name] < len(r) and r[head_i[name]]
                            else d)
    presence, days = parse_avail(g("Наявність"))
    qty = int(num(g("К-ть")))
    return candidate(
        source=g("Джерело", SRC_BMPARTS),
        article=g("Артикул"),
        name_src=g("Назва (як у джерелі)"),
        cost=num(g("Собівартість, ₴")),
        qty=qty if presence == "available" else 0,
        presence=presence,
        days=days,
        brand="",
    )


def _staging(sh, ex_head):
    """Вкладка чернетки з тією ж шапкою, що й Export, — щоб рядок звідти можна
    було просто перенести в бойову таблицю без перескладання колонок."""
    ws = find_ws(sh, STAGING_TAB, create_cols=max(len(ex_head), 31))
    try:
        first = ws.row_values(1)
    except Exception:
        first = []
    if not first:
        ws.update(values=[ex_head], range_name="A1", value_input_option="RAW")
    return ws


def do_enrich(sh, st):
    rv = find_ws(sh, REVIEW_TAB)
    rows = rv.get_all_values()
    if not rows:
        raise SystemExit("огляд порожній")
    head = rows[0]
    head_i = {}
    for i, h in enumerate(head):
        head_i.setdefault(keyf(h), i)
    hi = {name: head_i.get(keyf(name)) for name in
          ["Джерело", "Артикул", "Назва (як у джерелі)", "Собівартість, ₴",
           "Наявність", "К-ть", "Взяти", "Статус"]}
    if hi["Взяти"] is None or hi["Артикул"] is None:
        raise SystemExit(f"в «{REVIEW_TAB}» нема колонок «Взяти»/«Артикул» — "
                         f"перезапусти MODE=review")

    export = find_ws(sh, EXPORT_TAB)
    ex_vals = export.get_all_values()
    ex_head = ex_vals[0]
    ex_codes = {key(r[0]) for r in ex_vals[1:] if r and r[0]}

    selected = []
    for rn, r in enumerate(rows[1:], start=2):
        c_take = hi["Взяти"]
        if len(r) <= c_take or keyf(r[c_take]) not in TRUE:
            continue
        c = _cand_from_row(hi, r)
        if c["article"]:
            selected.append((rn, c))
    if MAX:
        selected = selected[:MAX]
    print(f"[add] відмічено «Взяти»: {len(selected)}")
    if not selected:
        print("[add] нема відмічених — постав галки «Взяти»")
        return

    from adding.review import _bm
    bm = _bm()
    # Свіжа наявність BM Parts: між оглядом і enrich могли минути дні.
    # Для позицій із прайсів наявність лишається та, що в огляді, — її джерело
    # прайс постачальника, а не BM Parts.
    stock = stock_map(bm, st["brand"]) if (bm and any(
        c["source"] == SRC_BMPARTS for _rn, c in selected)) else {}

    use_ai = st.get("ai") != "Без ШІ"
    to_export, to_staging, mark = [], [], {}
    seen = set()
    for rn, c in selected:
        art, k = c["article"], key(c["article"])
        try:
            if k in ex_codes or k in seen:
                mark[rn] = "вже в Export"
                print(f"[add] {art}: вже в Export — пропуск")
                continue
            if bm:
                bm_lookup(bm, c)
            if c["source"] == SRC_BMPARTS:
                if not c["matched_bm"]:
                    mark[rn] = "нема в BM Parts"
                    print(f"[add] {art}: не знайдено в BM Parts")
                    continue
                av, qt = stock.get(keyf(art), ("", ""))
                if av:
                    c["presence"], c["days"] = parse_avail(av)
                    c["qty"] = int(num(qt)) if c["presence"] == "available" else 0

            prod = product_from_candidate(c)
            f, name_ua, imgs, details, price = build_fields(prod, cand=c, use_ai=use_ai)

            # --- ВАЛІДАТОР на воротах (ПРАВИЛА §10) ---
            # Рівень рахуємо ДО валідації: картці рівня 3 брак фото ставиться в
            # провину лише як WARN, бо вона й так їде в чернетку «чекає фото».
            # Інакше валідатор відхиляв би її тут і позиція гинула б мовчки.
            lv = level(c)
            # meta_title / meta_desc / keywords додано 27.07: без них валідатор
            # не бачив половини чекліста §10 — довжину мета-полів, кількість
            # ключовиків, наявність каталожного номера в меті.
            card = {"name": f.get("Назва_позиції_укр"), "description": f.get("Опис_укр"),
                    "chars": details, "images": imgs, "price": price,
                    "product_id": art, "group_id": f.get("Номер_групи"),
                    "meta_title": f.get("HTML_заголовок_укр"),
                    "meta_desc": f.get("HTML_опис_укр"),
                    "keywords": f.get("Пошукові_запити_укр")}
            flags = validate_card(card, is_part=True, level=lv)
            verdict = summarize(flags)
            if worst_level(flags) == CRITICAL:
                mark[rn] = f"відхилено валідатором: {verdict[:90]}"
                print(f"[add] ⛔ {art}: {verdict}")
                continue

            # --- ДРУГА ДУМКА ШІ (дорадча, ПРАВИЛА §10 + Google) ---
            # Іде ПІСЛЯ валідатора і лише для карток, які вже пройшли: на
            # відхиленій витрачати добову квоту немає сенсу. Результат ніде далі
            # не читається, крім рядка статусу, — маршрут «Export чи Staging»
            # рахує код. Нема ключів / вичерпано квоту / провайдер мовчить ->
            # audit_line порожній, і конвеєр працює точно так само, як досі.
            ai_note = audit_line(audit_card(f, chars=details, images=imgs,
                                            article=art, group=f.get("Номер_групи"),
                                            use_ai=use_ai))

            dest, status = route(c, st["target"])
            # Запобіжник: навіть якщо рівень порахувався оптимістично, картка
            # без жодного фото в бойову таблицю не піде — Prom її відхилить.
            if dest == "export" and not imgs:
                dest, status = "staging", "чекає фото"
            # Те саме для групи (27.07). map_group() свідомо повертає '' для
            # невпізнаного типу — вигадувати номер групи Prom не можна, бо
            # неіснуючий ID ламає імпорт усього файлу. Але раніше така картка
            # усе одно їхала в Export із порожньою групою: наприклад масляний
            # фільтр, якого просто нема в сіді GROUPS. Тепер вона чекає, поки
            # власник обере групу руками.
            if dest == "export" and not f.get("Номер_групи"):
                dest, status = "staging", "нема групи — обрати вручну"
            row = _row_from_fields(ex_head, f, details)
            (to_export if dest == "export" else to_staging).append(row)
            seen.add(k)
            mark[rn] = (f"{status} → {'Export' if dest == 'export' else 'Staging'}"
                        + ("" if verdict == "OK" else f" ({verdict[:60]})")
                        + (f" | {ai_note[:120]}" if ai_note else ""))
            print(f"[add] ✅ {art} | рівень {lv} | {name_ua[:38]} | ціна {price} | "
                  f"наяв {f.get('Наявність','')} к-ть {f.get('Кількість','')} | "
                  f"х-к {len(details)} | фото {len(imgs)} | -> {dest} | {verdict}"
                  + (f" | {ai_note}" if ai_note else ""))
        except Exception as e:
            mark[rn] = "помилка"
            print(f"[add] {art}: ПОМИЛКА {e}")

    if to_export and LIVE:
        export.append_rows(to_export, value_input_option="RAW")
        print(f"[add] ✅ дописано {len(to_export)} карток у «{export.title}» (БОЙОВА)")
    elif to_export:
        print(f"[add] DRY-RUN (LIVE=0): {len(to_export)} карток НЕ записано в Export")
    if to_staging:
        _staging(sh, ex_head).append_rows(to_staging, value_input_option="RAW")
        print(f"[add] ✅ дописано {len(to_staging)} карток у «{STAGING_TAB}» (на перевірку)")
    if not to_export and not to_staging:
        print("[add] нових карток нема (усе вже в Export / без даних / відхилено валідатором)")

    c_stat = hi["Статус"]
    if mark and c_stat is not None:
        rv.batch_update([{"range": gspread.utils.rowcol_to_a1(rn, c_stat + 1), "values": [[stt]]}
                         for rn, stt in mark.items()], value_input_option="RAW")

    try:
        from adding.ai_layer import usage_report
        ai_line = f" | ШІ: {usage_report()}"
    except Exception:
        ai_line = ""
    write_status(sh, f"enrich: Export {len(to_export)}, Staging {len(to_staging)}, "
                     f"відмічено {len(selected)}{ai_line}")


def main():
    sh = open_hub(os.environ.get("HUB_ID", ID_HUB))
    if MODE == "panel":
        ensure_panel(sh)
        return
    ensure_panel(sh)                 # пульт має існувати до будь-якого прогону
    st = read_panel(sh)
    if MODE == "enrich":
        do_enrich(sh, st)
    else:
        _st, cands = do_review(sh, st)
        write_status(sh, f"review: {len(cands)} кандидатів, джерело {st['source']}")


if __name__ == "__main__":
    main()
