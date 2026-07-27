# -*- coding: utf-8 -*-
"""ДРУГИЙ ПРОХІД ШІ — той, що не лише світить червоним, а й дописує.

Вимога власника 27.07: «до цього всього треба докрутити ШІ, який буде це все
перевіряти по жорсткій інструкції, І ДОПОВНЮВАТИ, і робити повноцінну картку,
яка одразу залітає вже в кабінет».

Схема, яку ці тести закріплюють, — та сама, що й в аудиті, лише з третім кроком:

    код   — вирішує   (enforce_limits ріже межі, validator рахує, route маршрутизує)
    ШІ    — коментує  (audit_card дає зауваження)
    ШІ    — дописує   (repair_card переписує ТЕКСТ за цими зауваженнями)
    код   — вирішує ЩЕ РАЗ (та сама валідація, не полегшена)

Головне, що тут перевіряється, — межі ДРУГОГО кроку. ПРАВИЛА §8 забороняють ШІ
чіпати Код_товару, Ціну, Валюту, Наявність, Кількість, Фото, Групу, Виробника,
GTIN і характеристики. Заборона тримається не обіцянкою в промпті, а будовою:
merge_ai фізично вміє писати лише в 10 текстових ключів, а repairable() ще й не
пускає до моделі зауваження про технічні поля. Нижче — обидва замки окремо.

Мережі тут немає: _ai_call підмінюється у кожному тесті.
"""
import json

import pytest

from adding import ai_layer
from adding.ai_layer import repair_fields, repair_on, repairable
from adding.card_builder import repair_card

PRODUCT = {
    "article": "34116792217", "brand": "BMW",
    "name": "Диск гальмівний передній BMW 3 F30",
    "images": ["images/f0.jpg"], "nodes": "Гальмівні диски",
    "details": {"Виробник": "BMW", "Діаметр [мм]": "330", "Вісь": "передня"},
    "oe": [{"number": "34116792217", "is_oem": True}],
    "cars": [{"brand": "BMW", "model": "3 F30", "years": "12-18"}],
}


def _card():
    """Готова картка так, як її бачить run.py: разом із грошима й технікою."""
    return {"Код_товару": "34116792217",
            "Назва_позиції_укр": "Диск 34116792217",
            "Назва_позиції": "Диск 34116792217",
            "Пошукові_запити_укр": "диск",
            "Пошукові_запити": "диск",
            "Опис_укр": "<p>Диск.</p>",
            "Опис": "<p>Диск.</p>",
            "HTML_заголовок_укр": "Диск",
            "HTML_заголовок": "Диск",
            "HTML_опис_укр": "Диск BMW.",
            "HTML_опис": "Диск BMW.",
            # --- технічні поля: їх не має торкнутися ніхто, крім коду ---
            "Номер_групи": "138537679", "Назва_групи": "Тормозные диски",
            "Виробник": "BMW", "Вага,кг": "6.5",
            "Посилання_зображення": "https://bm.parts/images/f0.jpg",
            "Ідентифікатор_підрозділу": "341523",
            # --- те, що НЕ має піти до третьої сторони ---
            "Ціна": "2400", "Собівартість": "1580", "Валюта": "UAH",
            "Наявність": "!", "Кількість": "3"}


GOOD_ANSWER = json.dumps({
    "name_ua": "Диск гальмівний передній BMW 3 F30 34116792217",
    "name_ru": "Диск тормозной передний BMW 3 F30 34116792217",
    "keywords_ua": ["диск гальмівний BMW F30", "34116792217", "гальмівний диск BMW 3"],
    "keywords_ru": ["диск тормозной BMW F30", "34116792217"],
    "desc_ua": "<p>Оригінальний гальмівний диск BMW 34116792217. Діаметр 330 мм, "
               "передня вісь. Підходить на BMW 3 F30.</p>",
    "desc_ru": "<p>Оригинальный тормозной диск BMW 34116792217.</p>",
    "meta_title_ua": "Диск гальмівний BMW 3 F30 34116792217",
    "meta_title_ru": "Диск тормозной BMW 3 F30 34116792217",
    "meta_desc_ua": "Оригінальний диск BMW 34116792217, діаметр 330 мм, передня вісь.",
    "meta_desc_ru": "Оригинальный диск BMW 34116792217.",
}, ensure_ascii=False)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    """Кожен тест починає з чистої пам'яті правок і увімкненим AI_FIX."""
    ai_layer._fix_memo.clear()
    monkeypatch.delenv("AI_FIX", raising=False)
    yield
    ai_layer._fix_memo.clear()


