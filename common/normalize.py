# -*- coding: utf-8 -*-
"""Нормалізація чисел і артикулів — ЄДИНА копія для всіх модулів."""
import re


def num(x):
    try:
        return float(str(x).replace(",", ".").replace("\xa0", "").replace(" ", ""))
    except Exception:
        return 0.0


def _norm(x):
    return "".join(str(x).lower().split())


def _nkey(s):
    """Нормалізація коду: лише цифри/літери, UPPER. '20114-0050-99' -> '20114005099'."""
    return re.sub(r"[^0-9a-zA-Z]", "", str(s)).upper()


def _expand_code(code):
    """Розкладає дефісний код на ПОВНІ номери. Другий+ номер може бути скороченим
    суфіксом першого: '51117303107-108' -> ['51117303107','51117303108'];
    '51712150246-47' -> ['51712150246','51712150247']. Повний номер лишається як є."""
    raw = [p.strip() for p in str(code).split("-") if p.strip()]
    if not raw:
        return []
    base = raw[0]
    out = [base]
    for nx in raw[1:]:
        if len(nx) < len(base):
            nx = base[:len(base) - len(nx)] + nx  # дотягнути префіксом першого
        out.append(nx)
    return out
