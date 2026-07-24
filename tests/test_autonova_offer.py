# -*- coding: utf-8 -*-
from repricing.sources.autonova_web import pick_offer


def test_shortest_delivery_wins_over_cheaper():
    # Дешева-але-повільна НЕ виграє; беремо найшвидшу навіть якщо дорожча.
    offers = [
        {"price": 5000, "qty": 3, "days": 7, "own": False},   # дешева, але 7 днів
        {"price": 6200, "qty": 1, "days": 1, "own": True},    # дорожча, але 1 день
        {"price": 5800, "qty": 0, "days": 3, "own": False},
    ]
    best = pick_offer(offers)
    assert best["price"] == 6200 and best["days"] == 1


def test_tie_on_days_picks_cheapest():
    # Кілька з однаковим найкоротшим терміном -> найдешевша з них.
    offers = [
        {"price": 6200, "qty": 1, "days": 2, "own": True},
        {"price": 5900, "qty": 2, "days": 2, "own": False},   # той самий термін, дешевша
        {"price": 5000, "qty": 3, "days": 9, "own": False},   # дешевша, але повільна
    ]
    best = pick_offer(offers)
    assert best["price"] == 5900 and best["days"] == 2


def test_empty():
    assert pick_offer([]) is None
