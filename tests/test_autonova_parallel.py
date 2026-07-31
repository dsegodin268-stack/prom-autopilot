# -*- coding: utf-8 -*-
"""Прискорення нічного прогону (31.07): паралельні запити + пам'ять марок.

Головне, що тут доводиться: ДАНІ НЕ ЗМІНИЛИСЬ. Паралель дає той самий результат,
що й стара черга; правила ПРІОРИТЕТУ ПРАЙСУ BMW (lock 0/1/2) цілі; ціни й наявність
не кешуються між запитами; сумарний темп запитів лишається обмеженим."""
import threading
import time

import repricing.sources.autonova_web as aw


def _reset(monkeypatch, workers, interval="0"):
    aw._brand_reset()
    aw._RATE_NEXT[0] = 0.0
    monkeypatch.setenv("AUTONOVA_WORKERS", str(workers))
    monkeypatch.setenv("AUTONOVA_MIN_INTERVAL", str(interval))


def _item(cost, days, presence="order", qty=0):
    return {"name": "", "cost": cost, "qty": qty, "days": days,
            "presence": presence, "brand": "Авто-web"}


# --- 1. Паралель = черга: той самий результат ---------------------------------

def _run_recheck(monkeypatch, workers, codes, best_src, resolve):
    _reset(monkeypatch, workers)
    monkeypatch.setattr(aw, "autonova_web_authorized", lambda c: True)
    monkeypatch.setattr(aw, "_resolve_autonova", resolve)
    best = {k: dict(v) for k, v in best_src.items()}
    instock, written = {}, []
    up = aw.recheck_autonova_faster(codes, best, instock, "cookie",
                                    on_upgrade=written.append)
    return best, instock, up, written


def test_parallel_gives_same_result_as_queue(monkeypatch):
    codes = [f"X{i}" for i in range(40)]
    best_src = {c: {"cost": 1000, "days": 10, "brand": "BMParts"} for c in codes}

    def resolve(code, cookie, brands):
        n = int(str(code)[1:])
        if n % 3 == 0:
            return None                       # немає на autonova
        return _item(500 + n, days=1 if n % 2 else 9,
                     presence="available" if n % 2 else "order",
                     qty=2 if n % 2 else 0)

    seq = _run_recheck(monkeypatch, 1, codes, best_src, resolve)
    par = _run_recheck(monkeypatch, 8, codes, best_src, resolve)
    assert seq[0] == par[0]      # best
    assert seq[1] == par[1]      # instock
    assert seq[2] == par[2]      # список прискорених — і склад, і ПОРЯДОК
    assert seq[3] == par[3]      # порядок записів у таблицю


def test_pull_parallel_same_as_queue(monkeypatch):
    codes = [f"Y{i}" for i in range(30)]

    def resolve(code, cookie, brands):
        n = int(str(code)[1:])
        if n % 4 == 0:
            return None
        return _item(300 + n, days=1, presence="available", qty=n + 1)

    def run(workers):
        _reset(monkeypatch, workers)
        monkeypatch.setattr(aw, "autonova_web_authorized", lambda c: True)
        monkeypatch.setattr(aw, "_resolve_autonova", resolve)
        best, instock = {}, {}
        aw.pull_autonova_web(codes, best, instock, "cookie")
        return best, instock

    assert run(1) == run(8)


# --- 2. Правила BMW цілі -------------------------------------------------------

def test_lock01_still_never_asked_in_parallel(monkeypatch):
    asked = []
    lock_at = threading.Lock()

    def spy(code, cookie, brands):
        with lock_at:
            asked.append(str(code))
        return _item(100, days=0, presence="available", qty=5)

    best = {"A0": {"cost": 900, "days": 9, "lock": 0},
            "A1": {"cost": 900, "days": 9, "lock": 1},
            "A2": {"cost": 900, "days": 9, "lock": 2},
            "A3": {"cost": 900, "days": 9}}
    _reset(monkeypatch, 8)
    monkeypatch.setattr(aw, "autonova_web_authorized", lambda c: True)
    monkeypatch.setattr(aw, "_resolve_autonova", spy)
    up = aw.recheck_autonova_faster(["A0", "A1", "A2", "A3"], best, {}, "cookie")
    assert sorted(asked) == ["A2", "A3"]      # lock 0/1 — autonova не питали взагалі
    assert best["A0"]["cost"] == 900 and best["A1"]["cost"] == 900
    assert sorted(up) == ["A2", "A3"]


