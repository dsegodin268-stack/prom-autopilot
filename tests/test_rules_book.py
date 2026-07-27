# -*- coding: utf-8 -*-
"""ДОВІДНИК ЖОРСТКИХ ПРАВИЛ — adding/rules.py.

Вимога власника 27.07: «ШІ повинен усе перевіряти, за жорсткими правилами Prom
та Google». Виконати її можна двома способами. Поганий: переказати правила ще
раз у промпті — тоді те саме число живе в трьох місцях (шлюз, валідатор, промпт)
і розходиться мовчки, а помітно це стає на бойовій таблиці. Добрий: записати
кожну межу РІВНО ОДИН РАЗ, а промпт ГЕНЕРУВАТИ з того самого списку.

Цей файл стереже другий спосіб. Він перевіряє не «чи правильне число 70», а те,
що число одне: шлюз, валідатор і промпт беруть його з rules.py і фізично не
можуть розійтися. Плюс — кожне правило має джерело, бо «правило без джерела»
через місяць неможливо ні підтвердити, ні прибрати.
"""
import re

import pytest

from adding import card_builder as cb
from adding import rules
from adding import validator as vd


# ------------------------------------------------- одна копія кожного числа ---
def test_gate_and_validator_read_the_same_limits():
    """Головний тест файлу. Доти межа мети жила окремо в card_builder і окремо
    у validator; шлюз різав до 70, а валідатор мовчав про свої 70 — і коли
    хтось правив одне, друге лишалось старим."""
    assert cb.META_TITLE_MAX is rules.META_TITLE_MAX
    assert cb.META_DESC_MAX is rules.META_DESC_MAX
    assert vd.META_TITLE_MAX is rules.META_TITLE_MAX
    assert vd.META_DESC_MAX is rules.META_DESC_MAX
    assert cb.PROM_UNITS is rules.PROM_UNITS
    assert vd.PROM_UNITS is rules.PROM_UNITS


def test_units_list_is_the_long_one_not_the_short_copy():
    """У шлюзі лежала СКОРОЧЕНА копія списку одиниць: «година», «доба», «кВт»,
    «лист» він не знав і мовчки зрізав, а валідатор ті самі одиниці знав і теж
    мовчав. Характеристика доходила до Prom без одиниці виміру."""
    for u in ("година", "день", "кВт", "лист", "карат", "рулон"):
        assert rules.unit_ok(u), u
    assert rules.unit_ok("")            # порожня одиниця — нормально
    assert not rules.unit_ok("папуг")


def test_every_limit_names_its_source():
    """Межа без джерела — це чиясь пам'ять, а не правило. Через місяць таку
    неможливо ні підтвердити, ні прибрати: ніхто не знає, звідки вона."""
    for name, (val, src) in rules.LIMITS.items():
        assert src in rules.SOURCES, f"{name}: невідоме джерело {src}"
        url, title = rules.source(src)
        assert title, name
        # 'own' — свідомо власна межа проєкту, у першоджерелах числа немає;
        # решта мусить мати посилання, яке можна відкрити й перевірити.
        if src != "own":
            assert url.startswith("http"), f"{name}: джерело {src} без посилання"


def test_source_of_unknown_key_does_not_crash():
    assert rules.source("такого-нема") == ("", "такого-нема")


# --------------------------------------------------------- промпт із правил ---
def test_prompt_is_generated_from_the_rules_not_written_by_hand():
    """Якщо промпт колись знову напишуть руками, цей тест впаде: у ньому мусить
    стояти ТОЙ САМИЙ текст правил, що читає код."""
    system = rules.audit_system()
    for r in rules.audit_rules():
        assert r.text in system, r.code


def test_pure_code_rules_do_not_waste_the_prompt():
    """Ціна, наявність і контрольна цифра GTIN — чиста арифметика. Їх рахує код,
    у payload їх або немає взагалі (гроші), або модель однаково рахує гірше.
    Кожен зайвий рядок системного промпта — витрачена добова квота на КОЖНІЙ
    із 3913 позицій."""
    codes = {r.code for r in rules.audit_rules()}
    assert "price" not in codes and "availability" not in codes
    assert "gtin" not in codes
    # а те, що вміє тільки людина/модель — на місці
    assert {"findable", "no_invention", "name_type_first", "consistent"} <= codes


def test_prompt_carries_every_number_the_owner_asked_about():
    system = rules.audit_system()
    for token in (str(rules.NAME_MAX), str(rules.NAME_VISIBLE),
                  str(rules.META_TITLE_MAX), str(rules.META_DESC_MAX),
                  f"{rules.KW_MIN}-{rules.KW_MAX}",
                  f"{rules.DESC_TEXT_MIN}-{rules.DESC_TEXT_SOFT_MAX}",
                  str(rules.CHARS_MIN)):
        assert token in system, token


