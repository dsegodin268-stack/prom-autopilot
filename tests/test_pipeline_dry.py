# -*- coding: utf-8 -*-
"""СУХИЙ ПРОГІН усього конвеєра додавання без жодного запиту в мережу.

Таблиця і BM Parts підмінені (tests/fakes.py), решта коду — справжня: пульт,
збирач кандидатів, рівні повноти, довідник, card_builder, валідатор, маршрут.
Перевіряємо головне правило власника від початку до кінця:

    рівень 1 -> Export (бойова)      рівні 2 і 3 -> Staging_Prom

і те, що позиція без фото в бойову таблицю не потрапляє ЖОДНИМ шляхом.
Так само не потрапляє позиція, тип якої не мапиться в групу Prom: у каталозі
без групи товар не знаходиться ні категорією, ні фільтром, а вигадувати номер
групи заборонено (adding/groups.py).
"""
import pytest

from adding import canon
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
    assert len(cands) == 4

    rows = sh.ws(REVIEW_TAB).get_all_values()
    head = rows[0]
    lv = head.index("Рівень")
    art = head.index("Артикул")
    by_art = {r[art]: r[lv] for r in rows[1:]}
    assert by_art["34116792217"].startswith("1")     # повна картка, група мапиться
    assert by_art["11517586925"].startswith("2")     # усе є, але групи Prom нема
    assert by_art["34116794300"].startswith("3")     # нема фото
    assert by_art["63117214941"].startswith("2")     # фото є, характеристик мало


def test_review_shows_supplier_availability_verbatim(sh):
    _run_review(sh)
    rows = sh.ws(REVIEW_TAB).get_all_values()
    head = rows[0]
    art, av = head.index("Артикул"), head.index("Наявність")
    by_art = {r[art]: r[av] for r in rows[1:]}
    assert "наявн" in by_art["34116792217"].lower()
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
    assert _take_all(sh) == 4
    do_enrich(sh, read_panel(sh))

    ex = sh.ws(EXPORT_TAB).get_all_values()
    stg = sh.ws(STAGING_TAB).get_all_values()
    assert [r[0] for r in ex[1:]] == ["34116792217"]          # лише рівень 1
    assert {r[0] for r in stg[1:]} == {"11517586925", "34116794300", "63117214941"}


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
    assert row[i_av] == "!" and row[i_qt] == "3"      # у наявності 3 шт.

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
    # У фейковій шапці блоків лише ТРИ, тож вижити мусять найважливіші. Раніше
    # тут чекався «Діаметр» постачальника — і це було симптомом справжньої
    # діри: у картку взагалі не потрапляв обов'язковий набір Prom. Тепер
    # порядок канонічний (adding/canon.py), і при обрізанні гине другорядне.
    assert [t[0] for t in chars] == [canon.CH_STATE, canon.CH_BRAND_FIT, canon.CH_MODEL_FIT]


def test_supplier_characteristics_survive_a_real_width_header():
    """А на БОЙОВІЙ шапці (29 блоків) вистачає місця й характеристикам
    постачальника — саме тому обрізання канонічним порядком безпечне."""
    from common.prom_format import read_chars, write_chars
    from adding.card_builder import build_fields

    head = (EX_HEAD[:21]
            + ["Назва_Характеристики", "Одиниця_виміру_Характеристики",
               "Значення_Характеристики"] * canon.CHAR_SLOTS
            + ["Вага,кг"])
    prod = {"article": "34116792217", "name": "Диск гальмівний передній BMW 3 F30",
            "brand": "BMW", "images": ["/a.jpg"],
            "oe": [{"number": "34116792217", "is_oem": True}],
            "cars": [{"brand": "BMW", "model": "3", "modification": "F30",
                      "years": "2011-2018"}],
            "details": {"Діаметр [мм]": "330"},
            "nodes": "Гальма / Тормозные диски", "price": 2400}
    f, _n, _i, chars, _p = build_fields(prod, use_ai=False)
    got = read_chars(head, write_chars(head, [f.get(h, "") for h in head], chars))
    names = [t[0] for t in got]
    assert ("Діаметр", "мм", "330") in got
    assert canon.CH_PART_CODE in names
    assert names.index(canon.CH_PART_CODE) < names.index("Діаметр")


