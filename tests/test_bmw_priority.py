# -*- coding: utf-8 -*-
"""ПРІОРИТЕТ ПРАЙСУ BMW (власник, 29.07.2026) + чесні мітки добору за ключем
+ наявність BM Parts зі складських колонок /prices/list."""
import repricing.sources.autonova_web as aw
from repricing.sources.base import keep_best
from repricing.sources.bmw_pairs import pull_pairs_from_best


def _bmw(cost, lock, days, presence="order", qty=0):
    return {"cost": cost, "qty": qty, "days": days, "presence": presence,
            "brand": "BMW", "lock": lock}


def test_lock0_not_replaced_even_by_cheaper_available():
    # «наяв» BMW: ціна BMW перша — дешевша autonova її НЕ перебиває
    best = {"A": _bmw(100, 0, 0, "available", 3)}
    instock = {"A": 3}
    keep_best(best, "A", {"cost": 50, "qty": 9, "days": 0,
                          "presence": "available", "brand": "Авто"}, instock)
    assert best["A"]["brand"] == "BMW" and best["A"]["cost"] == 100
    assert instock["A"] == 3   # чужу наявність до BMW-позиції не домішуємо


def test_lock1_not_replaced():
    # «чекати 2-3д» BMW теж ніхто не перебиває
    best = {"A": _bmw(100, 1, 3)}
    instock = {}
    keep_best(best, "A", {"cost": 50, "qty": 9, "days": 0,
                          "presence": "available", "brand": "Авто"}, instock)
    assert best["A"]["brand"] == "BMW"
    assert "A" not in instock


def test_lock2_replaced_by_fast_source():
    # «під замовлення 15 дн» BMW віддаємо швидкому (в наявності = 0 днів)
    best = {"A": _bmw(100, 2, 15)}
    instock = {}
    keep_best(best, "A", {"cost": 150, "qty": 2, "days": 0,
                          "presence": "available", "brand": "Авто"}, instock)
    assert best["A"]["brand"] == "Авто"
    assert instock["A"] == 2


def test_lock2_kept_against_slow_source():
    # повільніше 5 днів — лишається ціна BMW, хай чужа й дешевша
    best = {"A": _bmw(100, 2, 15)}
    instock = {}
    keep_best(best, "A", {"cost": 50, "qty": 0, "days": 10,
                          "presence": "order", "brand": "Авто"}, instock)
    assert best["A"]["brand"] == "BMW"


def test_bmw_tab_priority_inside_book():
    # у межах прайсу BMW вища вкладка перемагає: «наяв» > «під замовлення»
    best = {"A": _bmw(90, 2, 15)}
    instock = {}
    keep_best(best, "A", _bmw(100, 0, 0, "available", 1), instock)
    assert best["A"]["lock"] == 0 and best["A"]["cost"] == 100


def test_plain_positions_keep_cheapest_rule():
    # без lock — старе правило «найдешевша перемагає» не змінилося
    best = {"A": {"cost": 100, "qty": 0, "days": 0, "presence": "order", "brand": "X"}}
    instock = {}
    keep_best(best, "A", {"cost": 90, "qty": 1, "days": 0,
                          "presence": "available", "brand": "Y"}, instock)
    assert best["A"]["brand"] == "Y" and best["A"]["cost"] == 90


def test_recheck_skips_bmw_instock_tabs(monkeypatch):
    # «чекати 2-3д» BMW: autonova навіть не питаємо
    calls = []

    def spy(code, cookie, brands):
        calls.append(code)
        return {"name": "", "cost": 130, "qty": 2, "days": 1,
                "presence": "available", "brand": "Авто-web"}
    monkeypatch.setattr(aw, "autonova_web_authorized", lambda c: True)
    monkeypatch.setattr(aw, "_resolve_autonova", spy)
    best = {"X1": _bmw(100, 1, 3)}
    up = aw.recheck_autonova_faster(["X1"], best, {}, "cookie")
    assert up == [] and calls == []
    assert best["X1"]["brand"] == "BMW"


