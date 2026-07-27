# -*- coding: utf-8 -*-
"""АУДИТ ШІ — дорадчий шар. Тут перевіряється рівно те, що він НЕ може зламати.

Вимога власника 27.07: «ШІ повинен усе перевіряти, за жорсткими правилами Prom
та Google». Схема, яку ці тести закріплюють:

    код   — вирішує (enforce_limits ріже межі, validator рахує, route маршрутизує);
    ШІ    — коментує (audit_card повертає зауваження в колонку «Статус»).

Чому саме так, а не «ШІ вирішує»: ключі опційні, добова квота вичерпується,
провайдер лягає, а модель уміє вигадати зауваження на порожньому місці. Якби
публікація залежала від відповіді ШІ, будь-яка з цих подій зупиняла б додавання
позицій у каталог. Тому нижче: без ключів аудит мовчить, картка їде; з ключами
аудит говорить, картка їде так само; ціна назовні не йде НІКОЛИ.

Мережі тут немає: _ai_call підмінюється у кожному тесті.
"""
import json

import pytest

from adding import ai_layer
from adding.ai_layer import (_norm_audit, audit_card, audit_line, audit_on)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    """Кожен тест починає з чистої пам'яті аудиту й увімкненим AI_AUDIT."""
    ai_layer._audit_memo.clear()
    monkeypatch.delenv("AI_AUDIT", raising=False)
    yield
    ai_layer._audit_memo.clear()


def _card():
    """Готова картка так, як її бачить run.py: разом із грошима."""
    return {"Код_товару": "34116792217",
            "Назва_позиції_укр": "Диск гальмівний передній BMW 3 F30 34116792217",
            "Назва_позиції": "Диск тормозной передний BMW 3 F30 34116792217",
            "Пошукові_запити_укр": "диск гальмівний BMW F30, 34116792217",
            "Опис_укр": "<p>Підходить на BMW 3 F30. OEM 34116792217.</p>",
            "HTML_заголовок_укр": "Диск гальмівний BMW 3 F30 34116792217",
            "HTML_опис_укр": "Оригінальний диск BMW. OEM 34116792217.",
            "Номер_групи": "138537679",
            # --- те, що НЕ має піти до третьої сторони ---
            "Ціна": "2400", "Собівартість": "1580", "Валюта": "UAH",
            "Наявність": "!", "Кількість": "3"}


def _spy(monkeypatch, answer):
    """Підміна _ai_call: запам'ятовує payload і віддає готову відповідь."""
    seen = []

    def fake(system, user_json):
        seen.append((system, user_json))
        return answer

    monkeypatch.setattr(ai_layer, "_ai_call", fake)
    return seen


# ------------------------------------------------- гроші не йдуть назовні ---
def test_price_and_cost_never_reach_the_provider(monkeypatch):
    """Найдорожча помилка цього шару. У словнику картки поруч із текстами лежать
    ціна, собівартість і наявність. Аудит шле картку СТОРОННЬОМУ провайдеру, тому
    поля відбираються білим списком: якщо завтра в картку додадуть ще одне грошове
    поле, воно не поїде саме собою — його треба свідомо дописати в _AUDIT_FIELDS."""
    seen = _spy(monkeypatch, '{"verdict":"ok","score":90,"issues":[]}')
    audit_card(_card(), chars=[("Виробник", "", "BMW")], images=["https://x/1.jpg"],
               article="34116792217")
    payload = seen[0][1]
    for forbidden in ("2400", "1580", "Ціна", "Собівартість", "Валюта", "Наявність"):
        assert forbidden not in payload, forbidden
    # а зміст картки — на місці, інакше перевіряти нічого
    assert "34116792217" in payload and "Пошукові_запити_укр" in payload