def test_rules_are_well_formed():
    seen = set()
    for r in rules.RULES:
        assert r.code and r.code not in seen, r.code
        seen.add(r.code)
        assert r.who in ("код", "ші", "обидва"), r.code
        assert r.field and len(r.text) > 20, r.code
        assert r.src in rules.SOURCES, r.code


def test_rulebook_renders_for_the_owner():
    md = rules.rulebook_md()
    for r in rules.RULES:
        assert r.code in md, r.code
    assert "NAME_MAX" in md and "adding/rules.py" in md


# ------------------------------------------------------------------- GTIN ---
def test_gtin_check_digit_is_really_checked():
    """Google Merchant Center відхиляє товар із неправильним GTIN, а Prom такий
    код мовчки приймає — тобто помилку видно аж у відхиленому фіді Google, через
    тиждень і без пояснення. Тому контрольну цифру рахуємо самі."""
    for good in ("5901234123457", "4006381333931", "0012345678905", "96385074"):
        assert rules.gtin_valid(good), good
    for bad in ("5901234123456", "4006381333930", "123", "", None,
                "590123412345", "abcdefghijklm"):
        assert not rules.gtin_valid(bad), bad


def test_gate_refuses_a_barcode_with_a_broken_check_digit():
    """Раніше перевірялась лише ДОВЖИНА: будь-які 13 цифр ставали GTIN.
    Порожнє поле — це «нема даних», хибне — це «ми брешемо про товар»."""
    assert cb.gtin_from({"barcodes": ["5901234123457"]}) == "5901234123457"
    assert cb.gtin_from({"barcodes": ["5901234123456"]}) == ""
    assert cb.gtin_from({"barcodes": ["5901234123456", "4006381333931"]}) == "4006381333931"
    assert cb.gtin_from({}) == ""


def test_validator_reports_which_part_of_gtin_is_wrong():
    codes = {c for (_l, c, _m) in vd.validate_gtin("5901234123456")}
    assert "gtin_check" in codes
    assert {c for (_l, c, _m) in vd.validate_gtin("12345")} == {"gtin_len"}
    assert vd.validate_gtin("") == []          # GTIN не обов'язковий
    assert vd.validate_gtin("5901234123457") == []


# ------------------------------------------------- рекламні vs загальні слова ---
def test_ad_words_are_caught_anywhere_in_the_phrase():
    assert rules.seo_words_in("Купити диск BMW недорого") == ["купити", "недорого"]
    assert rules.seo_words_in("диск гальмівний BMW F30") == []


def test_generic_word_inside_a_real_phrase_is_not_a_defect():
    """Регресія, яку ловить саме цей тест. «авто» лежить усередині
    «автозапчастини», «автомобільний», «автоматична» — перевірка підрядком
    зрізала кожен нормальний запит як брак. Загальне слово — брак ЛИШЕ тоді,
    коли з таких слів складається вся фраза: «авто», «авто запчастини»."""
    assert rules.bad_words_in("автозапчастини BMW 3 F30") == []
    assert rules.bad_words_in("автомобільний фільтр BMW") == []
    assert rules.bad_words_in("фільтр автоматичної коробки BMW") == []
    assert rules.bad_words_in("авто") == ["авто"]
    assert rules.bad_words_in("авто запчастини") == ["авто", "запчастини"]
    assert rules.bad_words_in("Запчастини") == ["запчастини"]


def test_keyword_gate_agrees_with_the_rulebook():
    """Шлюз і валідатор мусять однаково думати про одну й ту саму фразу —
    інакше шлюз ріже те, про що валідатор мовчить."""
    for good in ("автозапчастини BMW F30", "диск гальмівний BMW 3 F30", "11427953129"):
        assert cb._kw_ok(good), good
        assert "kw_seo" not in {c for (_l, c, _m) in vd.validate_keywords([good])}
    for bad in ("купити диск", "авто", "BMW", "(BMW)"):
        assert not cb._kw_ok(bad), bad


def test_meta_is_not_scolded_for_ordinary_words():
    """У мета-описі перевіряються ЛИШЕ рекламні слова. «Оригінальні
    автозапчастини BMW» — це звичайна мова сніпета Google, який читає людина,
    а не окремий пошуковий запит, що з'їдає місце у списку 15-40."""
    quiet = vd.validate_meta("Фільтр масляний BMW 11427953129",
                             "Оригінальні автозапчастини BMW. OEM 11427953129.",
                             "11427953129")
    assert quiet == []
    loud = {c for (_l, c, _m) in vd.validate_meta("Фільтр 11427953129",
                                                  "Купити недорого 11427953129",
                                                  "11427953129")}
    assert "meta_desc_seo" in loud


