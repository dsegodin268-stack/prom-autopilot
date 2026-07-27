# -*- coding: utf-8 -*-
# Розкладка характеристик у фіді Prom. Саме тут була мовчазна втрата даних:
# run.py писав ТРІЙКАМИ, а review.py читав ПАРАМИ, тому з рядка діставалась
# одиниця виміру замість значення (а одиниця часто порожня — і характеристики
# просто зникали). Тест фіксує, що обидві сторони беруть розкладку з шапки.
from common.prom_format import char_columns, read_chars, write_chars

TRIPLE = ["Код_товару", "Назва_позиції",
          "Назва_Характеристики", "Одиниця_виміру_Характеристики", "Значення_Характеристики",
          "Назва_Характеристики", "Одиниця_виміру_Характеристики", "Значення_Характеристики"]

PAIR = ["Код_товару", "Назва_позиції",
        "Назва_Характеристики", "Значення_Характеристики",
        "Назва_Характеристики", "Значення_Характеристики"]


def test_triples_layout_detected():
    assert char_columns(TRIPLE) == [(2, 3, 4), (5, 6, 7)]


def test_pairs_layout_detected():
    assert char_columns(PAIR) == [(2, None, 3), (4, None, 5)]


def test_header_without_chars_gives_nothing():
    assert char_columns(["Код_товару", "Назва_позиції", "Ціна"]) == []


def test_write_then_read_roundtrip_triples():
    chars = [("Виробник", "", "BMW"), ("Діаметр", "мм", "76.0")]
    row = write_chars(TRIPLE, [""] * len(TRIPLE), chars)
    assert row[2:5] == ["Виробник", "", "BMW"]
    assert row[5:8] == ["Діаметр", "мм", "76.0"]
    assert read_chars(TRIPLE, row) == chars


def test_write_then_read_roundtrip_pairs():
    # У парній шапці одиниці подіти нікуди — вона губиться, але ЗНАЧЕННЯ
    # лишається на місці. Раніше саме тут значення підмінялось одиницею.
    chars = [("Виробник", "", "BMW"), ("Діаметр", "мм", "76.0")]
    row = write_chars(PAIR, [""] * len(PAIR), chars)
    assert row[2:4] == ["Виробник", "BMW"]
    assert row[4:6] == ["Діаметр", "76.0"]
    assert read_chars(PAIR, row) == [("Виробник", "", "BMW"), ("Діаметр", "", "76.0")]


def test_extra_chars_are_dropped_not_crashing():
    # Характеристик більше, ніж блоків у шапці: зайві відкидаються мовчки.
    chars = [(f"Х{i}", "", str(i)) for i in range(10)]
    row = write_chars(TRIPLE, [""] * len(TRIPLE), chars)
    assert len(read_chars(TRIPLE, row)) == 2


def test_half_filled_block_is_skipped():
    # Назва без значення — це не характеристика, у Prom такий блок не йде.
    row = [""] * len(TRIPLE)
    row[2] = "Виробник"
    assert read_chars(TRIPLE, row) == []


def test_read_limit():
    chars = [("A", "", "1"), ("B", "", "2")]
    row = write_chars(TRIPLE, [""] * len(TRIPLE), chars)
    assert read_chars(TRIPLE, row, limit=1) == [("A", "", "1")]
