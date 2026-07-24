# -*- coding: utf-8 -*-
"""Ручний шар: вкладки overrides (ручні ціни) і competitors (ціни конкурентів)."""
from common.config import ID_HUB
from common.normalize import num


def load_map(gc, tab):
    """Вкладка «артикул | ціна» -> {article(UPPER): price}."""
    m = {}
    try:
        for r in gc.open_by_key(ID_HUB).worksheet(tab).get_all_values()[1:]:
            if len(r) < 2:
                continue
            a = (r[0] or "").strip().upper()
            p = num(r[1])
            if a and p > 0:
                m[a] = p
    except Exception as e:
        print(f"[{tab}] {str(e)[:50]}")
    return m


def get_overrides(gc):
    return load_map(gc, "overrides")


def get_competitors(gc):
    return load_map(gc, "competitors")