# --------------------------------------------------- назва: емодзі й контакти ---
def test_emoji_and_contacts_in_the_name_are_critical():
    """[prom_goods] прямо забороняє і те, і те в назві. Контакти в назві —
    класична причина блокування магазину, а не просто зауваження."""
    assert rules.has_emoji("Фільтр масляний BMW 🔥")
    assert not rules.has_emoji("Фільтр масляний BMW 3 F30")
    for bad in ("Фільтр BMW visimics.com.ua", "Фільтр BMW +380671234567",
                "Фільтр BMW telegram", "Фільтр shop@mail.com"):
        assert rules.has_contact(bad), bad
    assert not rules.has_contact("Фільтр масляний BMW 3 F30 11427953129")

    lvls = {c: l for (l, c, _m) in vd.validate_name("Фільтр BMW 🔥 +380671234567")}
    assert lvls.get("name_emoji") == vd.CRITICAL
    assert lvls.get("name_contact") == vd.CRITICAL


def test_city_in_the_name_is_only_a_warning():
    """Свідомо WARN, а не CRITICAL: хибний CRITICAL зупиняє позицію, хибний
    WARN лише додає рядок у звіт. «Львівський» — це не нав'язування міста."""
    lvls = {c: l for (l, c, _m) in vd.validate_name("Фільтр масляний BMW Київ")}
    assert lvls.get("name_region") == vd.WARN


# ------------------------------------------------------- ціна й наявність ---
def test_technical_price_is_flagged():
    """[prom_goods]: «технічні» ціни на кшталт 1 грн заборонені — за ними Prom
    ховає товар із видачі, і позиція просто зникає."""
    assert rules.price_ok(640) and rules.price_ok("2400,50")
    assert not rules.price_ok(1) and not rules.price_ok(0) and not rules.price_ok("")


def test_in_stock_only_when_dispatch_is_short():
    assert rules.availability_ok("!", 1)
    assert rules.availability_ok("+", rules.AVAIL_MAX_DAYS_IN_STOCK)
    assert not rules.availability_ok("!", rules.AVAIL_MAX_DAYS_IN_STOCK + 1)
    # «під замовлення» з довгим строком — це нормально, це чесний статус
    assert rules.availability_ok("-", 14)
    codes = {c for (_l, c, _m) in vd.validate_availability("!", 10)}
    assert "avail_days" in codes


# ------------------------------------------------------------ характеристики ---
def test_three_characteristics_is_the_floor():
    """Довідка Prom: «Вказуйте не менше 3 характеристик товару». Раніше в коді
    стояло 2 — число, якого немає в жодному першоджерелі."""
    assert rules.CHARS_MIN == 3
    two = vd.validate_characteristics([("Виробник", "", "BMW"), ("Вісь", "", "передня")])
    assert "char_min" in {c for (_l, c, _m) in two}
    three = vd.validate_characteristics([("Виробник", "", "BMW"), ("Вісь", "", "передня"),
                                         ("Діаметр", "мм", "330")])
    assert "char_min" not in {c for (_l, c, _m) in three}


def test_unknown_unit_is_reported():
    codes = {c for (_l, c, _m) in vd.validate_characteristics(
        [("Виробник", "", "BMW"), ("Вісь", "", "передня"), ("Діаметр", "папуг", "330")])}
    assert "char_unit" in codes


# ------------------------------------------------------------------- назва ---
def test_name_length_comes_from_the_rulebook():
    long = "Диск гальмівний передній вентильований " * 5
    n = cb._name_for_prom(long, "34116889571")
    assert len(n) <= rules.NAME_MAX
    assert rules.NAME_MAX == 110 and rules.NAME_VISIBLE == 70


def test_the_one_deliberate_copy_of_the_name_limit_is_watched():
    """common/ спільний із нічним репрайсером, тому тягнути в нього adding/rules.py
    не можна: репрайсер почав би залежати від конвеєра додавання. Через це в
    common.bmparts_client лежить свідома копія межі назви. Свідома копія — це
    нормально; НЕПОМІЧЕНА копія — ні. Тут вона й помічається."""
    from common import bmparts_client

    assert bmparts_client.NAME_MAX == rules.NAME_MAX


def test_missing_analog_brand_does_not_print_none_to_the_buyer():
    """Англійське None в описі українського магазину виглядає як зламаний сайт.
    Було f"{number} ({brand})" беззастережно, а бренд замінника в BM Parts
    заповнений далеко не завжди."""
    from common.bmparts_client import oem_and_replacements

    _oem, repl = oem_and_replacements(
        {"oe": [{"number": "11427953129", "is_oem": True},
                {"number": "11427854445", "is_oem": False},          # бренда немає
                {"number": "11427854446", "is_oem": False, "brand": "MANN"},
                {"number": "11427854447 (BMW)", "is_oem": False, "brand": "BMW"}]})
    assert repl == ["11427854445", "11427854446 (MANN)", "11427854447 (BMW)"]
    assert not any("None" in r for r in repl)
    d = cb.html_desc({"name": "Фільтр масляний BMW", "brand": "BMW",
                      "article": "11427953129",
                      "oe": [{"number": "11427953129", "is_oem": True},
                             {"number": "11427854445", "is_oem": False}]}, "ua")
    assert "None" not in d
