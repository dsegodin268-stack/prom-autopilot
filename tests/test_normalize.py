# -*- coding: utf-8 -*-
from common.normalize import num, _nkey, _expand_code


def test_nkey_hyphens():
    # BM Parts зберігає артикули з дефісами — матчимо нормалізовано (баг 2026-07-19)
    assert _nkey("20114-0050-99") == "20114005099"
    assert _nkey("19-064529") == "19064529"
    assert _nkey(" 7p1 061 500 041 ") == "7P1061500041"


def test_expand_code_suffix():
    assert _expand_code("51117303107-108") == ["51117303107", "51117303108"]
    assert _expand_code("51712150246-47") == ["51712150246", "51712150247"]
    assert _expand_code("51128078671-2") == ["51128078671", "51128078672"]


def test_expand_code_full_numbers():
    assert _expand_code("A-B") == ["A", "B"]
    assert _expand_code("51117303107") == ["51117303107"]
    assert _expand_code("") == []


def test_num():
    assert num("1 234,56") == 1234.56
    assert num("\xa01000") == 1000.0
    assert num("сміття") == 0.0
