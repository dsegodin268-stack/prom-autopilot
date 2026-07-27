# -*- coding: utf-8 -*-
"""ЖОРСТКІ МЕЖІ PROM І GOOGLE — рахує код, а не око.

Ці перевірки з'явились 27.07 після живого тесту трьох карток BMW, який показав,
що конвеєр мовчки випускав у бойову таблицю: мета-заголовки на 91-96 символів
при межі 70, дев'ять пошукових запитів при межі 15, мета-опис без каталожного
номера, сміттєві ключовики «(BMW)» і «BMW x36», хвіст «купити Київ» у КОЖНІЙ
меті й картку без обов'язкових характеристик «Артикул» і «Гарантія».

Розподіл обов'язків, який тут закріплено:
  • card_builder.enforce_limits() — ШЛЮЗ: те, що рахується (довжина, кількість,
    заборонені слова), обрізається залізно й ДО, і ПІСЛЯ втручання ШІ;
  • validator.validate_*()        — ОЦІНКА: пише в звіт, що саме не так;
  • ШІ                            — дорадчий, жодного права вирішувати.
Тому кожен тест нижче ганяє детермінований шлях, без мережі й без ключів.
"""
from adding.card_builder import (META_DESC_MAX, META_TITLE_MAX, _car_tokens,
                                 _display_name, _fitment, _part_token, clean_details,
                                 enforce_limits, gen_keywords, html_desc, meta_desc,
                                 meta_title)
from adding.validator import (WARN, validate_desc_length, validate_keywords,
                              validate_meta)


def _codes(flags):
    return {c for (_lvl, c, _msg) in flags}


# ---------------------------------------------------------------- мета ---
def test_meta_title_fits_seventy_even_for_long_names():
    p = {"name": "Диск гальмівний передній вентильований BMW 3 G20 G21 4 G22 G23 348x36 18-",
         "article": "34116889571"}
    t = meta_title(p, "ua")
    assert len(t) <= META_TITLE_MAX, t
    assert "34116889571" in t          # номер резервує собі місце ПЕРШИМ


def test_meta_has_no_city_and_no_buy_word():
    """§0-bis: міста і слово «купити» зі знімків чужих карток — НЕ копіювати.
    До 27.07 хвіст « купити Київ. Vision Dynamics» стояв у кожній картці."""
    p = {"name": "Фільтр масляний BMW 3 G20", "article": "11427953129"}
    both = (meta_title(p, "ua") + " " + meta_desc(p, "ua")).lower()
    assert "київ" not in both and "киев" not in both
    assert "купити" not in both and "купить" not in both


def test_meta_desc_falls_back_to_article_when_no_oem():
    """Позиція з прайсу, якої нема в довіднику: OEM нема взагалі. Раніше в
    мета-опис не потрапляв ЖОДЕН номер — §0 вимагає протилежного."""
    p = {"name": "Патрубок системи охолодження BMW", "article": "11537549476"}
    d = meta_desc(p, "ua")
    assert "11537549476" in d
    assert len(d) <= META_DESC_MAX


def test_validate_meta_catches_length_city_and_missing_article():
    long_title = "Диск гальмівний передній вентильований BMW 3 G20 G21 4 G22 G23 348x36 оригінал"
    flags = validate_meta(long_title, "Купити недорого в Києві", "34116889571")
    codes = _codes(flags)
    assert "meta_title_len" in codes
    assert "meta_title_no_art" in codes
    assert "meta_desc_seo" in codes and "meta_desc_region" in codes
    assert all(lvl == WARN for (lvl, _c, _m) in flags)


def test_country_in_meta_is_not_a_city_but_in_keywords_it_is():
    """Місто і країна — різні речі. «Купити в Києві» в меті — це нав'язування
    міста, яке §0-bis забороняє. «Відправка щодня по Україні» — звичайна фраза
    про доставку в сніпеті Google, і вона стоїть у КОЖНІЙ нашій картці: поки
    обидва слова лежали в одному списку, прапорець meta_desc_region висів
    завжди, а попередження, яке горить завжди, перестають читати.
    У ключових запитах країна лишається браком: «фільтр Україна» ніхто не
    набирає, а місце у списку 15-40 фраз воно з'їдає."""
    quiet = validate_meta("Фільтр масляний BMW 11427953129",
                          "Фільтр масляний BMW. OEM 11427953129. Відправка щодня по Україні.",
                          "11427953129")
    assert "meta_desc_region" not in _codes(quiet)
    assert "meta_desc_region" in _codes(
        validate_meta("Фільтр 11427953129", "Купити в Києві 11427953129", "11427953129"))
    assert "kw_region" in _codes(validate_keywords(["фільтр масляний Україна", "диск BMW"]))


