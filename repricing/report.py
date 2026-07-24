# -*- coding: utf-8 -*-
"""Вкладка «Звіт_Ціни» — журнал репрайсера по кожному товару каталогу."""
from common.config import ID_HUB, REPORT_TAB
from common.normalize import num
from common.pricing import price_with_competitor


def write_report(gc, catalog, best, instock, overrides, comps, guard_status=None, final_price_map=None):
    guard_status = guard_status or {}
    final_price_map = final_price_map or {}
    head = ["Артикул", "Назва (Prom)", "Ціна нова", "Зміна %", "Наявність", "Кількість",
            "Джерело", "Собівартість", "Статус"]
    rows = [head]
    for art, info in catalog.items():
        b = best.get(art)
        if b:
            newp = final_price_map.get(art)
            if newp is None:
                newp = overrides.get(art) or price_with_competitor(b["cost"], comps.get(art))
            cur = num(info.get("price"))
            chg = ("%+.0f%%" % (100 * (num(newp) - cur) / cur)) if cur > 0 else ""
            aq = instock.get(art, 0)
            if aq > 0:
                pres = "готово до відправки"  # в наявності = Prom «!»
            else:
                d = int(num(b.get("days"))) if b.get("days") is not None else 0
                pres = f"під замовлення {d if d > 0 else 15} дн"
            qty = aq if aq > 0 else ""
            rows.append([art, info.get("name", ""), newp, chg, pres, qty,
                         b.get("brand", ""), b.get("cost", ""), guard_status.get(art, "оновлено")])
        else:
            rows.append([art, info.get("name", ""), "", "", "", "", "", "", "Ручне коригування ціни"])
    ss = gc.open_by_key(ID_HUB)
    ws = None
    for w in ss.worksheets():
        if w.title.strip().casefold() == REPORT_TAB.casefold():
            ws = w
            break
    if ws is None:
        ws = ss.add_worksheet(title=REPORT_TAB, rows=max(len(rows) + 5, 100), cols=len(head))
    ws.resize(rows=max(len(rows) + 5, 10), cols=len(head))
    ws.clear()
    ws.update(values=rows, range_name="A1")
    print(f"[report] {REPORT_TAB}: {len(rows)-1} рядків записано")
