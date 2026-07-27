# -*- coding: utf-8 -*-
# Правило власника «ТІЛЬКИ ОРИГІНАЛ». BMParts.search_uuid() при неточному збігу
# віддає ПЕРШИЙ-ліпший результат пошуку. Без перевірки на картку оригінальної
# деталі BMW потрапили б фото і характеристики аналога. _verify() пропускає лише
# точний збіг артикула або той самий бренд, у чиєму списку OEM є наш номер.
from adding.sources import candidate, dedup, key
from adding.sources.lookup import _codes_to_try, _verify


def test_exact_article_match_passes():
    assert _verify({"article": "11427953129", "brand": "BMW"}, "11427953129")


def test_match_ignores_spaces_and_case():
    # Номер BMW у прайсі може бути записаний як завгодно; у нас він завжди суцільний.
    assert _verify({"article": "11 42 7 953 129"}, "11427953129")
    assert _verify({"article": "11427953129"}, "11 42 7 953 129")


def test_foreign_analog_is_rejected():
    # Пошук віддав аналог MANN замість оригіналу BMW — не наша деталь.
    prod = {"article": "HU7008Z", "brand": "MANN",
            "oe": [{"number": "11427953129", "is_oem": True}]}
    assert not _verify(prod, "11427953129", brand="BMW")


def test_same_brand_via_oem_list_passes():
    # Той самий бренд, інший внутрішній артикул, але наш номер серед OEM — це воно.
    prod = {"article": "BMW-7953129", "brand": "BMW",
            "oe": [{"number": "11427953129", "is_oem": True}]}
    assert _verify(prod, "11427953129", brand="BMW")


def test_non_oem_reference_does_not_pass():
    # Номер у списку як НЕ-OEM (крос-посилання) — недостатньо, щоб визнати деталь.
    prod = {"article": "X1", "brand": "BMW",
            "oe": [{"number": "11427953129", "is_oem": False}]}
    assert not _verify(prod, "11427953129", brand="BMW")


def test_empty_article_never_matches():
    assert not _verify({"article": ""}, "")


def test_hyphenated_code_expands_to_both_numbers():
    # «51117303107-108» у прайсі — це ДВА повних номери, а не один із дефісом.
    codes = _codes_to_try("51117303107-108")
    assert "51117303107" in codes
    assert codes[0] == "51117303107-108"


def test_key_normalizes_article():
    assert key("11 42 7 953 129") == key("11427953129")


def test_dedup_keeps_cheaper_supplier():
    a = candidate("BMW прайс (Баварія)", "11427953129", "Фільтр", 420)
    b = candidate("BM Parts", "11 42 7 953 129", "Фільтр", 300)
    out = dedup([a, b])
    assert len(out) == 1 and out[0]["cost"] == 300


def test_dedup_drops_rows_without_article():
    out = dedup([candidate("BM Parts", "", "Без коду", 100)])
    assert out == []
