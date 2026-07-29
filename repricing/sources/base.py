# -*- coding: utf-8 -*-
"""Спільне для всіх джерел собівартості.

ПРІОРИТЕТ ПРАЙСУ BMW (власник, 29.07.2026): позиції з прайсу «Баварія Моторс»
несуть поле lock: 0=«наяв», 1=«чекати 2-3д», 2=«під замовлення 15 днів».
  * lock 0/1 не перебиває НІХТО — ціна BMW завжди перша для BMW-позицій;
  * lock 2 перебиває лише швидке джерело з терміном ≤5 днів (autonova в
    наявності або з коротким терміном); повільніше — лишається ціна BMW;
  * між позиціями БЕЗ lock діє старе правило «найдешевша перемагає».
"""
from common.normalize import num


def _may_replace(cur, new):
    """Чи має new замінити cur у best (правила — у шапці файлу)."""
    lc = cur.get("lock")
    ln = new.get("lock")
    if lc is None:
        if ln is not None:
            return True          # прайс BMW перебиває звичайне джерело
        return new["cost"] < cur["cost"]
    if ln is not None:           # обидва з прайсу BMW: вища вкладка перемагає
        return ln < lc or (ln == lc and new["cost"] < cur["cost"])
    if lc <= 1:
        return False             # «наяв»/«чекати 2-3д» — ціна BMW перша
    nd = int(num(new.get("days") or 0))
    return nd <= 5               # «під замовлення 15 дн» віддаємо лише швидкому


def keep_best(best, art, item, instock):
    """Кладе позицію в best за правилами пріоритету і оновлює instock."""
    k = str(art).strip().upper()
    if not k:
        return
    cur = best.get(k)
    if cur is not None and not _may_replace(cur, item):
        # позицію відкинуто; для звичайних (без lock) наявність, як і раніше,
        # рахуємо з усіх джерел — для BMW-позицій чужу наявність не домішуємо,
        # бо в Export пішла б ціна BMW з чужим терміном
        if cur.get("lock") is None and item.get("presence") == "available" \
                and num(item.get("qty")) > 0:
            instock[k] = max(instock.get(k, 0), int(num(item.get("qty"))))
        return
    if item.get("presence") == "available" and num(item.get("qty")) > 0:
        instock[k] = max(instock.get(k, 0), int(num(item.get("qty"))))
    item["article"] = k
    best[k] = item