def test_validate_meta_is_quiet_when_everything_fits():
    assert validate_meta("Фільтр масляний BMW 3 G20 11427953129",
                         "Фільтр масляний BMW 3 G20. OEM 11427953129. Оригінал і аналоги.",
                         "11427953129") == []


def test_description_always_carries_a_number_even_without_oem():
    """Позиція з прайсу, якої нема в довіднику: OEM нема, і в описі не лишалось
    ЖОДНОГО номера — а Google індексує саме текст опису. Правило власника:
    позицію мусить знайти покупець за каталожним номером. Тут цей номер — сам
    артикул, іншого в нас нема."""
    d = html_desc({"name": "Патрубок системи охолодження BMW", "brand": "BMW",
                   "article": "11537549476"}, "ua")
    assert "11537549476" in d
    assert "Каталожний номер" in d and "OEM" not in d
    # там, де OEM є, підпис лишається старим — підміни не відбувається
    withoem = html_desc({"name": "Фільтр масляний BMW", "brand": "BMW",
                         "article": "11427953129",
                         "oe": [{"number": "11427953129", "is_oem": True}]}, "ua")
    assert "OEM" in withoem and "Каталожний номер" not in withoem


# ----------------------------------------------------------- ключовики ---
def test_part_token_takes_the_number_not_the_brackets():
    """Було r.split()[-1]: «11427854445 (BMW)» → ключовик «(BMW)», а справжній
    альтернативний номер не потрапляв у список узагалі."""
    assert _part_token("11427854445 (BMW)") == "11427854445"
    assert _part_token("MANN HU6004X") == "HU6004X"
    assert _part_token("") == ""


def test_car_tokens_do_not_split_a_disc_size():
    """«348x36» — це розмір диска, а не код кузова. Раніше звідси народжувався
    неіснуючий ключовик «BMW x36»."""
    assert "x36" not in _car_tokens("Диск гальмівний передній BMW 3 G20 348x36")
    assert "G20" in _car_tokens("Диск гальмівний передній BMW 3 G20 348x36")


def test_generated_keywords_have_no_junk_no_city_no_generic_words():
    p = {"name": "Диск гальмівний передній BMW 3 G20 348x36", "brand": "BMW",
         "article": "34116889571",
         "oe": [{"number": "34116889571", "is_oem": True},
                {"number": "34116792217 (BMW)", "is_oem": False}]}
    kws = gen_keywords(p, "ua")
    low = " | ".join(kws).lower()
    assert "київ" not in low and "запчастини" not in low and "купити" not in low
    assert not any("(" in k or ")" in k for k in kws)
    assert "bmw x36" not in low
    assert len(kws) <= 40


def test_one_word_keyword_is_dropped_but_a_number_stays():
    """Prom шукає збіг усередині ОДНІЄЇ фрази, тому ключовик «BMW» означає
    «показуй мою картку на кожен запит зі словом BMW»: покупець, який шукає
    диски, бачить масляний фільтр і йде геть, а сама деталь від цього не
    знаходиться жодного разу. Те саме з голим «фільтр».
    Цифри — свідомий виняток: «11427953129» теж одне слово, але це каталожний
    номер, і вимога власника «позицію мусить знайти пошук за номером» важливіша
    за правило про цілі фрази."""
    p = {"name": "Фільтр масляний BMW 3 G20", "brand": "BMW", "article": "11427953129",
         "oe": [{"number": "11427953129", "is_oem": True}]}
    kws = gen_keywords(p, "ua")
    assert all(len(k.split()) > 1 for k in kws if not any(ch.isdigit() for ch in k)), kws
    assert "11427953129" in kws
    # той самий фільтр стоїть і в шлюзі — після ШІ теж
    f = {"Пошукові_запити_укр": "BMW, фільтр, 11427953129, фільтр масляний BMW"}
    enforce_limits(f, "11427953129")
    left = [k.strip() for k in f["Пошукові_запити_укр"].split(",")]
    assert "BMW" not in left and "фільтр" not in left
    assert "11427953129" in left and "фільтр масляний BMW" in left


def test_validate_keywords_counts_the_floor_and_the_ceiling():
    assert "kw_few" in _codes(validate_keywords(["диск", "диск BMW", "диск передній"]))
    assert "kw_many" in _codes(validate_keywords([f"фраза {i}" for i in range(45)]))


