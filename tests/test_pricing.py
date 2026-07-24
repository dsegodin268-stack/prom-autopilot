# -*- coding: utf-8 -*-
import math

from common.pricing import final_price, price_with_competitor, MIN_MARKUP_ABS, MARGIN_FLOOR


def test_final_price_tiers():
    assert final_price(0) == 0
    assert final_price(-5) == 0
    assert final_price(2000) == 3000            # ×1.5
    assert final_price(4000) == 5800            # ×1.45
    assert final_price(8000) == 10400           # ×1.3
    assert final_price(20000) == 24000          # ×1.2
    assert final_price(50000) == 55001          # ×1.1 (float→ceil, як в оригінальному main.py)


def test_final_price_min_markup_abs():
    # дешева позиція: ×1.5 дає +50 грн, але мінімальна абсолютна націнка = 150
    assert final_price(100) == 100 + MIN_MARKUP_ABS
    # додавання і репрайсер тепер рахують ОДНАКОВО (раніше enrich_add не мав цього)


def test_price_with_competitor():
    # конкурент нижче тарифу, вище floor -> конкурент - 1
    assert price_with_competitor(2000, 2900) == 2899
    # конкурент нижче floor -> тариф
    floor = int(math.ceil(2000 * MARGIN_FLOOR))
    assert price_with_competitor(2000, floor - 100) == final_price(2000)
    # конкурента нема -> тариф
    assert price_with_competitor(2000, None) == final_price(2000)
