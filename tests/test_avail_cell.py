# -*- coding: utf-8 -*-
from repricing.export_writer import avail_cell


def test_in_stock_is_ready_to_ship():
    # В наявності -> статус Prom «!» (готово до відправки) + кількість.
    avail, qty = avail_cell(4, 0)
    assert avail == "!" and qty == 4


def test_order_uses_real_term():
    # Під замовлення -> реальний термін постачання (днів), кількість порожня.
    assert avail_cell(0, 3) == ("3", "")
    assert avail_cell(0, 15) == ("15", "")


def test_order_unknown_term_defaults_15():
    assert avail_cell(0, 0) == ("15", "")
    assert avail_cell(0, None) == ("15", "")


def test_in_stock_wins_even_with_days():
    # Якщо є залишок — це «!», навіть якщо в offer був якийсь термін.
    avail, qty = avail_cell(2, 5)
    assert avail == "!" and qty == 2