def _spy(monkeypatch, answer):
    """Підміна _ai_call: запам'ятовує payload і віддає готову відповідь."""
    seen = []

    def fake(system, user_json):
        seen.append((system, user_json))
        return answer

    monkeypatch.setattr(ai_layer, "_ai_call", fake)
    return seen


# ------------------------------------------------------- ЩО ВЗАГАЛІ ЛІКУЄМО --
def test_only_text_issues_reach_the_model():
    """Зауваження про текст — до моделі; про техніку — ні.

    Це перший із двох замків. «Групи 999 немає в довіднику» не лікується
    красивішим описом: попросиш модель це «виправити» — отримаєш вигаданий
    номер групи, тобто рівно ту аварію, від якої втікали."""
    issues = ["назва: немає моделі авто",
              "мета: заголовок довший за 70 символів",
              "запити: лише 2 ключовики",
              "опис: коротший за 500 символів",
              "характеристики: лише 2 з обов'язкових",
              "група: 999 немає в довіднику",
              "фото: адреса веде на інший артикул",
              "вага: 0,01 кг у гальмівного диска",
              "підрозділ: не вказаний"]
    assert repairable(issues) == issues[:4]


def test_canon_findings_have_no_field_prefix_so_they_never_get_repaired():
    """Знахідки коду за каноном (validator.validate_canon) приходять у той самий
    список issues — але без префікса «поле:». Вони мусять піти на ручну курацію
    (Staging), а не в переписування тексту."""
    canon_notes = ["Групи 999 немає в довіднику магазину",
                   "Немає обов'язкових характеристик: Код запчастини, Виробник",
                   "Підрозділ маркетплейсу не вказаний — картка на ручну курацію"]
    assert repairable(canon_notes) == []


def test_nothing_repairable_means_no_request_at_all(monkeypatch):
    """Квота безкоштовних провайдерів кінцева. Якщо лікувати нічого — запиту
    немає взагалі, а не «запит із порожнім списком»."""
    seen = _spy(monkeypatch, GOOD_ANSWER)
    assert repair_fields({"article": "34116792217"}, ["група: немає"]) is None
    assert seen == [], "витратили запит на зауваження, яке текстом не лікується"


# ------------------------------------------------------------- ЩО ЇДЕ НАЗОВНІ --
def test_the_model_sees_the_current_card_and_the_complaints(monkeypatch):
    """Другий прохід без поточних текстів — це просто ще одне створення картки.
    Модель має бачити, ЩО вже написано і ЩО з цим не так, інакше вона перепише
    все з нуля й загубить те, що було правильним."""
    seen = _spy(monkeypatch, GOOD_ANSWER)
    f = _card()
    repair_card(f, PRODUCT, ["назва: немає моделі авто"])

    assert len(seen) == 1
    payload = json.loads(seen[0][1])
    assert payload["зауваження"] == ["назва: немає моделі авто"]
    assert payload["поточна_картка"]["Назва_позиції_укр"] == "Диск 34116792217"
    assert payload["факти"]["article"] == "34116792217"
    # І окремо — системний промпт мусить пояснити, що це ДРУГИЙ прохід.
    assert "ДРУГИЙ ПРОХІД" in seen[0][0]


def test_no_money_leaves_the_house_on_the_second_pass(monkeypatch):
    """Той самий замок, що і в аудиті: ціна, собівартість і залишки складу до
    третьої сторони не їдуть. Другий прохід — це ще один канал назовні, і його
    треба замикати окремо, а не сподіватися на замок першого."""
    seen = _spy(monkeypatch, GOOD_ANSWER)
    repair_card(_card(), PRODUCT, ["опис: закороткий"])

    blob = seen[0][1]
    for forbidden in ("2400", "1580", "Собівартість", "Ціна", "Кількість"):
        assert forbidden not in blob, f"«{forbidden}» поїхало до провайдера"


