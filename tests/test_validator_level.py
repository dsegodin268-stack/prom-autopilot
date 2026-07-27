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
    # Справжня листкова група з довідника магазину. Раніше тут стояло «123» —
    # номер, якого в Prom не існує. Поки канон ніхто не перевіряв, вигадка
    # мовчки проходила; тепер саме такий рядок і ламає імпорт усього файлу.
    "group_id": "138500033",          # Масляные фильтры
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


# ------------------------------------------------------- КАНОН на воротах ---
# Вимога власника 27.07: таблиця експорту — канонічний шаблон, і ШІ мусить
# перевіряти картку САМЕ за цими вимогами. Перевірки жили в rules.py, але їх
# ніхто не викликав. Ці тести стережуть, що тепер викликає.

def test_invented_group_id_is_critical():
    """Неіснуючий номер групи валить імпорт УСЬОГО файлу, а не однієї позиції.
    Тому це єдина канонна перевірка, яка має право зупинити картку."""
    flags = validate_card(dict(OK_CARD, group_id="999"))
    assert worst_level(flags) == CRITICAL
    assert "canon_group" in _codes(flags)


def test_missing_group_is_only_warn_so_the_card_reaches_staging():
    """Групи нема -> це «оберіть руками», а не аварія: run.py відправить таку
    картку в Staging_Prom. CRITICAL убив би її ще до маршрутизації."""
    flags = validate_card(dict(OK_CARD, group_id=""))
    assert worst_level(flags) == WARN
    assert "group_empty" in _codes(flags)
    assert "canon_group" not in _codes(flags)


def test_parent_group_is_a_hint_not_a_stopper():
    flags = validate_card(dict(OK_CARD, group_id="138537782"))   # Амортизаторы
    assert worst_level(flags) == WARN
    assert "canon_group_deep" in _codes(flags)


def test_unknown_section_is_critical_but_missing_one_is_not():
    bad = validate_card(dict(OK_CARD, section_id="999"))
    assert worst_level(bad) == CRITICAL and "canon_section" in _codes(bad)

    empty = validate_card(dict(OK_CARD, section_id=""))
    assert worst_level(empty) == WARN and "canon_section_empty" in _codes(empty)


def test_section_link_must_match_its_id():
    flags = validate_card(dict(OK_CARD, section_id="341523",
                               section_url="https://prom.ua/Inshe"))
    assert "canon_section_url" in _codes(flags)
    assert worst_level(flags) == WARN


def test_missing_required_characteristics_are_named():
    flags = validate_card(OK_CARD)
    assert "canon_chars" in _codes(flags)
    msg = [m for (_f, _l, c, m) in flags if c == "canon_chars"][0]
    assert "Код запчастини" in msg


def test_part_code_must_match_the_article():
    chars = [("Стан", "", "Новий"), ("Сумісність з маркою", "", "BMW"),
             ("Сумісність з моделлю", "", "3-Series"), ("Тип запчастини", "", "Оригінал"),
             ("Тип техніки", "", "Легковий автомобіль"),
             ("Код запчастини", "", "11427953129")]
    assert "canon_part_code" not in _codes(validate_card(dict(OK_CARD, chars=chars)))

    spaced = [t if t[0] != "Код запчастини" else ("Код запчастини", "", "1142 7953129")
              for t in chars]
    flags = validate_card(dict(OK_CARD, chars=spaced))
    assert "canon_part_code" in _codes(flags)
    assert worst_level(flags) == WARN        # у чернетку, а не в нікуди