def test_routing_judges_the_built_card_not_the_raw_candidate(sh, monkeypatch):
    """ГОЛОВНА РЕГРЕСІЯ ПРОГОНУ №18 (27.07).

    Рівень і маршрут рахувалися з candidate — тобто з того, що прийшло в
    «Огляд_Додавання» з прайсу постачальника, ДО того, як card_builder зібрав
    картку. Через це позиція, у якої в підсумку 11 характеристик, фото, справжня
    група Prom і підрозділ, лягла в чернетку з написом «на перевірку: нема
    характеристик, сумісності». Обидва твердження були неправдою: у прайсі цього
    справді не було, а в КАРТЦІ вже було.

    Тест доводить, що судять саме картку: кандидатові тут вибивають з рук усе,
    що читав старий level() — фото, характеристики, OEM, сумісність і підказку
    групи, — а картка все одно мусить доїхати в Export."""
    from adding.panel import read_panel
    import adding.run as run
    import adding.sources.lookup as lookup

    real_lookup = lookup.bm_lookup

    def blinding(bm, c, cache=None):
        """Довідник відпрацював, а потім кандидата «осліпили»: у ньому не
        лишилось нічого, за чим старий код рахував рівень."""
        ok = real_lookup(bm, c, cache=cache)
        c.update(photos=[], chars=[], oem=[], fitment=[], group_hint="")
        return ok

    monkeypatch.setattr(run, "bm_lookup", blinding)

    _run_review(sh)
    _take_all(sh)
    run.do_enrich(sh, read_panel(sh))

    ex = {r[0] for r in sh.ws(EXPORT_TAB).get_all_values()[1:]}
    assert "34116792217" in ex, (
        "повна картка знову поїхала в чернетку через сирого кандидата")


def test_staging_reason_names_what_is_really_missing(sh):
    """Друга половина тієї ж регресії: у чернетці має бути написана ПРАВДА.

    У прогоні №18 статус казав «нема характеристик, сумісності» про картку, де
    і те, і те було. Власник читає цю клітинку щодня і за нею вирішує, що
    доробляти руками, — брехливий статус коштує його часу."""
    from adding.panel import read_panel
    from adding.run import do_enrich

    _run_review(sh)
    _take_all(sh)
    do_enrich(sh, read_panel(sh))

    rows = sh.ws(REVIEW_TAB).get_all_values()
    i_art, i_st = rows[0].index("Артикул"), rows[0].index("Статус")
    by_art = {r[i_art]: r[i_st] for r in rows[1:]}

    # Помпа водяної групи в Prom нема -> причина саме «група», і жодного слова
    # про характеристики: їх у картці 10.
    assert "груп" in by_art["11517586925"]
    assert "характеристик" not in by_art["11517586925"]
    # Колодки без фото -> «чекає фото», і теж без вигаданих претензій.
    assert "фото" in by_art["34116794300"]


def test_card_without_the_part_code_waits_in_staging(sh, monkeypatch):
    """ЧЕТВЕРТИЙ запобіжник (27.07). «Код запчастини» — це поле, за яким Prom
    підчіплює крос-довідник, тобто показує позицію тому, хто шукає за номером.
    Картка без нього формально валідна — і саме тому мовчки лягала б у бойову
    таблицю напівпорожньою. Тепер чекає в чернетці.

    Валідатор ставить тут WARN, а не CRITICAL, теж свідомо: CRITICAL означає
    `continue`, тобто позиція не потрапила б НІКУДИ — ні в Export, ні сюди."""
    from adding.panel import read_panel
    import adding.run as run

    real = run.build_fields

    def crippled(product, cand=None, use_ai=True):
        f, name_ua, imgs, chars, price = real(product, cand=cand, use_ai=use_ai)
        chars = [t for t in chars if t[0] != canon.CH_PART_CODE]
        return f, name_ua, imgs, chars, price

    monkeypatch.setattr(run, "build_fields", crippled)

    _run_review(sh)
    _take_all(sh)
    run.do_enrich(sh, read_panel(sh))

    assert sh.ws(EXPORT_TAB).get_all_values()[1:] == [], "картка без номера пішла в бойову"
    assert "34116792217" in {r[0] for r in sh.ws(STAGING_TAB).get_all_values()[1:]}

    rows = sh.ws(REVIEW_TAB).get_all_values()
    i_st = rows[0].index("Статус")
    line = [r[i_st] for r in rows[1:] if r[rows[0].index("Артикул")] == "34116792217"][0]
    assert "канон" in line.lower() and "Staging" in line


def _ai_on(sh, monkeypatch):
    """Пульт із увімкненим ШІ + німий провайдер.

    Провайдер мовчить навмисно: створення картки має лишитись таким самим, як у
    решті сухих тестів, а перевіряємо ми тут ТРЕТІЙ крок — правку, — і його
    видно лише тоді, коли решта не змінюється."""
    from adding import ai_layer
    from adding.panel import read_panel
    monkeypatch.setattr(ai_layer, "_ai_call", lambda system, user: "")
    st = read_panel(sh)
    st["ai"] = "Повний"
    return st