def test_lock2_takes_only_fast_autonova_in_parallel(monkeypatch):
    # lock=2 (BMW «під замовлення») віддається лише джерелу з терміном <=5 днів
    best = {"S": {"cost": 900, "days": 9, "lock": 2},   # autonova 3 дн -> міняємо
            "L": {"cost": 900, "days": 9, "lock": 2}}   # autonova 7 дн -> лишаємо BMW
    _reset(monkeypatch, 8)
    monkeypatch.setattr(aw, "autonova_web_authorized", lambda c: True)
    monkeypatch.setattr(aw, "_resolve_autonova",
                        lambda code, cookie, brands: _item(500, days=3 if code == "S" else 7))
    up = aw.recheck_autonova_faster(["S", "L"], best, {}, "cookie")
    assert up == ["S"]
    assert best["S"]["cost"] == 500
    assert best["L"]["cost"] == 900 and best["L"]["days"] == 9


# --- 3. Темп запитів лишається обмеженим --------------------------------------

def test_rate_gate_bounds_total_request_rate(monkeypatch):
    _reset(monkeypatch, 8, interval="0.02")
    aw._RATE_NEXT[0] = time.monotonic()
    n = 20
    t0 = time.monotonic()
    ths = [threading.Thread(target=aw._rate_gate) for _ in range(n)]
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    spent = time.monotonic() - t0
    # 20 запитів по 0.02 c сумарно з 8 потоків не можуть пройти швидше ніж за ~0.38 c
    assert spent >= (n - 1) * 0.02 * 0.9


def test_rate_gate_off_when_interval_zero(monkeypatch):
    _reset(monkeypatch, 8, interval="0")
    t0 = time.monotonic()
    for _ in range(50):
        aw._rate_gate()
    assert time.monotonic() - t0 < 0.5


def test_workers_env_is_clamped(monkeypatch):
    monkeypatch.setenv("AUTONOVA_WORKERS", "0")
    assert aw._autonova_workers() == 1
    monkeypatch.setenv("AUTONOVA_WORKERS", "999")
    assert aw._autonova_workers() == 16
    monkeypatch.setenv("AUTONOVA_WORKERS", "дурня")
    assert aw._autonova_workers() == 6
    monkeypatch.delenv("AUTONOVA_WORKERS", raising=False)
    assert aw._autonova_workers() == 6


# --- 4. Пам'ять марок: тільки «де шукати», не «скільки коштує» ------------------

def test_brand_memo_cuts_lookups_but_not_prices(monkeypatch):
    """Код знаходиться лише під маркою 16 (остання в переліку). Перший раз —
    повний перебір; другий — одразу 16. Але ЦІНА щоразу тягнеться свіжа."""
    aw._brand_reset()
    monkeypatch.setenv("AUTONOVA_MIN_INTERVAL", "0")
    calls = []
    price = [1000]

    def fake_best(code, brand_id, cookie):
        calls.append((code, brand_id))
        if brand_id != 16:
            return None
        return {"cost": price[0], "qty": 0, "presence": "order", "days": 8}

    monkeypatch.setattr(aw, "_autonova_code_best", fake_best)
    brands = [1, 72, 56, 59, 81, 16]

    r1 = aw._resolve_autonova("11427508969", "cookie", brands)
    first = len(calls)
    assert r1["cost"] == 1000 and first == len(brands)

    price[0] = 1234          # ціна на autonova змінилась
    calls.clear()
    r2 = aw._resolve_autonova("11427508969", "cookie", brands)
    assert len(calls) == 1 and calls[0][1] == 16      # марку згадали
    assert r2["cost"] == 1234                          # ціну НЕ згадали — питали заново


def test_brand_order_memo_then_guess_then_hits():
    aw._brand_reset()
    brands = [1, 72, 56, 59, 81, 16]
    # цифровий код -> підказка 72
    assert aw._brand_order("11427508969", brands)[0] == 72
    # після влучань 16 стає першою серед «решти»
    aw._brand_hit("OTHER1", 16)
    aw._brand_hit("OTHER2", 16)
    order = aw._brand_order("11427508969", brands)
    assert order[0] == 72 and order[1] == 16
    # для свого коду пам'ять важливіша за підказку
    aw._brand_hit("11427508969", 59)
    assert aw._brand_order("11427508969", brands)[:2] == [59, 72]
    assert sorted(aw._brand_order("11427508969", brands)) == sorted(brands)
    aw._brand_reset()


