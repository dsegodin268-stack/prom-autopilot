# -*- coding: utf-8 -*-
"""Спільне для всіх джерел собівартості: правило «найдешевша перемагає»."""
from common.normalize import num


def keep_best(best, art, item, instock):
    """Кладе позицію в best (виграє найнижча собівартість) і оновлює instock."""
    k = str(art).strip().upper()
    if not k:
        return
    if item.get("presence") == "available" and num(item.get("qty")) > 0:
        instock[k] = max(instock.get(k, 0), int(num(item.get("qty"))))
    if k not in best or item["cost"] < best[k]["cost"]:
        item["article"] = k
        best[k] = item
