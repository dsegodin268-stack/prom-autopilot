# -*- coding: utf-8 -*-
"""СУХИЙ ПРОГІН усього конвеєра додавання без жодного запиту в мережу.

Таблиця і BM Parts підмінені (tests/fakes.py), решта коду — справжня: пульт,
збирач кандидатів, рівні повноти, довідник, card_builder, валідатор, маршрут.
Перевіряємо головне правило власника від початку до кінця:

    рівень 1 -> Export (бойова)      рівні 2 і 3 -> Staging_Prom

і те, що позиція без фото в бойову таблицю не потрапляє ЖОДНИМ шляхом.
"""
import pytest

from common.config import EXPORT_TAB, PANEL_TAB, REVIEW_TAB, STAGING_TAB
from tests.fakes import FakeBM, FakeSpreadsheet

# 31 колонка формату імпорту Prom: скаляри + три блоки характеристик + вага
EX_HEAD = ["Код_товару", "Ідентифікатор_товару", "Назва_позиції", "Назва_позиції_укр",
           "Пошукові_запити", "Пошукові_запити_укр", "Опис", "Опис_укр",
           "HTML_заголовок", "HTML_заголовок_укр", "HTML_опис", "HTML_опис_укр",
           "Ціна", "Валюта", "Одиниця_виміру", "Наявність", "Кількість",
           "Номер_групи", "Назва_групи", "Виробник", "Посилання_зображення",
           "Назва_Характеристики", "Одиниця_виміру_Характеристики", "Значення_Характеристики",
           "Назва_Характеристики", "Одиниця_виміру_Характеристики", "Значення_Характеристики",
           "Назва_Характеристики", "Одиниця_виміру_Характеристики", "Значення_Характеристики",
           "Вага,кг"]

PANEL_SEED = [
    ["Параметр", "Значення", "Підказка"],
    ["Джерело", "BM Parts", ""],
    ["Марка (для BM Parts)", "BMW", ""],
    ["Скільки позицій за раз", "200", ""],
    ["Куди писати готові", "Export Products Sheet (бойова)", ""],
    ["Рівень ШІ", "Без ШІ", ""],          # сухий прогін не ходить до ШІ-провайдерів
    ["Тільки в наявності", "FALSE", ""],
    ["Мін. собівартість, ₴", "0", ""],
    ["Останній запуск", "", ""],
]


@pytest.fixture
def sh(monkeypatch):
    """Книга з бойовою вкладкою і заповненим пультом + підмінений BM Parts."""
    book = FakeSpreadsheet()
    ex = book.add_worksheet(EXPORT_TAB, cols=len(EX_HEAD))
    ex.update(values=[EX_HEAD], range_name="A1")
    book.add_worksheet(PANEL_TAB, cols=3).update(values=PANEL_SEED, range_name="A1")

    import adding.review as review
    monkeypatch.setattr(review, "_bm", lambda: FakeBM())
    return book


def _run_review(book):
    from adding.panel import ensure_panel, read_panel
    from adding.review import do_review
    ensure_panel(book)
    st = read_panel(book)
    return do_review(book, st)


def _take_all(book):
    """Власник ставить галки «Взяти» на всіх рядках огляду."""
    from adding.review import C_TAKE
    rv = book.ws(REVIEW_TAB)
    n = len(rv.get_all_values())
    for r in range(2, n + 1):
        rv._put(r, C_TAKE + 1, "TRUE")
    return n - 1


# ---------------------------------------------------------------- ЕТАП 1 ---
def test_review_builds_three_candidates_with_right_levels(sh):
    st, cands = _run_review(sh)
    assert st["source"] == "BM Parts" and st["target"] == "export"
    assert len(cands) == 3

    rows = sh.ws(REVIEW_TAB).get_all_values()
    head = rows[0]
    lv = head.index("Рівень")
    art = head.index("Артикул")
    by_art = {r[art]: r[lv] for r in rows[1:]}
    assert by_art["11427953129"].startswith("1")     # повна картка
    assert by_art["34116794300"].startswith("3")     # нема фото
    assert by_art["63117214941"].startswith("2")     # фото є, характеристик мало


def test_review_shows_supplier_availability_verbatim(sh):
    _run_review(sh)
    rows = sh.ws(REVIEW_TAB).get_all_values()
    head = rows[0]
    art, av = head.index("Артикул"), head.index("Наявність")
    by_art = {r[art]: r[av] for r in rows[1:]}
    assert "наявн" in by_art["11427953129"].lower()
    assert "15" in by_art["34116794300"]             # під замовлення ~15 дн


def test_review_take_column_starts_unchecked(sh):
    from adding.review import C_TAKE
    _run_review(sh)
    rows = sh.ws(REVIEW_TAB).get_all_values()
    assert all(r[C_TAKE] == "FALSE" for r in rows[1:])


