# -*- coding: utf-8 -*-
"""Якірний захист цін — УВІМКНЕНО 2026-07-24 (раніше код існував у main.py,
але ніколи не викликався — рішення власника №5 фактично не діяло).

Правила (діють лише коли НЕМАЄ конкурента/override — свідома ціна їх вимикає):
  1) нова ціна < ANCHOR_FLOOR (60%) від якоря 30.06 -> УТРИМАТИ (не писати);
  2) зниження діючої ціни > MAX_DROP_PCT (25%)      -> УТРИМАТИ (не писати).
Утримані позиції потрапляють у Звіт_Ціни зі статусом «утримано …»."""
import csv
import os

from common.normalize import num

ANCHOR_FLOOR = num(os.environ.get("ANCHOR_FLOOR") or 60) / 100.0
MAX_DROP_PCT = num(os.environ.get("MAX_DROP_PCT") or 25) / 100.0

_DEF_PATHS = (
    os.path.join(os.path.dirname(__file__), "data", "anchor_prices.csv"),
    "anchor_prices.csv",  # старий шлях у корені — на час міграції
)


def load_anchor(path=None):
    """article(UPPER) -> anchor_price. CSV: article,anchor_price."""
    paths = [p for p in [path or os.environ.get("ANCHOR_CSV")] if p] or list(_DEF_PATHS)
    m = {}
    for p in paths:
        try:
            with open(p, encoding="utf-8") as f:
                rd = csv.reader(f)
                next(rd, None)
                for row in rd:
                    if len(row) >= 2:
                        a = str(row[0]).strip().upper()
                        pr = num(row[1])
                        if a and pr > 0:
                            m[a] = pr
            print(f"[anchor] завантажено {len(m)} якірних цін із {p}")
            return m
        except FileNotFoundError:
            continue
        except Exception as e:
            print("[anchor]", str(e)[:80])
            return m
    print(f"[anchor] файл якоря не знайдено ({', '.join(paths)}) — якірний захист вимкнено")
    return m


def check(code, new_price, cur_price, anchor, has_competitor):
    """-> (можна_писати: bool, статус: str)."""
    if has_competitor:
        return True, "оновлено (конкурент/override)"
    a = anchor.get(str(code).strip().upper())
    if a and num(new_price) < a * ANCHOR_FLOOR:
        return False, f"утримано (нижче {int(ANCHOR_FLOOR*100)}% якоря {a:.0f})"
    cur = num(cur_price)
    if cur > 0 and num(new_price) < cur * (1 - MAX_DROP_PCT):
        return False, f"утримано (падіння >{int(MAX_DROP_PCT*100)}%)"
    return True, "оновлено"