def test_whole_card_goes_to_the_audit_not_just_the_texts(monkeypatch):
    """Вимога власника: «ШІ повинен УСЕ перевіряти». Доти на аудит їхало 10
    текстових полів, а решта картки лишалась невидимою — і найдорожчі помилки
    саме там: назва каже «фільтр масляний», а група — «гальмівні диски»; у назві
    один артикул, а в адресі фото інший; вага 0,01 кг у гальмівного диска.
    Фото раніше йшли ЧИСЛОМ: за «3» неможливо помітити, що всі три знімки ведуть
    на чужу деталь."""
    seen = _spy(monkeypatch, '{"verdict":"ok","score":90,"issues":[]}')
    f = _card()
    f.update({"Назва_групи": "Тормозные диски", "Виробник": "BMW",
              "Код_маркування_(GTIN)": "4006381333931", "Вага,кг": "8.4",
              "Посилання_зображення": "https://cdn.bm.parts/34116792217_1.jpg"})
    audit_card(f, chars=[("Виробник", "", "BMW")], article="34116792217")
    payload = seen[0][1]
    for token in ("Тормозные диски", "4006381333931", "8.4",
                  "cdn.bm.parts/34116792217_1.jpg"):
        assert token in payload, token
    # і межа лишилась там, де була: гроші й запаси магазину назовні не йдуть
    for forbidden in ("2400", "1580", "Ціна", "Собівартість", "Валюта",
                      "Наявність", "Кількість"):
        assert forbidden not in payload, forbidden


def test_audit_never_mutates_the_card(monkeypatch):
    """ШІ не має права правити картку: правку нікому було б перевірити."""
    _spy(monkeypatch, '{"verdict":"fix","issues":[{"field":"назва","why":"довга"}],'
                      '"score":40}')
    f = _card()
    before = dict(f)
    audit_card(f, article="34116792217")
    assert f == before


# ------------------------------------------------------- штатне мовчання ---
def test_no_keys_means_no_audit_and_no_crash(monkeypatch):
    """Сходи провайдерів порожні -> _ai_call повертає None. Це НЕ помилка:
    картка публікується так само, як публікувалася б без ШІ взагалі."""
    monkeypatch.setattr(ai_layer, "_ai_call", lambda s, u: None)
    assert audit_card(_card(), article="34116792217") is None
    assert audit_line(None) == ""


def test_switch_off_skips_the_call_entirely(monkeypatch):
    """AI_AUDIT=0 — аудит подвоює витрату добової квоти, власник має вимикач."""
    seen = _spy(monkeypatch, '{"verdict":"ok","issues":[]}')
    monkeypatch.setenv("AI_AUDIT", "0")
    assert audit_on() is False
    assert audit_card(_card(), article="34116792217") is None
    assert seen == []


def test_without_ai_flag_no_call(monkeypatch):
    """«Без ШІ» в пульті вимикає й аудит — інакше пульт брехав би власнику."""
    seen = _spy(monkeypatch, '{"verdict":"ok","issues":[]}')
    assert audit_card(_card(), article="34116792217", use_ai=False) is None
    assert seen == []


def test_broken_json_is_survived(monkeypatch):
    """Безкоштовні моделі регулярно віддають текст замість JSON."""
    _spy(monkeypatch, "Вибачте, я не можу перевірити цю картку.")
    assert audit_card(_card(), article="34116792217") is None


def test_provider_exception_is_survived(monkeypatch):
    def boom(system, user_json):
        raise RuntimeError("503 upstream")

    monkeypatch.setattr(ai_layer, "_ai_call", boom)
    assert audit_card(_card(), article="34116792217") is None


# ------------------------------------------------------------ нормалізація ---
def test_answer_is_normalized_whatever_the_model_called_its_fields():
    """Кожен провайдер відповідає по-своєму: 'problems' замість 'issues',
    рядки замість об'єктів, verdict великими літерами. Розбирати це на місці
    виклику не можна — тоді нова сходинка провайдерів ламала б звіт."""
    r = _norm_audit({"вердикт": "FIX", "problems": ["запити: це окремі слова, а не фрази"],
                     "score": "73"})
    assert r["verdict"] == "fix" and r["score"] == 73
    assert r["issues"] == ["запити: це окремі слова, а не фрази"]


def test_ok_verdict_with_issues_is_still_fix():
    """Модель любить написати 'ok' і тут же перелічити три проблеми."""
    r = _norm_audit({"verdict": "ok", "issues": [{"field": "мета", "why": "довга"}]})
    assert r["verdict"] == "fix"
    assert r["issues"] == ["мета: довга"]


def test_issue_list_is_clamped(monkeypatch):
    """Стовпчик «Статус» — одна клітинка, а не трактат: 6 зауважень максимум,
    кожне обрізане, і в рядок статусу йдуть лише перші три."""
    r = _norm_audit({"verdict": "fix",
                     "issues": [{"field": "назва", "why": "дуже довге пояснення " * 20}
                                for _ in range(20)]})
    assert len(r["issues"]) == 6
    assert all(len(i) <= 24 + 2 + 120 for i in r["issues"])
    assert len(audit_line(r).split(";")) == 3