def test_validate_keywords_catches_junk_region_dup_and_missing_article():
    kws = ["(BMW)", "диск гальмівний Київ", "диск гальмівний", "диск гальмівний",
           "купити диск"]
    codes = _codes(validate_keywords(kws, "34116889571"))
    assert {"kw_junk", "kw_region", "kw_dup", "kw_seo", "kw_no_art"} <= codes


def test_validate_keywords_accepts_a_comma_string_too():
    # У картці ключовики лежать одним рядком через кому — валідатор має вміти обидва.
    assert "kw_empty" not in _codes(validate_keywords("диск, диск BMW, диск передній"))


# --------------------------------------------------------- довжина опису ---
def test_desc_length_counts_text_not_tags():
    short = "<p>" + "а" * 100 + "</p>"
    assert "desc_thin" in _codes(validate_desc_length(short))
    ok = "<p>" + "а" * 500 + "</p>"
    assert validate_desc_length(ok) == []


# ------------------------------------------------------------- шлюз меж ---
def test_enforce_limits_clamps_whatever_the_ai_returned():
    """Головне в дворівневій схемі: ШІ може повернути що завгодно — довгу мету,
    сорок дев'ять ключовиків, «купити оптом». Шлюз ріже це ПІСЛЯ merge_ai(),
    тому жоден варіант відповіді ШІ не пролазить у бойову таблицю."""
    f = {"HTML_заголовок_укр": "Неймовірно вигідна пропозиція " * 5,
         "HTML_опис_укр": "Купуйте прямо зараз. " * 20,
         "Пошукові_запити_укр": ", ".join(["купити диск", "(BMW)", "ok"]
                                          + [f"фраза {i}" for i in range(50)])}
    enforce_limits(f, "34116889571")

    assert len(f["HTML_заголовок_укр"]) <= META_TITLE_MAX
    assert len(f["HTML_опис_укр"]) <= META_DESC_MAX
    assert "34116889571" in f["HTML_заголовок_укр"]
    assert "34116889571" in f["HTML_опис_укр"]

    kws = [k.strip() for k in f["Пошукові_запити_укр"].split(",")]
    assert len(kws) <= 40
    assert "купити диск" not in kws and "(BMW)" not in kws


def test_enforce_limits_does_not_invent_fields_it_was_not_given():
    f = {"Назва_позиції_укр": "Диск гальмівний"}
    assert enforce_limits(dict(f), "123") == f


def test_enforce_limits_drops_duplicate_keywords():
    f = {"Пошукові_запити_укр": "диск BMW, Диск BMW, диск bmw, диск передній"}
    enforce_limits(f, "")
    assert len(f["Пошукові_запити_укр"].split(",")) == 2


# ------------------------------------------------- характеристики й назва ---
def test_required_characteristics_survive_cleaning():
    """§5 перелічує «Артикул» і «Гарантія» серед ОБОВ'ЯЗКОВИХ, а фільтр
    _DROP_NAME мовчки зрізав обидва — картка їхала в Prom без них."""
    prod = {"details": {"Виробник": "BMW", "Артикул": "11427953129",
                        "Гарантія [міс]": "12", "Код виробника": "X1",
                        "Штрихкод": "4008321012345"}}
    names = [n for (n, _u, _v) in clean_details(prod)]
    assert "Артикул" in names and "Гарантія" in names
    assert "Код виробника" not in names and "Штрихкод" not in names


def test_display_name_is_the_same_string_everywhere():
    """Один товар мав три різні написання заголовка в одній картці: чиста назва
    в «Назва_позиції», а опис і мета брали сиру, з висячим «18-»."""
    raw = "Диск гальмівний передній BMW 3 G20 348x36 18-"
    n = _display_name(raw)
    assert not n.endswith("18-") and n.endswith("348x36")
    assert n in meta_title({"name": raw, "article": ""}, "ua")


def test_fitment_years_are_humanized_from_the_catalogue_too():
    """Раніше _humanize_years() стояв лише в запасному розборі назви, тому
    сумісність із BM Parts їхала в опис як «18-» замість «2018+»."""
    prod = {"brand": "BMW", "cars": [{"brand": "BMW", "model": "3 G20", "years": "18-"},
                                     {"brand": "BMW", "model": "5 G30", "years": "16-23"}]}
    fit = " | ".join(_fitment(prod, "Диск гальмівний BMW"))
    assert "2018+" in fit and "2016-2023" in fit
    assert "18-" not in fit.replace("2018-", "")
