# -*- coding: utf-8 -*-
import repricing.sources.autonova_web as aw


def test_recheck_replaces_when_autonova_faster(monkeypatch):
    # BMW-позиція «під замовлення 15 дн», а autonova має її в наявності -> замінити.
    monkeypatch.setattr(aw, "autonova_web_authorized", lambda c: True)
    monkeypatch.setattr(aw, "_resolve_autonova", lambda code, cookie, brands: {
        "name": "", "cost": 130, "qty": 2, "days": 1, "presence": "available", "brand": "Авто-web"})
    best = {"X1": {"cost": 100, "qty": 0, "days": 15, "presence": "order", "brand": "BMW"}}
    instock = {}
    aw.recheck_autonova_faster(["X1"], best, instock, "cookie")
    assert best["X1"]["brand"] == "Авто-web"
    assert best["X1"]["presence"] == "available"
    assert best["X1"]["cost"] == 130       # ціна з найшвидшого джерела
    assert instock["X1"] == 2


def test_recheck_keeps_when_autonova_slower(monkeypatch):
    # autonova має, але ПОВІЛЬНІШЕ (20 дн проти 15) -> лишаємо прайс BMW.
    monkeypatch.setattr(aw, "autonova_web_authorized", lambda c: True)
    monkeypatch.setattr(aw, "_resolve_autonova", lambda code, cookie, brands: {
        "name": "", "cost": 130, "qty": 0, "days": 20, "presence": "order", "brand": "Авто-web"})
    best = {"X1": {"cost": 100, "qty": 0, "days": 15, "presence": "order", "brand": "BMW"}}
    instock = {}
    aw.recheck_autonova_faster(["X1"], best, instock, "cookie")
    assert best["X1"]["brand"] == "BMW"
    assert "X1" not in instock


def test_recheck_skips_when_autonova_has_nothing(monkeypatch):
    monkeypatch.setattr(aw, "autonova_web_authorized", lambda c: True)
    monkeypatch.setattr(aw, "_resolve_autonova", lambda code, cookie, brands: None)
    best = {"X1": {"cost": 100, "qty": 0, "days": 15, "presence": "order", "brand": "BMW"}}
    instock = {}
    aw.recheck_autonova_faster(["X1"], best, instock, "cookie")
    assert best["X1"]["brand"] == "BMW"
