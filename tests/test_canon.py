# -*- coding: utf-8 -*-
"""КАНОН КАРТКИ — adding/canon.py і перевірки за ним у adding/rules.py.

Вимога власника 27.07: «таблицю експорту треба взяти як канонічну таблицю для
наповнення товару… заклади це як канонічний шаблон, якого треба притримуватися».

Тобто канон — це не документ, який хтось пообіцяв пам'ятати, а довідник у коді,
зчитаний з бойової вкладки на 3960 позицій. Цей файл стереже дві речі, кожна з
яких уже колись коштувала нам картки:

  1. ID НЕ ВИГАДУЮТЬСЯ. Неіснуючий номер групи ламає імпорт УСЬОГО файлу, а не
     однієї позиції — тому «немає в довіднику» мусить бути помилкою, а не
     мовчазним пропуском.
  2. Роздільники різні. У Prom їх ТРИ: «|» для моделей і років, «;» для
     крос-номерів, «, » для фото. Сплутати — злити всі значення в одне сміттєве,
     яке фільтр маркетплейсу не розбере, і побачити це аж у кабінеті.
"""
import pytest

from adding import canon
from adding import rules


# ----------------------------------------------------------- довідник груп ---
def test_group_directory_has_no_orphans():
    """Кожен батько мусить існувати. Група з батьком-привидом — це зламаний
    шлях у каталозі: товар начебто є, а гілки, у якій він лежить, немає."""
    ids = {gid for gid, _n, _p in canon.CATALOG}
    for gid, name, parent in canon.CATALOG:
        if parent:
            assert parent in ids, f"{gid} «{name}»: батька {parent} немає в довіднику"


def test_group_ids_are_unique():
    ids = [gid for gid, _n, _p in canon.CATALOG]
    assert len(ids) == len(set(ids))


def test_leaf_is_not_the_same_as_exists():
    """142124961 «Пыльники и отбойники» — листок, туди товар класти можна.
    138537782 «Амортизаторы» — батьківська: покупець, що зайшов у підкатегорію,
    позицію з неї просто не побачить."""
    assert canon.group_exists("142124961") and canon.is_leaf("142124961")
    assert canon.group_exists("138537782") and not canon.is_leaf("138537782")
    assert not canon.group_exists("999")


def test_group_path_reads_top_down():
    assert canon.group_path("142124961").endswith("Амортизаторы / Пыльники и отбойники")
    assert canon.group_path("999") == ""


# ------------------------------------------------------- довідник розділів ---
def test_section_url_is_built_only_from_the_directory():
    """Підрозділ маркетплейсу — друга вісь, окрема від групи магазину, і в
    бойовій таблиці заповнена на 3960/3960 рядків. Невідомий ID дає порожнє
    посилання, а НЕ вигадане: краще чернетка, ніж зламаний імпорт."""
    assert canon.section_url("341523") == "https://prom.ua/Pylniki-avtomobilnye"
    assert canon.section_url("999") == ""
    assert canon.section_url("") == ""
    assert canon.section_exists(canon.SECTION_FALLBACK)


# ------------------------------------------------------------ роздільники ---
def test_three_separators_do_not_get_mixed_up():
    assert canon.join_multi(["5-Series", "520i"]) == "5-Series|520i"
    assert canon.join_cross(["181653", "33108370"]) == "181653;33108370"
    assert canon.join_images(["a.jpg", "b.jpg"]) == "a.jpg, b.jpg"


def test_join_drops_blanks_and_duplicates_but_keeps_order():
    """Дубль моделі в «Сумісність з моделлю» — це не косметика: у фільтрі
    маркетплейсу та сама модель починає двоїтися."""
    assert canon.join_multi(["X5", "", "X5", None, "X6"]) == "X5|X6"


# ------------------------------------------------------- характеристики ---
def test_char_order_puts_the_important_ones_first():
    """common/prom_format.write_chars кладе характеристики ПОЗИЦІЙНО і мовчки
    відкидає все після 29-го блоку. Тому порядок — це не естетика: якщо «Код
    запчастини» опиниться в хвості, він і загубиться першим, а без нього Prom
    не підчепить крос-довідник."""
    chars = [("Місце встановлення", "", "Задній"),
             ("Код запчастини", "", "33531093094"),
             ("Стан", "", "Новий")]
    names = [t[0] for t in canon.order_chars(chars)]
    assert names.index("Стан") < names.index("Код запчастини") < names.index("Місце встановлення")


def test_order_chars_truncates_to_the_real_number_of_slots():
    many = [(f"Х{i}", "", str(i)) for i in range(50)]
    assert len(canon.order_chars(many)) == canon.CHAR_SLOTS


def test_order_chars_drops_empty_values_and_duplicate_names():
    chars = [("Стан", "", "Новий"), ("Стан", "", "Вживаний"), ("Колір", "", "")]
    assert canon.order_chars(chars) == [("Стан", "", "Новий")]


