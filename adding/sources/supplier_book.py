# -*- coding: utf-8 -*-
"""Джерело B: прайс-книги постачальників (BMW «Баварія», Porsche) у Google Sheets.

Ці книги дають рівно три речі: артикул, назву (часто непридатну для Prom і SEO)
і собівартість. Фото, характеристик, OEM і сумісності тут немає — їх шукає
довідник BM Parts (sources/lookup.py), а чого не знайшлося, дописує ШІ за
жорсткими правилами (adding/ai_layer.py, профіль THIN).

Читання вкладок НЕ дублюється: використовується той самий read_all_tabs(), що
й у нічному репрайсері, — отже наявність, терміни й «найдешевша перемагає»
рахуються за однаковими правилами в обох процесах. Раніше тут був окремий
supplier_articles() у card_builder.py, який умів лише артикули без цін —
його видалено як строго слабший."""
import os

from common.config import SUPPLIER_BOOKS
from common.normalize import num
from common.sheets import keyf
from repricing.sources.bmw_porsche_sheets import read_all_tabs
from adding.sources import candidate, key


def _gclient():
    """Повний gspread-клієнт: read_all_tabs робить open_by_key, а sh.client
    у gspread 6 — це HTTPClient без цього методу."""
    from common.sheets import gclient_rw
    return gclient_rw()


def candidates(source, ex_codes=(), limit=0, gc=None):
    """Прайс-книга постачальника -> список candidate() без контенту."""
    book = SUPPLIER_BOOKS.get(source)
    if not book:
        print(f"[price-book] невідоме джерело {source!r}")
        return []
    sid, brand = book
    gc = gc or _gclient()
    best, instock = {}, {}
    read_all_tabs(gc, sid, brand, best, instock)
    if not best:
        print(f"[price-book] {brand}: прайс порожній або нема доступу")
        return []

    have = {keyf(c) for c in ex_codes} | {key(c) for c in ex_codes}
    min_cost = num(os.environ.get("MIN_COST") or 0)
    out = []
    for art, it in best.items():
        k = key(art)
        if not k or k in have or keyf(art) in have:
            continue
        cost = num(it.get("cost"))
        if cost <= 0 or (min_cost and cost < min_cost):
            continue
        qty = int(num(it.get("qty")))
        presence = it.get("presence") or "order"
        out.append(candidate(
            source=source,
            article=it.get("article") or art,
            name_src=(it.get("name") or "").strip(),
            cost=cost,
            qty=qty if presence == "available" else 0,
            presence=presence,
            days=int(num(it.get("days"))) or (0 if presence == "available" else 15),
            brand=it.get("brand") or brand,
        ))
        if limit and len(out) >= limit:
            break
    print(f"[price-book] {brand}: {len(best)} у прайсі -> {len(out)} нових кандидатів")
    return out
