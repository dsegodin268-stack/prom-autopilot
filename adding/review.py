# -*- coding: utf-8 -*-
"""MODE=review: зібрати кандидатів із вибраного джерела -> «Огляд_Додавання».

Вкладка огляду — це КОНТРАКТ між двома етапами. Усе, що потрібно етапу enrich
(джерело, артикул, собівартість, наявність, кількість), лежить у рядку. Тому
enrich не перечитує прайси вдруге і не може випадково взяти ціну не в того
постачальника, у якого ми цю позицію купуємо.

Що бачить власник у кожному рядку: фото, звідки позиція, скільки коштує нам і
скільки коштуватиме покупцю, РІВЕНЬ повноти і ЧОГО САМЕ бракує. Галка «Взяти»
лишилась там же, де була."""
import os
import re

from common.bmparts_client import BMParts
from common.config import (EXPORT_TAB, REVIEW_TAB, SRC_ALL, SRC_BMPARTS,
                           SUPPLIER_BOOKS)
from common.pricing import final_price
from common.sheets import find_ws
from adding.completeness import LEVEL_NAME, describe, level
from adding.panel import read_panel
from adding.sources import dedup
from adding.sources.bmparts_feed import candidates as bm_candidates
from adding.sources.bmparts_feed import stock_map  # noqa: F401  (використовує run.py)
from adding.sources.lookup import bm_lookup_many
from adding.sources.supplier_book import candidates as book_candidates

HEAD = ["Фото", "Джерело", "Артикул", "Назва (як у джерелі)", "Собівартість, ₴",
        "Ціна, ₴", "Наявність", "К-ть", "Рівень", "Чого бракує",
        "Характеристики", "OEM", "Сумісність", "Взяти", "Статус"]
C_TAKE = 13          # 0-based індекс колонки «Взяти» (для чекбокса)
LEVEL_BG = {1: (0.85, 0.94, 0.83), 2: (1.0, 0.95, 0.80), 3: (0.98, 0.85, 0.83)}


def avail_h(presence, days, qty=0):
    """Людський текст наявності. enrich читає його назад через parse_avail()."""
    if presence == "available":
        return "✅ в наявності" + (f" ({int(qty)} шт.)" if qty else "")
    d = int(days or 0) or 15
    return f"під замовлення ~{d} дн"


def parse_avail(text):
    """Зворотне до avail_h(): текст із огляду -> (presence, days).
    Потрібне етапу enrich, щоб не лізти по наявність у прайс удруге."""
    t = str(text or "").strip().lower()
    if "наявн" in t or t in ("!", "+", "true", "1"):
        return "available", 0
    m = re.search(r"(\d+)", t)
    return "order", (int(m.group(1)) if m else 15)


def _bm():
    """Клієнт BM Parts або None (без токена довідник просто не працює)."""
    if not (os.environ.get("BMPARTS_TOKEN") or "").strip():
        print("[add] нема BMPARTS_TOKEN — фід і довідник BM Parts недоступні")
        return None
    try:
        return BMParts()
    except Exception as e:
        print(f"[add] BM Parts недоступний: {str(e)[:80]}")
        return None


def collect(st, ex_codes, bm=None):
    """Пульт -> список кандидатів із потрібних джерел (уже без дублів)."""
    src, lim = st["source"], st["max"]
    out = []
    if src in (SRC_BMPARTS, SRC_ALL):
        bm = bm or _bm()
        if bm:
            out += bm_candidates(bm, ex_codes, st["brand"], lim)
    for name in SUPPLIER_BOOKS:
        if src in (name, SRC_ALL):
            out += book_candidates(name, ex_codes, lim)
    out = dedup(out)
    if st.get("instock_only"):
        n = len(out)
        out = [c for c in out if c["presence"] == "available"]
        print(f"[add] лише в наявності: {n} -> {len(out)}")
    if st.get("min_cost"):
        n = len(out)
        out = [c for c in out if (c["cost"] or 0) >= st["min_cost"]]
        print(f"[add] мін. собівартість {st['min_cost']:.0f} ₴: {n} -> {len(out)}")
    if lim:
        out = out[:lim]
    return out