def test_brand_order_keeps_all_brands_once():
    aw._brand_reset()
    brands = [1, 72, 56]
    order = aw._brand_order("A1678992200", brands)   # підказка 56
    assert order[0] == 56
    assert len(order) == len(set(order)) == len(brands)
    aw._brand_reset()


# --- 5. Стійкість і порядок ----------------------------------------------------

def test_one_bad_code_does_not_kill_the_rest_in_parallel(monkeypatch):
    def boom(code, cookie, brands):
        if code == "BAD":
            raise RuntimeError("autonova впала")
        return _item(500, days=1, presence="available", qty=3)

    best = {"BAD": {"cost": 900, "days": 9}, "OK": {"cost": 900, "days": 9}}
    _reset(monkeypatch, 8)
    monkeypatch.setattr(aw, "autonova_web_authorized", lambda c: True)
    monkeypatch.setattr(aw, "_resolve_autonova", boom)
    up = aw.recheck_autonova_faster(["BAD", "OK"], best, {}, "cookie")
    assert up == ["OK"] and best["BAD"]["cost"] == 900


def test_resolve_many_keeps_input_order(monkeypatch):
    _reset(monkeypatch, 8)
    rows = [(f"K{i}", f"C{i}") for i in range(50)]

    def resolve(code, cookie, brands):
        # навмисно різна тривалість, щоб потоки завершувались не по порядку
        time.sleep(0.002 * (int(str(code)[1:]) % 5))
        return _item(int(str(code)[1:]), days=1)

    monkeypatch.setattr(aw, "_resolve_autonova", resolve)
    out = list(aw._resolve_many(rows, "cookie", [1], "t"))
    assert [r[0] for r, _ in out] == [r[0] for r in rows]
    assert [it["cost"] for _, it in out] == list(range(50))


def test_duplicate_codes_asked_once(monkeypatch):
    asked = []
    lock_at = threading.Lock()

    def spy(code, cookie, brands):
        with lock_at:
            asked.append(code)
        return None

    _reset(monkeypatch, 4)
    monkeypatch.setattr(aw, "autonova_web_authorized", lambda c: True)
    monkeypatch.setattr(aw, "_resolve_autonova", spy)
    best = {"D": {"cost": 900, "days": 9}}
    aw.recheck_autonova_faster(["D", "d", "D "], best, {}, "cookie")
    assert len(asked) == 1


def test_recheck_limit_still_applies(monkeypatch):
    asked = []
    lock_at = threading.Lock()

    def spy(code, cookie, brands):
        with lock_at:
            asked.append(code)
        return None

    _reset(monkeypatch, 8)
    monkeypatch.setenv("AUTONOVA_RECHECK_LIMIT", "5")
    monkeypatch.setattr(aw, "autonova_web_authorized", lambda c: True)
    monkeypatch.setattr(aw, "_resolve_autonova", spy)
    codes = [f"Z{i}" for i in range(30)]
    best = {c: {"cost": 900, "days": 9} for c in codes}
    aw.recheck_autonova_faster(codes, best, {}, "cookie")
    assert len(asked) == 5


def test_no_price_cache_between_passes(monkeypatch):
    """Той самий код у двох проходах -> autonova питається ЗАНОВО, ціна свіжа."""
    aw._brand_reset()
    monkeypatch.setenv("AUTONOVA_MIN_INTERVAL", "0")
    seen = []
    price = [700]

    def fake_best(code, brand_id, cookie):
        seen.append(brand_id)
        return {"cost": price[0], "qty": 1, "presence": "available", "days": 0}

    monkeypatch.setattr(aw, "_autonova_code_best", fake_best)
    a = aw._resolve_autonova("11427508969", "cookie", [72])
    price[0] = 850
    b = aw._resolve_autonova("11427508969", "cookie", [72])
    assert a["cost"] == 700 and b["cost"] == 850
    assert len(seen) == 2
    aw._brand_reset()
