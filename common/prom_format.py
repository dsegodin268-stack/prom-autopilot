# -*- coding: utf-8 -*-
"""Розкладка колонок характеристик у форматі імпорту Prom.ua.

НАВІЩО ОКРЕМИЙ ФАЙЛ. У шапці Prom характеристики йдуть блоками, що повторюються:
    Назва_Характеристики | Одиниця_виміру_Характеристики | Значення_Характеристики
Тобто ТРІЙКА. Але подекуди (старі шаблони, деякі вивантаження постачальників)
одиниці немає і блок — ПАРА: Назва_Характеристики | Значення_Характеристики.

Раніше код розходився: adding/run.py писав у трійки (i, i+1, i+2), а
adding/review.py читав пари (i, i+1) — і через це в «Огляд_Додавання» у колонку
«Характеристики» потрапляла ОДИНИЦЯ замість значення (а оскільки одиниця часто
порожня, характеристики просто зникали). Тепер розкладка визначається ОДИН раз
за фактичною шапкою, і обидві сторони беруть її звідси.
"""
import re

_NAME = "назва_характеристики"
_UNIT = "одиниця"
_VAL = "значення_характеристики"


def _k(s):
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def char_columns(head):
    """Шапка -> [(i_назва, i_одиниця|None, i_значення)] у порядку появи.

    Визначає пару/трійку за сусідніми заголовками, а не за жорстким кроком:
    якщо одразу після «Назва_Характеристики» стоїть колонка одиниці — блок
    трійковий, інакше парний."""
    out = []
    n = len(head)
    for i, h in enumerate(head):
        if _k(h) != _NAME:
            continue
        j = i + 1
        if j < n and _UNIT in _k(head[j]):
            unit_i, val_i = j, j + 1
        else:
            unit_i, val_i = None, j
        if val_i < n and _k(head[val_i]).startswith("значення"):
            out.append((i, unit_i, val_i))
        elif val_i < n and unit_i is None:
            # шапка без слова «Значення» — вважаємо парою (сумісність зі старим шаблоном)
            out.append((i, None, val_i))
    return out


def read_chars(head, row, limit=0):
    """Рядок фіду -> [(назва, одиниця, значення)] лише для заповнених блоків."""
    g = lambda i: (row[i].strip() if (i is not None and i < len(row) and row[i]) else "")
    out = []
    for (ni, ui, vi) in char_columns(head):
        nm, val = g(ni), g(vi)
        if nm and val:
            out.append((nm, g(ui), val))
            if limit and len(out) >= limit:
                break
    return out


def write_chars(head, row, chars):
    """Кладе трійки (назва, одиниця, значення) у рядок за розкладкою шапки.
    Зайві характеристики, для яких у шапці немає блоків, мовчки відкидаються —
    Prom однаково прийме лише стільки, скільки колонок у фіді."""
    for (nm, unit, val), (ni, ui, vi) in zip(chars, char_columns(head)):
        row[ni] = nm
        if ui is not None:
            row[ui] = unit
        row[vi] = val
    return row
