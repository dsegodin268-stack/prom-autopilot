# -*- coding: utf-8 -*-
"""«Тільки оригінал»: _autonova_code_best бере ціну/наявність ЛИШЕ з оригінального
номера; аналог (інший артикул) ігнорується, навіть якщо він у наявності й дешевший."""
import repricing.sources.autonova_web as aw

CODE = "11427508969"


def _fetch(d):
    return lambda pid, cookie: d


def _offer(price, qty, days, article=None, **extra):
    o = {"price": {"current": price}, "quantity": qty, "delivery": {"days": days}}
    if article is not None:
        o["article"] = article
    o.update(extra)
    return o


def test_original_order_beats_instock_analog(monkeypatch):
    # Оригінал «під замовлення» (15 дн), аналог у наявності й дешевший -> беремо ОРИГІНАЛ.
    d = {"article": CODE, "offers": [
        _offer(1000, 0, 15, CODE),      # оригінал, замовлення
        _offer(400, 5, 1, "SM101"),     # аналог, в наявності
    ]}
    monkeypatch.setattr(aw, "_autonova_fetch", _fetch(d))
    r = aw._autonova_code_best(CODE, 72, "cookie")
    assert r is not None
    assert r["presence"] == "order"      # НЕ available (аналог не рахуємо)
    assert r["cost"] == 1000             # ціна оригіналу, не 400
    assert r["days"] == 15
    assert r["qty"] == 0


def test_only_analog_returns_none(monkeypatch):
    # На autonova лише аналог -> оригіналу нема -> None (не підміняємо).
    d = {"article": CODE, "offers": [_offer(400, 5, 1, "SM101")]}
    monkeypatch.setattr(aw, "_autonova_fetch", _fetch(d))
    assert aw._autonova_code_best(CODE, 72, "cookie") is None


def test_original_instock_available(monkeypatch):
    # Оригінал у наявності -> available з його ціною.
    d = {"offers": [_offer(1200, 3, 1, CODE)]}
    monkeypatch.setattr(aw, "_autonova_fetch", _fetch(d))
    r = aw._autonova_code_best(CODE, 72, "cookie")
    assert r["presence"] == "available" and r["cost"] == 1200 and r["qty"] == 3


def test_no_article_fields_treated_as_original(monkeypatch):
    # Немає жодних ознак артикулів -> ендпоінт і так по точному номеру -> оригінал.
    d = {"offers": [_offer(900, 0, 7)]}
    monkeypatch.setattr(aw, "_autonova_fetch", _fetch(d))
    r = aw._autonova_code_best(CODE, 72, "cookie")
    assert r["presence"] == "order" and r["cost"] == 900 and r["days"] == 7


def test_explicit_analog_flag_excluded(monkeypatch):
    # Явний прапорець isAnalog + інший номер -> відкинути; лишається оригінал.
    d = {"offers": [
        _offer(1500, 0, 20, CODE),
        _offer(500, 9, 1, "AN1", isAnalog=True),
    ]}
    monkeypatch.setattr(aw, "_autonova_fetch", _fetch(d))
    r = aw._autonova_code_best(CODE, 72, "cookie")
    assert r["cost"] == 1500 and r["presence"] == "order"
