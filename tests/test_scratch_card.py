# -*- coding: utf-8 -*-
"""Картка З НУЛЯ: позиції нема в каталозі BM Parts, факти відновлює ШІ.

Ризик цього режиму — вигадки. Тому недовіра стоїть у трьох місцях і кожне
перевіряється окремо:
  1) _scratch_clean відкидає відповідь не про той артикул, не про ту марку і
     характеристики з назвами поза канонічним списком;
  2) scratch_facts не має права нести до третьої сторони ціну й собівартість —
     те саме правило, що для ai_enrich і ai_check;
  3) scratch_product пише лише в ПОРОЖНІ поля: дані постачальника сильніші
     за модель, а ціни/наявності не торкається взагалі.
"""
import json

import pytest

import adding.ai_layer as ai
import adding.card_builder as cb


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    for d in (ai._used, ai._model_ok, ai._cooldown, ai._last_call, ai._memo):
        d.clear()
    yield


def _ans(**kw):
    base = {"article": "11427953129", "known": True, "type": "фільтр масляний",
            "category": "Фільтри", "fitment": ["BMW 3 F30 2011-2019"],
            "chars": [{"name": "Тип запчастини", "unit": "", "value": "фільтр масляний"}],
            "note": ""}
    base.update(kw)
    return base


# ------------------------------------------------------- фільтр відповіді ШІ
def test_clean_ok():
    got = ai._scratch_clean(_ans(), "11427953129", "BMW")
    assert got is not None
    fit, chars, typ, cat = got
    assert fit == ["BMW 3 F30 2011-2019"]
    assert chars == [("Тип запчастини", "", "фільтр масляний")]
    assert typ == "фільтр масляний" and cat == "Фільтри"


def test_clean_unknown_is_none():
    # «Не знаю» — правильна відповідь, і вона мусить дати рівно нічого.
    assert ai._scratch_clean(_ans(known=False), "11427953129", "BMW") is None


def test_clean_wrong_article_rejected(capsys):
    # Модель «виправила» номер на схожий -> вона відповідала про іншу деталь.
    assert ai._scratch_clean(_ans(article="11427953130"), "11427953129", "BMW") is None
    assert "11427953130" in capsys.readouterr().out


def test_clean_article_format_tolerant():
    # Той самий номер, записаний інакше, — це той самий номер.
    assert ai._scratch_clean(_ans(article="11 42 7 953 129"), "11427953129", "BMW")


def test_clean_foreign_brand_fitment_dropped(capsys):
    got = ai._scratch_clean(
        _ans(fitment=["Audi A4 B8 2007-2015", "BMW 3 F30 2011-2019"]),
        "11427953129", "BMW")
    fit = got[0]
    assert fit == ["BMW 3 F30 2011-2019"]     # чужа марка не заїжджає в картку
    assert "Audi" in capsys.readouterr().out


def test_clean_all_fitment_foreign_but_chars_kept():
    got = ai._scratch_clean(_ans(fitment=["Audi A4 B8"]), "11427953129", "BMW")
    assert got is not None and got[0] == []


def test_clean_char_outside_whitelist_dropped():
    got = ai._scratch_clean(_ans(chars=[
        {"name": "Гарантія", "unit": "", "value": "12 міс"},
        {"name": "Матеріал", "unit": "", "value": "папір"},
    ]), "11427953129", "BMW")
    assert got[1] == [("Матеріал", "", "папір")]


def test_clean_long_value_dropped():
    # Характеристика — не речення: Prom пише їх позиційно.
    got = ai._scratch_clean(_ans(chars=[
        {"name": "Матеріал", "unit": "", "value": "х" * 80}]), "11427953129", "BMW")
    assert got[1] == []


def test_clean_empty_answer_is_none():
    assert ai._scratch_clean(_ans(type="", category="", fitment=[], chars=[]),
                             "11427953129", "BMW") is None


def test_clean_junk_is_none():
    assert ai._scratch_clean(None, "1", "BMW") is None
    assert ai._scratch_clean("не JSON", "1", "BMW") is None


# --------------------------------------------------- запит без комерції
def test_scratch_facts_payload_has_no_money(monkeypatch):
    seen = {}

    def _fake(system, payload, **kw):
        seen["system"] = system
        seen["payload"] = payload
        return json.dumps(_ans(), ensure_ascii=False)

    monkeypatch.setattr(ai, "_ai_call", _fake)
    got = ai.scratch_facts("11427953129", "BMW", "FILTER OIL BMW")
    assert got is not None
    low = seen["payload"].lower()
    for word in ("ціна", "price", "собівар", "cost", "дилер", "знижк", "грн"):
        assert word not in low, f"у запиті не має бути «{word}»"
    assert json.loads(seen["payload"])["article"] == "11427953129"


