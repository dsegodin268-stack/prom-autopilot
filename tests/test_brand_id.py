# -*- coding: utf-8 -*-
from repricing.sources.autonova_web import _autonova_brand_for


def test_vag_codes_are_brand_1():
    # ⚠️ VAG-коди починаються з цифри, але це brandId 1, НЕ BMW (баг 2026-07-18)
    for code in ("4H0051701C", "8W1864777B3Q7", "4M0919303", "G055005A2", "80A057800", "3R0919311"):
        assert _autonova_brand_for(code) == 1, code


def test_bmw_pure_digits():
    assert _autonova_brand_for("13717599291") == 72
    assert _autonova_brand_for("51117303107") == 72


def test_mercedes_a_prefix():
    assert _autonova_brand_for("A1678992200") == 56


def test_porsche():
    # Porsche(81) критичний для каталогу: WAP-аксесуари і 9-шасі коди (2026-07-19)
    assert _autonova_brand_for("WAP0304500M") == 81
    assert _autonova_brand_for("992044100") == 81


def test_empty():
    assert _autonova_brand_for("") is None
