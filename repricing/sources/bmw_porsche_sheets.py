# -*- coding: utf-8 -*-
"""Джерело 1–2: прайси BMW і Porsche з Google-таблиць постачальника."""
import re

from common.normalize import num, _norm
from repricing.sources.base import keep_best


def _tab_days(nt):
    """Термін постачання (днів) з назви вкладки прайсу: '2-3'->3, '15 днів'->15,
    інакше дефолт 15. Для наявних вкладок термін не потрібен (0)."""
    if "2-3" in nt or "2–3" in nt or "23дн" in nt:
        return 3
    days = [int(x) for x in re.findall(r"\d+", nt) if 0 < int(x) <= 60]
    return max(days) if days else 15


def read_all_tabs(gc, sid, brand, best, instock, force=None):
    """Читає ВСІ вкладки книги-прайсу. Наявність визначає за назвою вкладки
    («наяв» / «чекати 2-3» / «під замовлення»), або force для всієї книги."""
    try:
        ss = gc.open_by_key(sid)
    except Exception as e:
        print(f"[sheet] {brand}: OPEN FAIL {str(e)[:80] or 'нема доступу'}")
        return
    for ws in ss.worksheets():
        title = ws.title
        nt = _norm(title)
        if force:
            presence = force
        elif "наяв" in nt:
            presence = "available"
        elif any(k in nt for k in ["чека", "2-3", "2–3", "23дн", "замов", "15дн", "15днів", "підзам"]):
            presence = "order"
        else:
            presence = "available"
        days = 0 if presence == "available" else _tab_days(nt)
        try:
            rows = ws.get_all_values()
        except Exception as e:
            print(f"[sheet] {brand}/{title}: READ FAIL {str(e)[:60]}")
            continue
        n = 0
        for r in rows:
            if len(r) < 3:
                continue
            art = (r[0] or "").strip()
            if not art:
                continue
            cost = num(r[3]) if len(r) >= 4 else 0
            if cost > 0:
                qty = num(r[2])
            else:
                cost = num(r[2])
                qty = 0
            if cost <= 0:
                continue
            keep_best(best, art, {"name": r[1], "cost": cost, "qty": qty, "days": days,
                                  "presence": presence, "brand": brand}, instock)
            n += 1
        print(f"[sheet] {brand}/{title}: {n} поз. ({presence})")