def test_missing_required_names_exactly_what_is_missing():
    full = [(n, "", "х") for n in canon.CHAR_REQUIRED]
    assert canon.missing_required(full) == ()
    assert "Код запчастини" in canon.missing_required(full[:-2])


# ------------------------------------------------------- скалярні дефолти ---
def test_unit_switches_to_kit_by_the_name():
    assert canon.unit_for("Фільтр масляний BMW") == "шт."
    assert canon.unit_for("Комплект пильників і відбійників") == "комплект"


def test_country_is_looked_up_not_guessed():
    """Невідомий бренд дає ПОРОЖНЮ країну. Підставити «Німеччина» за схожістю —
    це вигадка в бойовій картці, а вигадок у нас бути не може."""
    assert canon.country_for("BMW") == "Німеччина"
    assert canon.country_for("  bmw ") == "Німеччина"
    assert canon.country_for("Skoda") == ""
    assert canon.country_for(None) == ""


def test_part_type_is_binary():
    assert canon.part_type_value(True) == "Оригінал"
    assert canon.part_type_value(False) == "Аналог"


# ------------------------------------- перевірки за каноном у rules.py ---
def test_rules_reads_the_canon_and_does_not_copy_it():
    """Друга копія канону розійдеться з першою мовчки. Тому rules.py мусить
    БРАТИ числа з canon.py, а не мати свої."""
    assert rules.CHAR_SLOTS is canon.CHAR_SLOTS
    assert rules.CHARS_REQUIRED is canon.CHAR_REQUIRED
    assert rules.GROUPS_KNOWN == len(canon.CATALOG)


@pytest.mark.parametrize("gid, expect", [
    ("142124961", ""),                 # листкова група — годиться
    ("138537782", ""),                 # батьківська, але власник сам нею користується
    ("", "не визначена"),              # нема групи — на курацію, це не аварія
    ("999", "немає в довіднику"),      # вигаданий ID — аварія
])
def test_group_problem_only_fails_on_a_number_that_does_not_exist(gid, expect):
    assert expect in rules.group_problem(gid)


def test_parent_group_is_a_hint_not_a_defect():
    """У бойовій таблиці в «Амортизаторы» (138537782) лежать 47 позицій —
    власник сам так робить, бо підгрупи там про пружини й опори. Тому
    батьківська група — це порада перевірити, а не брак картки."""
    assert rules.group_problem("138537782") == ""
    assert "підгруп" in rules.group_note("138537782")
    assert rules.group_note("142124961") == ""
    assert rules.group_note("999") == ""


def test_section_problem_catches_a_link_that_does_not_match_the_id():
    ok = "https://prom.ua/Pylniki-avtomobilnye"
    assert rules.section_problem("341523", ok) == ""
    assert "не збігається" in rules.section_problem("341523", "https://prom.ua/Inshe")
    assert "не вказаний" in rules.section_problem("")
    assert "немає в довіднику" in rules.section_problem("999")


_GOOD = [("Стан", "", "Новий"), ("Сумісність з маркою", "", "BMW"),
         ("Сумісність з моделлю", "", "5-Series"), ("Тип запчастини", "", "Оригінал"),
         ("Код запчастини", "", "33531093094"), ("Тип техніки", "", "Легковий автомобіль")]


def test_chars_problem_passes_the_canonical_set():
    assert rules.chars_problem(_GOOD) == ""


def test_chars_problem_names_the_missing_ones():
    msg = rules.chars_problem(_GOOD[:3])
    assert "Код запчастини" in msg and "Тип техніки" in msg


def test_chars_problem_warns_about_silent_truncation():
    many = _GOOD + [(f"Х{i}", "", str(i)) for i in range(40)]
    assert "блоків" in rules.chars_problem(many)


def test_part_code_must_be_solid_and_equal_to_the_article():
    """Номер BMW у картці пишеться суцільно: 11427953129, а не 11 42 7 953 129.
    З пробілами крос-довідник Prom його не впізнає."""
    assert rules.part_code_problem(_GOOD, "33531093094") == ""
    assert "суцільно" in rules.part_code_problem(
        [("Код запчастини", "", "1142 7953129")], "11427953129")
    assert "різні номери" in rules.part_code_problem(_GOOD, "11427953129")
    assert "порожня" in rules.part_code_problem([("Стан", "", "Новий")], "111")


def test_audit_prompt_carries_the_canon_requirements():
    """Вимога власника: ШІ перевіряє картку ЗА ЦИМИ вимогами. Промпт
    генерується з RULES, тож достатньо перевірити, що канонні правила в нього
    справді доїхали."""
    sys = rules.audit_system()
    for code in ("chars_required", "part_code", "group", "section"):
        assert rules.RULES_BY_CODE[code].text[:40] in sys, code
