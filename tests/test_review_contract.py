# -*- coding: utf-8 -*-
# Вкладка «Огляд_Додавання» — КОНТРАКТ між етапами review і enrich. Наявність
# показується людською мовою, а enrich читає її назад через parse_avail(), щоб
# не лізти по ціну й наявність у прайс постачальника вдруге (і не переплутати
# джерело). Тому пара avail_h/parse_avail мусить бути оборотною.
from adding.review import C_TAKE, HEAD, avail_h, parse_avail


def test_take_column_index_matches_header():
    assert HEAD[C_TAKE] == "Взяти"


def test_header_has_no_duplicate_columns():
    assert len(HEAD) == len(set(HEAD))


def test_in_stock_roundtrip():
    txt = avail_h("available", 0, 4)
    assert "4" in txt
    assert parse_avail(txt) == ("available", 0)


def test_in_stock_without_qty_roundtrip():
    assert parse_avail(avail_h("available", 0, 0)) == ("available", 0)


def test_order_term_roundtrip():
    assert parse_avail(avail_h("order", 3)) == ("order", 3)
    assert parse_avail(avail_h("order", 15)) == ("order", 15)


def test_order_unknown_term_defaults_to_15():
    # Той самий дефолт, що й у репрайсера (repricing/export_writer.avail_cell).
    assert parse_avail(avail_h("order", 0)) == ("order", 15)
    assert parse_avail("") == ("order", 15)


def test_prom_raw_markers_are_understood():
    # Якщо в клітинку потрапив «сирий» формат Prom — теж читаємо правильно.
    assert parse_avail("!") == ("available", 0)
    assert parse_avail("+") == ("available", 0)
    assert parse_avail("7") == ("order", 7)


def test_qty_is_not_mistaken_for_days():
    # «✅ в наявності (4 шт.)» містить цифру — але це кількість, а не термін.
    presence, days = parse_avail(avail_h("available", 0, 4))
    assert presence == "available" and days == 0