def test_score_out_of_range_is_clamped():
    assert _norm_audit({"verdict": "ok", "score": 999})["score"] == 100
    assert _norm_audit({"verdict": "ok", "score": -5})["score"] == 0
    assert _norm_audit({"verdict": "ok", "score": "не знаю"})["score"] == 0


def test_garbage_answer_gives_none():
    assert _norm_audit(["список замість словника"]) is None


# --------------------------------------------------------------- ощадність ---
def test_same_card_is_audited_once(monkeypatch):
    """Одна й та сама картка двічі -> один запит. Квота безкоштовних провайдерів
    рахується подобово, а аудит і так подвоює витрату на кожну позицію."""
    seen = _spy(monkeypatch, '{"verdict":"ok","score":95,"issues":[]}')
    f = _card()
    a1 = audit_card(f, article="34116792217")
    a2 = audit_card(f, article="34116792217")
    assert a1 == a2 and len(seen) == 1


# ------------------------------------------------------------ рядок статусу ---
def test_status_line_marks_who_is_speaking():
    """У клітинці вже стоїть вердикт валідатора (це ФАКТ, порахований кодом).
    Думка ШІ мусить бути підписана, щоб власник бачив, що її можна ігнорувати."""
    line = audit_line({"verdict": "fix", "score": 50,
                       "issues": ["запити: замало фраз", "мета: нема номера"]})
    assert line.startswith("ШІ: ")
    assert "замало фраз" in line and "нема номера" in line
    assert audit_line({"verdict": "ok", "score": 98, "issues": []}) == "ШІ: ок"


# ------------------------------------------------------ перевірка за каноном ---
# Вимога власника 27.07: «заклади це як канонічний шаблон, якого треба
# притримуватися… цей крок перевірки також додай, щоб була перевірка ШІ за цими
# вимогами». Нижче — рівно про стик коду й моделі: що модель БАЧИТЬ і що вона
# не має права зіпсувати.

def test_the_marketplace_section_reaches_the_audit(monkeypatch):
    """Правило `section` у промпті стояло (who='обидва'), а самих полів у payload
    не було: модель просили подивитись на те, чого їй не показали."""
    seen = _spy(monkeypatch, '{"verdict":"ok","issues":[]}')
    f = _card()
    f.update({"Ідентифікатор_підрозділу": "341523",
              "Посилання_підрозділу": "https://prom.ua/Pylniki-avtomobilnye"})
    audit_card(f, article="34116792217")
    payload = seen[0][1]
    assert "341523" in payload and "Pylniki-avtomobilnye" in payload


def test_code_findings_are_handed_to_the_model(monkeypatch):
    """Модель має право лише на 6 зауважень. Якщо вона витратить їх на переказ
    того, що й так порахував код, місця на власне спостереження не лишиться."""
    seen = _spy(monkeypatch, '{"verdict":"ok","issues":[]}')
    audit_card(_card(), article="34116792217",
               known=["порожня характеристика «Код запчастини»"])
    payload = seen[0][1]
    assert "Вже_знайшов_код" in payload and "Код запчастини" in payload
    # межа лишилась там, де була
    for forbidden in ("2400", "1580", "Собівартість"):
        assert forbidden not in payload, forbidden


def test_code_findings_survive_a_silent_provider(monkeypatch):
    """Розбіжність із канонічною таблицею — це ФАКТ, порахований кодом. Зникати
    разом із провайдером, квотою чи вимикачем він не має права."""
    monkeypatch.setattr(ai_layer, "_ai_call", lambda s, u: None)
    res = audit_card(_card(), article="34116792217", known=["групи 999 немає в довіднику"])
    assert res and res["ai"] is False and res["verdict"] == "fix"
    assert audit_line(res).startswith("Канон: ")
    assert "999" in audit_line(res)


def test_canon_is_shown_even_with_the_ai_switch_off(monkeypatch):
    """AI_AUDIT=0 вимикає ДУМКУ моделі, а не перевірку за довідником."""
    seen = _spy(monkeypatch, '{"verdict":"ok","issues":[]}')
    monkeypatch.setenv("AI_AUDIT", "0")
    res = audit_card(_card(), article="34116792217", known=["нема підрозділу"])
    assert seen == [], "квота не витрачається"
    assert audit_line(res) == "Канон: нема підрозділу"
    # «Без ШІ» в пульті — те саме
    assert audit_line(audit_card(_card(), article="34116792217",
                                 known=["нема підрозділу"], use_ai=False)) == \
        "Канон: нема підрозділу"


