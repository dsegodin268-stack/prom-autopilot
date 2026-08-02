# -*- coding: utf-8 -*-
"""ЄДИНЕ ціноутворення для репрайсера І конвеєра додавання.
Раніше було 4 копії (main.py, enrich_add.py, engine/pricing.py, config.yaml) —
вони розходились: enrich_add не мав MIN_MARKUP_ABS, тож нова картка отримувала
іншу ціну, ніж ставив нічний репрайсер. Тепер джерело одне."""
import math
import os

from common.normalize import num

MIN_MARKUP_ABS = num(os.environ.get("MIN_MARKUP_ABS") or 150)  # мін. абсолютна націнка (грн)
MARGIN_FLOOR = 1.16                                            # беззбитковість + буфер


def final_price(cost):
    """Собівартість -> роздрібна ціна за тарифною сіткою + мін. абсолютна націнка."""
    c = num(cost)
    if c <= 0:
        return 0
    k = 1.4 if c < 3000 else 1.40 if c < 5000 else 1.2 if c < 10000 else 1.15 if c < 30000 else 1.1
    return int(math.ceil(max(c * k, c + MIN_MARKUP_ABS)))


def price_with_competitor(cost, comp):
    """Конкурент −1 грн, але не нижче cost*MARGIN_FLOOR і не вище тарифної ціни."""
    base = final_price(cost)
    if not comp or comp <= 0:
        return base
    floor = int(math.ceil(num(cost) * MARGIN_FLOOR))
    target = int(comp) - 1
    return target if (target >= floor and target < base) else base
