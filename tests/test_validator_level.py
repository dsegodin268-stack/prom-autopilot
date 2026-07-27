# -*- coding: utf-8 -*-
# Валідатор на воротах. Дві речі, які тут не можна зламати:
#   1) картка з CRITICAL не потрапляє в Export НІКОЛИ;
#   2) картка без фото (рівень 3) не має гинути на валідаторі — вона мусить
#      доїхати до Staging зі статусом «чекає фото». До правки img_none був
#      CRITICAL для всіх, і рівень 3 відхилявся ще ДО маршрутизації.
from adding.validator import CRITICAL, WARN, summarize, validate_card, worst_level

OK_CARD = {
    "name": "Фільтр масляний BMW 11427953129",
    "description": ("Фільтр масляний оригінальний. Підходить на: BMW 3 F30. "
                    "Оригінальний (OEM) номер: 11427953129. "
                    "Не впевнені, чи підійде саме на ваше авто? Ми підберемо за вас — "
                    "напишіть марку, модель, рік і VIN-код."),
    "chars": [("Виробник", "", "BMW"), ("Висота", "мм", "80")],
    "images": ["https://cdn.bm.parts/a.jpg"],
    "price": 640,
    "product_id": "11427953129",
    "group_id": "123",
}


def _codes(flags):
    return {c for (_f, _l, c, _m) in flags}


def test_good_card_has_no_critical():
    assert worst_level(validate_card(OK_CARD)) != CRITICAL


def test_no_photo_is_critical_by_default():
    card = dict(OK_CARD, images=[])
    flags = validate_card(card, level=1)
    assert worst_level(flags) == CRITICAL
    assert "img_none" in _codes(flags)


def test_no_photo_downgraded_to_warn_on_level_3():
    card = dict(OK_CARD, images=[])
    flags = validate_card(card, level=3)
    assert "img_none" in _codes(flags)
    assert worst_level(flags) == WARN        # картка доїде до Staging


def test_level_3_does_not_forgive_other_criticals():
    # Знижка стосується ЛИШЕ браку фото. Назва з дефісом — усе одно відмова.
    card = dict(OK_CARD, images=[], name="Фільтр масляний BMW - оригінал")
    flags = validate_card(card, level=3)
    assert worst_level(flags) == CRITICAL
    assert "name_dash" in _codes(flags)


def test_empty_description_rejected_on_every_level():
    for lv in (1, 2, 3):
        flags = validate_card(dict(OK_CARD, description=""), level=lv)
        assert worst_level(flags) == CRITICAL
        assert "desc_empty" in _codes(flags)


def test_missing_product_id_rejected_on_every_level():
    for lv in (1, 2, 3):
        flags = validate_card(dict(OK_CARD, product_id=""), level=lv)
        assert worst_level(flags) == CRITICAL


def test_name_with_dash_is_critical():
    # Prom відхиляє «-» у назві — це не смак, це формат імпорту.
    assert "name_dash" in _codes(validate_card(dict(OK_CARD, name="Фільтр - BMW")))


def test_too_long_name_is_critical():
    assert worst_level(validate_card(dict(OK_CARD, name="Ф" * 111))) == CRITICAL


def test_unknown_unit_is_only_warn():
    flags = validate_card(dict(OK_CARD, chars=[("Виробник", "", "BMW"),
                                               ("Довжина", "попугаїв", "5")]))
    assert worst_level(flags) == WARN
    assert "char_unit" in _codes(flags)


def test_summarize_is_short_and_lists_codes():
    s = summarize(validate_card(dict(OK_CARD, images=[]), level=1))
    assert s.startswith(CRITICAL) and "img_none" in s


def test_summarize_ok_when_clean():
    assert summarize([]) == "OK"