def test_code_findings_come_first_and_are_not_duplicated(monkeypatch):
    """Знахідка коду точна, зауваження моделі дорадче — тому код попереду.
    А якщо модель переказала те саме, дубль у клітинку не їде."""
    _spy(monkeypatch, '{"verdict":"ok","score":90,"issues":['
                      '{"field":"","why":"групи 999 немає в довіднику"},'
                      '{"field":"запити","why":"замало фраз"}]}')
    res = audit_card(_card(), article="34116792217", known=["групи 999 немає в довіднику"])
    assert res["issues"] == ["групи 999 немає в довіднику", "запити: замало фраз"]
    assert res["verdict"] == "fix" and res["ai"] is True
    assert audit_line(res).startswith("ШІ: ")


def test_prompt_carries_the_hard_limits(monkeypatch):
    """Промпт аудиту — це і є «жорсткі правила Prom та Google» словами. Якщо
    хтось витре з нього межі, ШІ мовчки перестане їх перевіряти, і помітити це
    буде ніяк. Тому числа зафіксовані тестом."""
    seen = _spy(monkeypatch, '{"verdict":"ok","issues":[]}')
    audit_card(_card(), article="34116792217")
    system = seen[0][0]
    for token in ("110", "70", "160", "15-40", "400-800", "Ми підберемо за вас"):
        assert token in system, token
    assert "НЕ переписуєш" in system


# -------------------------------------------------- аудит нічого не вирішує ---
def test_pipeline_publishes_even_when_ai_says_fix(monkeypatch):
    """Найголовніший тест шару. ШІ відповідає «fix» на КОЖЕН запит — і на
    створення тексту, і на аудит. У бойову таблицю однаково їде рівно та
    позиція, яку туди відправив код: рівень 1 з групою, що мапиться.

    Якби вердикт ШІ мав хоч якусь вагу в маршрутизації, тут в Export не було б
    нічого — а на бойовій таблиці це означало б зупинку додавання товарів через
    те, що чужа безкоштовна модель у поганому гуморі."""
    from adding.panel import ensure_panel, read_panel
    from adding.review import do_review
    from adding.run import do_enrich
    from adding.review import C_TAKE
    from common.config import EXPORT_TAB, PANEL_TAB, REVIEW_TAB, STAGING_TAB
    from tests.fakes import FakeBM, FakeSpreadsheet
    from tests.test_pipeline_dry import EX_HEAD, PANEL_SEED

    monkeypatch.setattr(ai_layer, "_ai_call",
                        lambda s, u: json.dumps({"verdict": "fix", "score": 10,
                                                 "issues": [{"field": "назва",
                                                             "why": "мені не подобається"}]},
                                                ensure_ascii=False))
    import adding.review as review
    monkeypatch.setattr(review, "_bm", lambda: FakeBM())

    book = FakeSpreadsheet()
    book.add_worksheet(EXPORT_TAB, cols=len(EX_HEAD)).update(values=[EX_HEAD], range_name="A1")
    panel = [list(r) for r in PANEL_SEED]
    panel[5][1] = "Повний"                       # ШІ увімкнено -> аудит теж
    book.add_worksheet(PANEL_TAB, cols=3).update(values=panel, range_name="A1")

    ensure_panel(book)
    st = read_panel(book)
    assert st["ai"] == "Повний"
    do_review(book, st)

    rv = book.ws(REVIEW_TAB)
    for r in range(2, len(rv.get_all_values()) + 1):
        rv._put(r, C_TAKE + 1, "TRUE")
    do_enrich(book, st)

    ex = book.ws(EXPORT_TAB).get_all_values()
    stg = book.ws(STAGING_TAB).get_all_values()
    assert [r[0] for r in ex[1:]] == ["34116792217"]
    assert {r[0] for r in stg[1:]} == {"11517586925", "34116794300", "63117214941"}

    # …а зауваження ШІ при цьому таки видно власнику в огляді
    rows = rv.get_all_values()
    i_st = rows[0].index("Статус")
    assert any("ШІ:" in r[i_st] for r in rows[1:])