# ----------------------------------------------------- ЧОГО ШІ НЕ МОЖЕ ЗЛАМАТИ --
def test_repair_touches_only_the_ten_text_fields(monkeypatch):
    """ПРАВИЛА §8 буквально. Модель відповідає повним словником — а в картці
    міняється рівно текст. Група, ціна, наявність, фото, вага, виробник і
    підрозділ лишаються такими, якими їх порахував код."""
    monkeypatch.setattr(ai_layer, "_ai_call", lambda s, u: json.dumps(
        {**json.loads(GOOD_ANSWER),
         # модель «люб'язно» пропонує ще й техніку — це має бути проігноровано
         "Номер_групи": "999", "Ціна": "9999", "Наявність": "-",
         "Кількість": "0", "Вага,кг": "0.01", "Виробник": "NoName",
         "Посилання_зображення": "https://example.com/other.jpg"}, ensure_ascii=False))
    f = _card()
    before = {k: v for k, v in f.items()}
    changed = repair_card(f, PRODUCT, ["назва: немає моделі авто"])

    assert "Назва_позиції_укр" in changed
    for tech in ("Номер_групи", "Назва_групи", "Виробник", "Вага,кг", "Ціна",
                 "Собівартість", "Валюта", "Наявність", "Кількість",
                 "Посилання_зображення", "Ідентифікатор_підрозділу", "Код_товару"):
        assert f[tech] == before[tech], f"ШІ дотягнувся до «{tech}»"


def test_the_repair_goes_through_the_same_gate(monkeypatch):
    """Відповідь другого проходу — такий самий сирий текст від провайдера, як і
    першого, і поблажок їй не робиться: enforce_limits ріже назву так само."""
    long_name = "Диск гальмівний передній BMW 3 F30 34116792217 " + "дуже " * 40
    monkeypatch.setattr(ai_layer, "_ai_call", lambda s, u: json.dumps(
        {**json.loads(GOOD_ANSWER), "name_ua": long_name}, ensure_ascii=False))
    f = _card()
    repair_card(f, PRODUCT, ["назва: немає моделі авто"])

    assert len(f["Назва_позиції_укр"]) <= 110, "довга назва пройшла повз ворота"


def test_an_invented_number_in_the_repair_is_thrown_away(monkeypatch):
    """Найдорожча помилка другого проходу — модель, «виправляючи» назву, вписує
    номер, якого у фактах не було. Покупець за таким номером знайде чужу деталь.
    numbers_ok ловить це так само, як і на першому проході: картка лишається
    старою, але правдивою."""
    monkeypatch.setattr(ai_layer, "_ai_call", lambda s, u: json.dumps(
        {**json.loads(GOOD_ANSWER),
         "name_ua": "Диск гальмівний передній BMW 3 F30 34116799999"}, ensure_ascii=False))
    f = _card()
    changed = repair_card(f, PRODUCT, ["назва: немає моделі авто"])

    assert changed == []
    assert f["Назва_позиції_укр"] == "Диск 34116792217", "вигадка потрапила в картку"


def test_a_silent_provider_leaves_the_card_as_it_was(monkeypatch):
    """Нема ключів / вичерпано квоту / провайдер мовчить — картка просто лишається
    такою, якою її зробив код. Другий прохід не має права нічого зупиняти."""
    monkeypatch.setattr(ai_layer, "_ai_call", lambda s, u: "")
    f = _card()
    assert repair_card(f, PRODUCT, ["назва: немає моделі авто"]) == []
    assert f["Назва_позиції_укр"] == "Диск 34116792217"


def test_broken_json_is_not_a_reason_to_lose_the_card(monkeypatch):
    monkeypatch.setattr(ai_layer, "_ai_call",
                        lambda s, u: "Вибачте, я не можу переписати цю картку.")
    f = _card()
    assert repair_card(f, PRODUCT, ["опис: закороткий"]) == []
    assert f["Опис_укр"] == "<p>Диск.</p>"


# --------------------------------------------------------------- ВИМИКАЧІ ----
def test_ai_fix_0_disables_the_second_pass(monkeypatch):
    """Третій запит на позицію коштує квоти. Вимикач мусить бути, і мусить
    вимикати ДО запиту, а не після."""
    seen = _spy(monkeypatch, GOOD_ANSWER)
    monkeypatch.setenv("AI_FIX", "0")
    assert repair_on() is False
    f = _card()
    assert repair_card(f, PRODUCT, ["назва: немає моделі авто"]) == []
    assert seen == []


def test_the_panel_switch_off_also_stops_the_repair(monkeypatch):
    """«Без ШІ» в пульті -> use_ai=False по всьому конвеєру, включно з правкою."""
    seen = _spy(monkeypatch, GOOD_ANSWER)
    assert repair_card(_card(), PRODUCT, ["назва: немає"], use_ai=False) == []
    assert seen == []


def test_repair_is_on_by_default():
    assert repair_on() is True