# ---------------------------------------------------------------- ЕТАП 2 ---
def test_enrich_routes_by_level(sh):
    from adding.panel import read_panel
    from adding.run import do_enrich

    _run_review(sh)
    assert _take_all(sh) == 3
    do_enrich(sh, read_panel(sh))

    ex = sh.ws(EXPORT_TAB).get_all_values()
    stg = sh.ws(STAGING_TAB).get_all_values()
    assert [r[0] for r in ex[1:]] == ["11427953129"]          # лише рівень 1
    assert {r[0] for r in stg[1:]} == {"34116794300", "63117214941"}


def test_no_photo_never_reaches_export(sh):
    from adding.panel import read_panel
    from adding.run import do_enrich

    _run_review(sh)
    _take_all(sh)
    do_enrich(sh, read_panel(sh))

    ex = sh.ws(EXPORT_TAB).get_all_values()
    i_img = EX_HEAD.index("Посилання_зображення")
    assert ex[1:], "в Export має бути хоч одна картка"
    for r in ex[1:]:
        assert r[i_img].strip(), "картка без фото потрапила в бойову таблицю"


def test_staging_keeps_export_header_so_row_can_be_moved(sh):
    from adding.panel import read_panel
    from adding.run import do_enrich

    _run_review(sh)
    _take_all(sh)
    do_enrich(sh, read_panel(sh))
    assert sh.ws(STAGING_TAB).get_all_values()[0] == EX_HEAD


def test_availability_follows_supplier_not_hardcoded(sh):
    """Раніше build_fields ставив «Наявність»: «+» усім — і нічний репрайсер
    наступного ж дня перебивав щойно додану картку. Тепер наявність і кількість
    рахує той самий avail_cell(), що й репрайсер."""
    from adding.panel import read_panel
    from adding.run import do_enrich

    _run_review(sh)
    _take_all(sh)
    do_enrich(sh, read_panel(sh))

    i_av, i_qt = EX_HEAD.index("Наявність"), EX_HEAD.index("Кількість")
    row = sh.ws(EXPORT_TAB).get_all_values()[1]
    assert row[i_av] == "!" and row[i_qt] == "5"      # у наявності 5 шт.

    stg = {r[0]: r for r in sh.ws(STAGING_TAB).get_all_values()[1:]}
    order = stg["34116794300"]
    assert order[i_av] == "15" and order[i_qt] == ""  # під замовлення, к-ть порожня


def test_characteristics_survive_the_triples_layout(sh):
    from adding.panel import read_panel
    from adding.run import do_enrich

    _run_review(sh)
    _take_all(sh)
    do_enrich(sh, read_panel(sh))

    from common.prom_format import read_chars
    row = sh.ws(EXPORT_TAB).get_all_values()[1]
    chars = read_chars(EX_HEAD, row)
    assert ("Висота", "мм", "80") in chars
    assert len(chars) >= 3


def test_second_run_does_not_duplicate_existing_codes(sh):
    from adding.panel import read_panel
    from adding.run import do_enrich

    _run_review(sh)
    _take_all(sh)
    do_enrich(sh, read_panel(sh))
    before = len(sh.ws(EXPORT_TAB).get_all_values())

    # Огляд лишився зі старими галками — повторний enrich не має нічого дописати.
    do_enrich(sh, read_panel(sh))
    assert len(sh.ws(EXPORT_TAB).get_all_values()) == before

    rows = sh.ws(REVIEW_TAB).get_all_values()
    i_st = rows[0].index("Статус")
    assert any("вже в Export" in r[i_st] for r in rows[1:])


def test_review_skips_codes_already_in_export(sh):
    ex = sh.ws(EXPORT_TAB)
    ex.append_rows([["11427953129"] + [""] * (len(EX_HEAD) - 1)])
    _st, cands = _run_review(sh)
    assert {c["article"] for c in cands} == {"34116794300", "63117214941"}


def test_panel_status_is_written_back(sh):
    from adding.panel import read_panel
    from adding.run import do_enrich

    _run_review(sh)
    _take_all(sh)
    do_enrich(sh, read_panel(sh))
    status = sh.ws(PANEL_TAB).get_all_values()[8][1]
    assert "Export 1" in status and "Staging 2" in status


def test_nothing_written_when_no_boxes_ticked(sh):
    from adding.panel import read_panel
    from adding.run import do_enrich

    _run_review(sh)
    do_enrich(sh, read_panel(sh))              # галок нема
    assert len(sh.ws(EXPORT_TAB).get_all_values()) == 1
    assert sh.ws(STAGING_TAB) is None
