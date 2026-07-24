# -*- coding: utf-8 -*-
from repricing import guard


def test_anchor_floor_holds():
    anchor = {"X1": 1000.0}
    ok, status = guard.check("X1", 500, 900, anchor, has_competitor=False)
    assert not ok and "якоря" in status  # 500 < 60% від 1000


def test_anchor_floor_passes():
    anchor = {"X1": 1000.0}
    ok, _ = guard.check("X1", 650, 800, anchor, has_competitor=False)
    assert ok  # 650 >= 600 (якір) і падіння 800→650 = 18.75% < 25%


def test_drop_pct_holds():
    ok, status = guard.check("X2", 700, 1000, {}, has_competitor=False)
    assert not ok and "падіння" in status  # -30% > 25%


def test_drop_pct_passes():
    ok, _ = guard.check("X2", 800, 1000, {}, has_competitor=False)
    assert ok  # -20% <= 25%


def test_competitor_disables_guard():
    anchor = {"X3": 1000.0}
    ok, status = guard.check("X3", 400, 1000, anchor, has_competitor=True)
    assert ok and "конкурент" in status  # свідома ціна вимикає захист


def test_no_anchor_no_current():
    ok, _ = guard.check("X4", 123, 0, {}, has_competitor=False)
    assert ok
