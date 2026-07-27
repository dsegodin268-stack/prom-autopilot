# -*- coding: utf-8 -*-
"""Джерела кандидатів на додавання — ЄДИНИЙ формат запису.

НАВІЩО. BM Parts віддає повну картку (фото + характеристики + OEM + сумісність),
а прайс постачальника (BMW «Баварія», Porsche) — лише артикул, назву і
собівартість, причому назва часто не годиться ні для Prom, ні для SEO.
Щоб далі по конвеєру не було двох гілок коду, обидва джерела зводяться до
одного словника candidate(), а різниця описується НЕ типом джерела, а тим,
скільки полів заповнено — див. adding/completeness.py (рівень 1 / 2 / 3).

ЗАЛІЗНЕ ПРАВИЛО (повторене і в sources/lookup.py):
ціна, валюта, наявність і кількість беруться ВИКЛЮЧНО від постачальника,
у якого ми купуємо цю позицію. Довідник BM Parts дає лише КОНТЕНТ
(фото, характеристики, OEM, сумісність) і ніколи не чіпає ці чотири поля.
"""
from common.normalize import _nkey


def candidate(source, article, name_src, cost, qty=0, presence="order",
              days=15, brand="", photos=None, chars=None, oem=None,
              fitment=None, group_hint=""):
    """Один кандидат на додавання, однаковий для всіх джерел.

    source     — з common.config.SRC_* (звідки ця позиція і за чиєю ціною)
    article    — код товару як у постачальника (може містити дефіси)
    name_src   — назва ЯК У ДЖЕРЕЛІ, ще не оброблена під Prom
    cost       — собівартість; роздрібну рахує common.pricing.final_price
    presence   — "available" | "order"
    photos/chars/oem/fitment/group_hint — контент; у прайсів порожні,
                 заповнюються довідником BM Parts (sources/lookup.py)
    matched_bm — позиція є в BM Parts (контент для неї здобувний)
    card_loaded — картку BM Parts уже завантажено, тобто OEM і сумісність
                 відомі остаточно. Поки False — ці два поля просто ще НЕ
                 запитували (bulk-фід їх не віддає), і рахувати їх «браком»
                 не можна: інакше кожна позиція BM Parts на етапі огляду
                 виглядала б неповною і їхала б у Staging замість Export.
    """
    return {"source": source, "article": article, "name_src": name_src,
            "cost": cost, "qty": qty, "presence": presence, "days": days,
            "brand": brand, "photos": photos or [], "chars": chars or [],
            "oem": oem or [], "fitment": fitment or [], "group_hint": group_hint,
            "matched_bm": False, "card_loaded": False}


def key(article):
    """Ключ порівняння артикулів між джерелами і Export: лише цифри/літери, UPPER."""
    return _nkey(article)


def dedup(cands):
    """Прибирає дублі по ключу артикула; перемагає дешевша собівартість."""
    best = {}
    for c in cands:
        k = key(c.get("article"))
        if not k:
            continue
        old = best.get(k)
        if old is None or (c.get("cost") or 0) < (old.get("cost") or 0):
            best[k] = c
    return list(best.values())