def test_the_audit_findings_go_back_to_the_ai_as_a_fix(sh, monkeypatch):
    """ТРЕТІЙ КРОК (27.07): «ШІ… буде це все перевіряти по жорсткій інструкції,
    І ДОПОВНЮВАТИ, і робити повноцінну картку, яка одразу залітає вже в кабінет».

    Досі аудит лише писав зауваження в колонку «Статус» — тобто знаходив роботу
    і залишав її власникові. Тут перевіряється, що знайдене повертається моделі
    наказом переписати, виправлений текст доїжджає до бойового рядка, а в звіті
    видно «✍» — що саме машина переписала сама."""
    import adding.run as run

    st = _ai_on(sh, monkeypatch)
    monkeypatch.setattr(run, "audit_card", lambda f, **kw: {
        "verdict": "fix", "score": 40, "ai": True,
        "issues": ["назва: немає моделі авто"]})

    called = {}

    def fake_repair(f, product, issues, use_ai=True):
        called["issues"] = list(issues or ())
        f["Назва_позиції_укр"] = "Диск гальмівний передній BMW 3 F30 34116792217"
        return ["Назва_позиції_укр"]

    monkeypatch.setattr(run, "repair_card", fake_repair)

    _run_review(sh)
    _take_all(sh)
    run.do_enrich(sh, st)

    assert called["issues"] == ["назва: немає моделі авто"], "зауваження не доїхали до правки"

    head, *rows = sh.ws(EXPORT_TAB).get_all_values()
    i_name = head.index("Назва_позиції_укр")
    line = [r for r in rows if r[0] == "34116792217"][0]
    assert line[i_name] == "Диск гальмівний передній BMW 3 F30 34116792217", \
        "переписана назва не доїхала до бойового рядка"

    rv = sh.ws(REVIEW_TAB).get_all_values()
    i_st = rv[0].index("Статус")
    status = [r[i_st] for r in rv[1:] if r[rv[0].index("Артикул")] == "34116792217"][0]
    assert "✍" in status and "Назва_позиції_укр" in status, \
        "у звіті не видно, що саме ШІ переписав сам"


def test_the_card_is_checked_again_after_the_repair(sh, monkeypatch):
    """«Після змін ще раз додаси позицію і перевірки все як в попередньому кроці
    було, цей крок перевірки також додай».

    Відповідь другого проходу — такий самий сирий текст від провайдера, як і
    першого, і поблажок їй не робиться. Тут ШІ «виправляє» назву в порожнечу:
    якби перевірки після правки не було, зіпсована картка мовчки лягла б у
    бойову таблицю — і саме її побачив би покупець."""
    import adding.run as run

    st = _ai_on(sh, monkeypatch)
    monkeypatch.setattr(run, "audit_card", lambda f, **kw: {
        "verdict": "fix", "score": 40, "ai": True,
        "issues": ["назва: немає моделі авто"]})

    def spoiling_repair(f, product, issues, use_ai=True):
        f["Назва_позиції_укр"] = ""
        return ["Назва_позиції_укр"]

    monkeypatch.setattr(run, "repair_card", spoiling_repair)

    _run_review(sh)
    _take_all(sh)
    run.do_enrich(sh, st)

    codes = {r[0] for r in sh.ws(EXPORT_TAB).get_all_values()[1:]}
    assert "34116792217" not in codes, "зіпсована правкою картка потрапила в бойову"
    # Ні в чернетку теж: назва порожня — це CRITICAL, а CRITICAL означає, що
    # картки не існує, а не «покладемо десь поруч». Вкладки Staging може не
    # бути взагалі — її створює лише перший рядок, який туди їде.
    st_ws = sh.ws(STAGING_TAB)
    staged = {r[0] for r in st_ws.get_all_values()[1:]} if st_ws else set()
    assert "34116792217" not in staged, "зіпсована картка не мала осісти й у чернетці"

    rv = sh.ws(REVIEW_TAB).get_all_values()
    i_st = rv[0].index("Статус")
    status = [r[i_st] for r in rv[1:] if r[rv[0].index("Артикул")] == "34116792217"][0]
    assert "після правки" in status.lower(), f"незрозуміло, на чому спіткнулось: {status}"


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
    ex.append_rows([["11517586925"] + [""] * (len(EX_HEAD) - 1)])
    _st, cands = _run_review(sh)
    assert {c["article"] for c in cands} == {"34116792217", "34116794300", "63117214941"}


def test_panel_status_is_written_back(sh):
    from adding.panel import read_panel
    from adding.run import do_enrich

    _run_review(sh)
    _take_all(sh)
    do_enrich(sh, read_panel(sh))
    status = sh.ws(PANEL_TAB).get_all_values()[8][1]
    assert "Export 1" in status and "Staging 3" in status


def test_nothing_written_when_no_boxes_ticked(sh):
    from adding.panel import read_panel
    from adding.run import do_enrich

    _run_review(sh)
    do_enrich(sh, read_panel(sh))              # галок нема
    assert len(sh.ws(EXPORT_TAB).get_all_values()) == 1
    assert sh.ws(STAGING_TAB) is None