def test_scratch_facts_memoised(monkeypatch):
    calls = []

    def _fake(system, payload, **kw):
        calls.append(payload)
        return json.dumps(_ans(), ensure_ascii=False)

    monkeypatch.setattr(ai, "_ai_call", _fake)
    ai.scratch_facts("11427953129", "BMW")
    ai.scratch_facts("11427953129", "BMW")
    assert len(calls) == 1


def test_scratch_facts_off_without_ai():
    assert ai.scratch_facts("11427953129", "BMW", use_ai=False) is None
    assert ai.scratch_facts("", "BMW") is None


# -------------------------------------------------- дописування в product
def test_scratch_product_fills_empty(monkeypatch):
    monkeypatch.setattr(cb, "scratch_facts",
                        lambda *a, **k: (["BMW 3 F30 2011-2019"],
                                         [("Матеріал", "", "папір")],
                                         "фільтр масляний", "Фільтри"))
    p = {"article": "11427953129", "brand": "BMW", "name": "",
         "cars": [], "details": {}, "nodes": ""}
    assert cb.scratch_product(p, {"scratch": True}) is True
    assert p["cars"] == ["BMW 3 F30 2011-2019"]
    assert p["details"]["Матеріал"] == "папір"
    assert p["nodes"] == "Фільтри"
    assert p["name"] == "фільтр масляний BMW"


def test_scratch_product_does_not_overwrite_supplier(monkeypatch):
    # Дані постачальника СИЛЬНІШІ за модель.
    monkeypatch.setattr(cb, "scratch_facts",
                        lambda *a, **k: (["BMW 3 F30 2011-2019"],
                                         [("Матеріал", "", "папір")],
                                         "фільтр масляний", "Фільтри"))
    p = {"article": "11427953129", "brand": "BMW", "name": "Фільтр оливи BMW",
         "cars": ["BMW 5 G30"], "details": {"Матеріал": "метал"}, "nodes": "Двигун"}
    cb.scratch_product(p, {"scratch": True})
    assert p["cars"] == ["BMW 5 G30"]
    assert p["details"]["Матеріал"] == "метал"
    assert p["nodes"] == "Двигун"
    assert p["name"] == "Фільтр оливи BMW"


def test_scratch_product_never_touches_money(monkeypatch):
    monkeypatch.setattr(cb, "scratch_facts",
                        lambda *a, **k: (["BMW 3 F30"], [], "фільтр", "Фільтри"))
    p = {"article": "1", "brand": "BMW", "name": "", "cars": [], "details": {},
         "nodes": "", "price": 111.0}
    cb.scratch_product(p, {"scratch": True})
    assert p["price"] == 111.0
    assert "cost" not in p and "Наявність" not in p


def test_scratch_product_no_facts(monkeypatch, capsys):
    monkeypatch.setattr(cb, "scratch_facts", lambda *a, **k: None)
    p = {"article": "11427953129", "brand": "BMW", "name": "", "cars": [],
         "details": {}, "nodes": ""}
    assert cb.scratch_product(p, {"scratch": True}) is False
    assert p["cars"] == [] and p["details"] == {}
    assert "не дав фактів" in capsys.readouterr().out


# ------------------------------------------------------------ довідник правил
def test_scratch_rules_are_written_down():
    from adding import rules
    codes = {r.code for r in rules.SCRATCH_RULES}
    assert {"scratch_only_asked", "scratch_no_oem", "scratch_own_brand",
            "scratch_staging"} <= codes
    for r in rules.SCRATCH_RULES:
        assert r.src in rules.SOURCES and r.hard


def test_scratch_rules_stay_out_of_audit_prompt():
    # Аудит судить ГОТОВУ картку і не знає, звідки взявся її зміст. Зайвий
    # рядок системного промпта — це витрачена квота на КОЖНІЙ картці.
    from adding import rules
    sysm = rules.audit_system()
    for r in rules.SCRATCH_RULES:
        assert r.text not in sysm


def test_kanon_has_scratch_section():
    from adding import rules
    md = rules.rulebook_md()
    assert "## Картка з нуля" in md
    assert "Фото вручну (посилання)" in md
    for r in rules.SCRATCH_RULES:
        assert r.code in md


def test_build_fields_scratch_off_by_default(monkeypatch):
    # Без прапорця scratch звертань до профілю «з нуля» бути не може.
    called = []
    monkeypatch.setattr(cb, "scratch_facts",
                        lambda *a, **k: called.append(1) or None)
    cb.build_fields({"article": "11427953129", "brand": "BMW",
                     "name": "Фільтр", "cars": [], "details": {}},
                    {"article": "11427953129", "matched_bm": True,
                     "scratch": False, "cost": 100, "source": "BM Parts",
                     "presence": "available", "qty": 5, "days": 1},
                    use_ai=False)
    assert called == []
