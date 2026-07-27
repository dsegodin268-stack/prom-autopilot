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


def test_recheck_returns_upgraded_and_fires_callback(monkeypatch):
    # Апгрейджені коди повертаються списком і on_upgrade викликається одразу
    # (для інкрементального запису в Export).
    monkeypatch.setattr(aw, "autonova_web_authorized", lambda c: True)
    monkeypatch.setattr(aw, "_resolve_autonova", lambda code, cookie, brands: {
        "name": "", "cost": 130, "qty": 2, "days": 1, "presence": "available", "brand": "Авто-web"})
    best = {"X1": {"cost": 100, "qty": 0, "days": 15, "presence": "order", "brand": "BMW"}}
    instock = {}
    written = []
    up = aw.recheck_autonova_faster(["X1"], best, instock, "cookie", on_upgrade=written.append)
    assert up == ["X1"]
    assert written == ["X1"]          # колбек спрацював саме для прискореного коду


def test_recheck_survives_resolver_exception(monkeypatch):
    # Одна погана позиція (виняток у резолвері) не має валити всю крос-перевірку.
    def boom(code, cookie, brands):
        if code == "BAD":
            raise ValueError("api hiccup")
        return {"name": "", "cost": 130, "qty": 1, "days": 1, "presence": "available", "brand": "Авто-web"}
    monkeypatch.setattr(aw, "autonova_web_authorized", lambda c: True)
    monkeypatch.setattr(aw, "_resolve_autonova", boom)
    best = {"BAD": {"cost": 1, "qty": 0, "days": 15, "presence": "order", "brand": "BMW"},
            "OK": {"cost": 1, "qty": 0, "days": 15, "presence": "order", "brand": "BMW"}}
    instock = {}
    up = aw.recheck_autonova_faster(["BAD", "OK"], best, instock, "cookie")
    assert up == ["OK"]               # BAD пропущено, OK прискорено
    assert best["OK"]["brand"] == "Авто-web"
