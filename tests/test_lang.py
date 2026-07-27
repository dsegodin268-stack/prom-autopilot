# -*- coding: utf-8 -*-
# Мова полів не змішується.
#
# Дефект прогону №18: у бойову таблицю пішла назва «Пыльник амортизатора
# (переднього)». Словник перекладу знав слово «пильник» і не знав слова
# «переднього» — тому половина назви лишилась українською. Prom такі назви
# приймає мовчки, отже спіймати це міг лише код, і він не ловив.
from adding.card_builder import ua2ru
from adding.rules import lang_mixed
from adding.validator import validate_lang


# --------------------------------------------------------------- ПЕРЕКЛАД ---

def test_the_exact_name_that_broke_in_run_18():
    """Вартовий тест. Саме цей рядок ліг у таблицю напівперекладеним."""
    src = ("Пильник амортизатора (переднього) BMW 3 (F30)/4 (F33)/M4 (F83) "
           "31306791712")
    out = ua2ru(src)
    assert out.startswith("Пыльник амортизатора (переднего)")
    assert "переднього" not in out


def test_endings_are_translated_not_only_whole_words():
    assert ua2ru("Диск гальмівний передній") == "Диск тормозной передний"
    assert ua2ru("Колодки гальмівні передні") == "Колодки тормозные передние"
    assert ua2ru("Комплект гумових килимків") == "Комплект резиновых ковриков"


def test_numbers_and_latin_are_untouched():
    """Марки, кузови й каталожні номери латиницею — не предмет перекладу."""
    out = ua2ru("Фільтр масляний BMW 3 (F30) 11427953129")
    assert "BMW 3 (F30) 11427953129" in out
    assert out.startswith("Фильтр масляный")


def test_half_translation_reverts_to_source():
    """Правило «або все, або нічого». Якщо після перекладу лишились українські
    ознаки — повертаємо ОРИГІНАЛ: чиста українська виглядає нормально, а суміш
    читається як недогляд і ламає російськомовний пошук."""
    src = "Кронштейн підсилювача заднього бампера"   # «підсилювача» словник не знає
    out = ua2ru(src)
    assert out == src or not any(ch in out for ch in "іїєґ")


def test_already_russian_text_is_not_mangled():
    assert ua2ru("Диск тормозной передний") == "Диск тормозной передний"


def test_empty_input():
    assert ua2ru("") == ""
    assert ua2ru(None) == ""


# ----------------------------------------------------------- ПЕРЕВІРКА МОВИ ---

def test_mixed_language_is_caught():
    assert lang_mixed("Пыльник амортизатора (переднього)", want="ru")
    assert lang_mixed("Пыльник амортизатора (переднього)", want="ua")


def test_clean_ukrainian_passes_as_ua():
    assert lang_mixed("Пильник амортизатора переднього BMW", want="ua") == ""


def test_clean_russian_passes_as_ru():
    assert lang_mixed("Пыльник амортизатора переднего BMW", want="ru") == ""


def test_russian_in_a_ukrainian_field_is_caught():
    assert lang_mixed("Пыльник амортизатора переднего", want="ua")


def test_ukrainian_in_a_russian_field_is_caught():
    assert lang_mixed("Пильник амортизатора переднього", want="ru")


def test_latin_only_is_not_a_language_mix():
    assert lang_mixed("BMW 3 (F30) 31306791712", want="ua") == ""
    assert lang_mixed("BMW 3 (F30) 31306791712", want="ru") == ""


def test_russian_soft_endings_are_not_mistaken_for_ukrainian():
    """«передними», «синими» — нормальна російська. Якби «ими» рахувалось
    українською ознакою, кожна друга російська назва ловила б вигаданий брак."""
    assert lang_mixed("Диск тормозной с передними колодками", want="ru") == ""


def test_empty_field_is_not_a_problem():
    assert lang_mixed("", want="ua") == ""
    assert lang_mixed(None, want="ru") == ""


# -------------------------------------------------------------- ВАЛІДАТОР ---

def _card(**kw):
    c = {"name": "Пильник амортизатора переднього BMW 3 (F30) 31306791712",
         "name_ru": "Пыльник амортизатора переднего BMW 3 (F30) 31306791712"}
    c.update(kw)
    return c


def test_validator_is_silent_on_a_clean_card():
    assert validate_lang(_card()) == []


def test_validator_catches_the_half_translated_name():
    flags = validate_lang(_card(
        name_ru="Пыльник амортизатора (переднього) BMW 31306791712"))
    assert flags
    assert flags[0][2] == "lang_mix"


def test_message_is_prefixed_so_the_ai_may_repair_it():
    """Префікс «назва: » обов'язковий: ai_layer.repairable() пропускає в другий
    прохід лише зауваження, що починаються з імені поля. Без префікса модель
    побачила б проблему й не мала б права її виправити."""
    from adding.ai_layer import repairable
    flags = validate_lang(_card(
        name_ru="Пыльник амортизатора (переднього) BMW 31306791712"))
    msgs = [m for (_f, _l, _c, m) in flags]
    assert all(m.startswith("назва: ") for m in msgs)
    assert repairable([{"field": "назва", "why": msgs[0]}]) or repairable(msgs)


def test_fields_that_were_not_passed_are_not_invented():
    """Старі виклики validate_card() нічого не знають про name_ru — і не мусять
    від цього отримувати зауваження."""
    assert validate_lang({"name": "Пильник амортизатора переднього"}) == []