def _row(c):
    url = (c.get("photos") or [""])[0]
    photo = f'=IMAGE("{url}")' if str(url).startswith("http") else ""
    chars = "; ".join(f"{n}: {v}" for (n, _u, v) in (c.get("chars") or [])[:4])
    return [photo, c["source"], c["article"], c.get("name_src", ""),
            int(c.get("cost") or 0), final_price(c.get("cost")),
            avail_h(c.get("presence"), c.get("days"), c.get("qty")),
            c.get("qty") or "", LEVEL_NAME[level(c)], describe(c),
            chars, ", ".join((c.get("oem") or [])[:5]),
            "; ".join((c.get("fitment") or [])[:3]), False, ""]


def render(sh, cands):
    rv = find_ws(sh, REVIEW_TAB, create_cols=len(HEAD))
    out = [HEAD] + [_row(c) for c in cands]
    n = len(out)
    rv.clear()
    rv.update(values=out, range_name=f"A1:O{n}", value_input_option="USER_ENTERED")

    px = {0: 70, 1: 120, 2: 130, 3: 300, 8: 130, 9: 200, 10: 260, 12: 220}
    reqs = [
        {"setDataValidation": {
            "range": {"sheetId": rv.id, "startRowIndex": 1, "endRowIndex": n,
                      "startColumnIndex": C_TAKE, "endColumnIndex": C_TAKE + 1},
            "rule": {"condition": {"type": "BOOLEAN"}, "strict": True}}},
        {"updateSheetProperties": {
            "properties": {"sheetId": rv.id,
                           "gridProperties": {"frozenRowCount": 1, "frozenColumnCount": 3}},
            "fields": "gridProperties.frozenRowCount,gridProperties.frozenColumnCount"}},
        {"updateDimensionProperties": {
            "range": {"sheetId": rv.id, "dimension": "ROWS", "startIndex": 1, "endIndex": n},
            "properties": {"pixelSize": 60}, "fields": "pixelSize"}},
    ]
    for i, w in px.items():
        reqs.append({"updateDimensionProperties": {
            "range": {"sheetId": rv.id, "dimension": "COLUMNS",
                      "startIndex": i, "endIndex": i + 1},
            "properties": {"pixelSize": w}, "fields": "pixelSize"}})
    # колір колонки «Рівень»: зелений/жовтий/червоний — щоб тріаж був на око
    rows = []
    for c in cands:
        r, g, b = LEVEL_BG[level(c)]
        rows.append({"values": [{"userEnteredFormat": {
            "backgroundColor": {"red": r, "green": g, "blue": b}}}]})
    if rows:
        reqs.append({"updateCells": {
            "range": {"sheetId": rv.id, "startRowIndex": 1, "endRowIndex": n,
                      "startColumnIndex": 8, "endColumnIndex": 9},
            "rows": rows, "fields": "userEnteredFormat.backgroundColor"}})
    rv.spreadsheet.batch_update({"requests": reqs})
    return rv


def do_review(sh, st=None):
    # st передає run.py — пульт уже прочитано, другий раз таблицю не смикаємо.
    st = st or read_panel(sh)
    export = find_ws(sh, EXPORT_TAB)
    ex_codes = {r[0] for r in export.get_all_values()[1:] if r and r[0]}
    print(f"[add] Export: {len(ex_codes)} наявних кодів")

    bm = _bm()
    cands = collect(st, ex_codes, bm)
    if not cands:
        print("[add] нових кандидатів нема")
        return st, []

    # Довідник BM Parts для позицій із прайсів: саме він перетворює «артикул +
    # назва + ціна» на повноцінну картку з фото і характеристиками. Дорого
    # (≈2.5 с на позицію через тротлінг), тому обмежено тим, що показуємо.
    need = [c for c in cands if c["source"] != SRC_BMPARTS and not c["card_loaded"]]
    if need and bm:
        print(f"[add] шукаю контент у BM Parts для {len(need)} позицій із прайсів…")
        bm_lookup_many(bm, need)
    elif need:
        print("[add] довідник BM Parts недоступний — позиції з прайсів лишаться рівня 3")

    render(sh, cands)
    by_lv = {}
    for c in cands:
        by_lv[level(c)] = by_lv.get(level(c), 0) + 1
    print(f"[add] ✅ {len(cands)} кандидатів у «{REVIEW_TAB}» "
          f"(рівень 1: {by_lv.get(1,0)}, 2: {by_lv.get(2,0)}, 3: {by_lv.get(3,0)})")
    print(">>> Постав «Взяти» → MODE=enrich → картки поїдуть за рівнем.")
    return st, cands
