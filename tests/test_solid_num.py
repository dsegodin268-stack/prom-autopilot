# -*- coding: utf-8 -*-
"""Каталожний номер у тексті — суцільно.

28.07. Бойовий рядок 3964 («Пильник амортизатора (переднього) BMW …»,
артикул 31306791712) показав, що довідник BM Parts віддає OEM у «людському»
записі — «31 30 6 791 712», і цей запис ішов у три поля картки: в опис
(«Оригінальний (OEM) номер: 31 30 6 791 712»), у пошукові запити (ДВІЧІ —
окремим ключовиком і у зв'язці з типом деталі) та в мета-опис. Виходило два
різні написання одного номера: за суцільним деталь знаходять, за розбитим —
ніде, бо саме так його ніхто не набирає. Мета-опис при цьому лишався без
робочого номера взагалі, і його дописували ворота enforce_limits().

Перевіряємо всі три шари: джерело (_oem_repl), ворота (enforce_limits) і
оцінку (validator.validate_solid).
"""
from adding import rules
from adding.card_builder import (_oem_repl, _solid_nums, enforce_limits,
                                 gen_keywords, html_desc, meta_desc)
from adding.validator import validate_solid

PROD = {
    "name": "Пильник амортизатора (переднього) BMW 3 (F30)/4 (F33)/M4 (F83)",
    "brand": "BMW",
    "article": "31306791712",
    "images": ["x.jpg"],
    "oe": [{"number": "31 30 6 791 712", "is_oem": True},
           {"number": "33 52 6 785 537", "is_oem": False, "brand": "BMW"}],
    "analogs": {"1": {"article": "005.0409", "brand": "ZENTPARTS"}},
}


# ---------- _solid_nums: збиває тільки те, що треба ----------
def test_solid_nums_збирає_розбитий_номер():
    assert _solid_nums("OEM 31 30 6 791 712.") == "OEM 31306791712."


def test_solid_nums_не_чіпає_роки():
    """«2011 2019» — дві групи, а не номер. Якби правило рахувало дві групи,
    діапазон років у сумісності перетворився б на 20112019."""
    assert _solid_nums("BMW 3 F30 2011 2019") == "BMW 3 F30 2011 2019"


def test_solid_nums_не_чіпає_номер_з_крапкою():
    assert _solid_nums("ZENTPARTS 005.0409") == "ZENTPARTS 005.0409"


def test_solid_nums_працює_в_кінці_речення():
    """Крапка після номера — це кінець речення, а не продовження числа."""
    assert _solid_nums("номер 11 42 7 953 129.") == "номер 11427953129."


def test_solid_nums_короткий_ряд_не_чіпається():
    assert _solid_nums("1 2 3") == "1 2 3"


# ---------- джерело ----------
def test_oem_repl_віддає_суцільні_номери():
    oem, repl = _oem_repl(PROD)
    assert oem == ["31306791712"]
    assert any("33526785537" in r for r in repl)
    assert not any(" 6 " in r for r in repl)


def test_ключовики_без_розбитого_номера():
    for lang in ("ru", "ua"):
        kws = gen_keywords(PROD, lang)
        assert "31306791712" in kws
        assert all("31 30 6" not in k for k in kws), kws


def test_опис_і_мета_з_суцільним_номером():
    for lang in ("ru", "ua"):
        d = html_desc(PROD, lang)
        assert "31306791712" in d
        assert "31 30 6 791 712" not in d
        m = meta_desc(PROD, lang)
        assert "31306791712" in m and "31 30 6 791 712" not in m


# ---------- ворота ----------
def test_ворота_чистять_текст_від_ші():
    """ШІ теж любить «людський» запис номера — ворота мусять тримати правило
    незалежно від того, хто написав текст."""
    f = enforce_limits({"HTML_опис": "Пыльник BMW OEM 31 30 6 791 712. Оригинал.",
                        "Назва_позиції_укр": "Пильник BMW 31 30 6 791 712",
                        "Пошукові_запити": "пыльник BMW, 31 30 6 791 712"},
                       "31306791712")
    assert "31 30 6 791 712" not in f["HTML_опис"]
    assert f["Назва_позиції_укр"] == "Пильник BMW 31306791712"
    assert "31306791712" in f["Пошукові_запити"]


def test_ворота_не_ламають_роки_в_описі():
    f = enforce_limits({"Опис_укр": "<p>BMW 3 (F30) 2011 2019</p>"}, "31306791712")
    assert "2011 2019" in f["Опис_укр"]


# ---------- оцінка ----------
def test_валідатор_бачить_розбитий_номер():
    flags = validate_solid({"name": "Пильник BMW 31 30 6 791 712"})
    assert [f for f in flags if f[2] == "num_spaced"]
    assert flags[0][3].startswith("назва: "), flags


def test_валідатор_мовчить_на_чистій_картці():
    assert validate_solid({"name": "Пильник BMW 31306791712",
                           "description": "OEM 31306791712"}) == []


def test_валідатор_не_чіпає_поля_яких_нема():
    assert validate_solid({}) == []


# ---------- правило в довіднику ----------
def test_правило_є_в_RULES():
    assert "num_spaced" in rules.RULES_BY_CODE
    assert rules.RULES_BY_CODE["num_spaced"].hard is True


def test_spaced_number_повертає_підказку():
    msg = rules.spaced_number("OEM 31 30 6 791 712")
    assert "31306791712" in msg
    assert rules.spaced_number("OEM 31306791712") == ""