def test_recheck_lock2_requires_5_days(monkeypatch):
    # autonova 7 дн проти BMW 15 дн: швидше, але >5 -> ціна BMW лишається
    monkeypatch.setattr(aw, "autonova_web_authorized", lambda c: True)
    monkeypatch.setattr(aw, "_resolve_autonova", lambda code, cookie, brands: {
        "name": "", "cost": 130, "qty": 0, "days": 7, "presence": "order", "brand": "Авто-web"})
    best = {"X1": _bmw(100, 2, 15)}
    up = aw.recheck_autonova_faster(["X1"], best, {}, "cookie")
    assert up == [] and best["X1"]["brand"] == "BMW"


def test_recheck_lock2_takes_fast_autonova(monkeypatch):
    monkeypatch.setattr(aw, "autonova_web_authorized", lambda c: True)
    monkeypatch.setattr(aw, "_resolve_autonova", lambda code, cookie, brands: {
        "name": "", "cost": 130, "qty": 2, "days": 1, "presence": "available", "brand": "Авто-web"})
    best = {"X1": _bmw(100, 2, 15)}
    instock = {}
    up = aw.recheck_autonova_faster(["X1"], best, instock, "cookie")
    assert up == ["X1"] and best["X1"]["brand"] == "Авто-web"
    assert instock["X1"] == 2


def test_pairs_honest_donor_label():
    # донор — АвтоНова: у «Джерело» більше не пишеться «BMW»
    best = {"8W7061221B 041": {"cost": 200, "qty": 3, "days": 0,
                               "presence": "available", "brand": "Авто"}}
    instock = {}
    pull_pairs_from_best(["8W7061221B041"], best, instock)
    assert best["8W7061221B041"]["brand"] == "Авто (ключ)"


def test_pairs_no_double_for_foreign_dash_code():
    # чужий код з рискою (19-045771) НІКОЛИ не отримує подвоєну ціну
    best = {"19": {"cost": 100, "qty": 1, "days": 0, "presence": "available", "brand": "X"}}
    instock = {}
    pull_pairs_from_best(["19-045771"], best, instock)
    assert "19-045771" not in best


def test_pairs_double_only_for_true_bmw_pair():
    best = {"51117303107": {"cost": 100, "qty": 2, "days": 0,
                            "presence": "available", "brand": "BMW"}}
    instock = {}
    pull_pairs_from_best(["51117303107-108"], best, instock)
    assert best["51117303107-108"]["cost"] == 200
    assert best["51117303107-108"]["brand"] == "BMW-пара(×2)"


def test_bmparts_qty_from_warehouse_columns(monkeypatch):
    # /prices/list: наявність = сума складських колонок («-» = 0)
    import repricing.sources.bmparts_prices as bp
    import common.bmparts_client as bc

    csv_text = ("ІД,Артикул,Бренд,Назва,Ціна ГРН,Київ ДАГ,Харків ДАГ\n"
                "UUID,Article,Brand,Name,Price,QTY:DAG:1,QTY:DAG:2\n"
                '"u1","55749SET","X","Колектор","6934.90","-","2"\n'
                '"u2","57400SET","X","Комплект","1808.82","-","-"\n')

    class _R:
        status_code = 200
        text = csv_text

    class _S:
        def post(self, *a, **k):
            return _R()

    class _BM:
        def __init__(self, token=None):
            self.s = _S()

        def warehouses(self):
            return [{"uuid": "w1"}]

    monkeypatch.setenv("BMPARTS_TOKEN", "t")
    monkeypatch.setattr(bc, "BMParts", _BM)
    m = bp._bmparts_list_map()
    assert m["55749SET"]["qty"] == 2
    assert m["55749SET"]["presence"] == "available"
    assert m["57400SET"]["presence"] == "order"
