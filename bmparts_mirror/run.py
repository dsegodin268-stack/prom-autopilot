#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""МОДУЛЬ «ДЗЕРКАЛО BM PARTS» — точка входу (запуск: python -m bmparts_mirror.run).
Щодоби: POST /prices/list (усі бренди ОДНИМ запитом, ~125k позицій у наявності)
-> вкладка «BMParts» ОКРЕМОЇ книги «BM Parts» (не головна Prom-таблиця).
Прайсові ендпоінти віддають ЛИШЕ наявне, тому вкладка = актуальне дзеркало.
Пише лише при LIVE=1 (інакше DRY-RUN). Ліміт розміру: BMPARTS_TAB_LIMIT (0 = усі)."""
import csv
import io
import os

from common.bmparts_client import BMParts
from common.config import ID_BMPARTS_BOOK, BM_TAB, LIVE
from common.sheets import gclient

ROW_LIMIT = int(float(os.environ.get("BMPARTS_TAB_LIMIT") or 0))


def main():
    token = os.environ.get("BMPARTS_TOKEN")
    if not token:
        print("[fatal] нема BMPARTS_TOKEN — пропуск")
        return
    gc = gclient()
    if not gc:
        print("[fatal] нема GCP_SA_KEY — без доступу до таблиці")
        return
    try:
        bm = BMParts(token)
        whs = [w.get("uuid") for w in bm.warehouses() if w.get("uuid")]
    except Exception as e:
        print(f"[fatal] BM Parts init FAIL: {str(e)[:120]}")
        return
    try:
        r = bm.s.post("https://api.bm.parts/prices/list",
                      json={"warehouses": whs, "format": "csv", "products_type": "code"}, timeout=300)
        if r.status_code != 200:
            print(f"[fatal] /prices/list HTTP {r.status_code}")
            return
        text = r.text
    except Exception as e:
        print(f"[fatal] /prices/list FAIL: {str(e)[:120]}")
        return
    sample = text[:2000]
    delim = ";" if sample.count(";") >= sample.count(",") else ","
    rows = list(csv.reader(io.StringIO(text), delimiter=delim))
    if len(rows) < 2:
        print("[bmparts] /prices/list порожній — вкладку НЕ чіпаю")
        return
    header = rows[0]
    data = rows[1:]
    total = len(data)
    if ROW_LIMIT and total > ROW_LIMIT:
        print(f"[bmparts] обрізаю до BMPARTS_TAB_LIMIT={ROW_LIMIT} (з {total})")
        data = data[:ROW_LIMIT]
    W = len(header)
    grid = [header] + [(rr + [""] * (W - len(rr)))[:W] for rr in data]
    print(f"[bmparts] /prices/list: {total} позицій у наявності, {W} колонок. Заголовок: {header[:12]}")
    if not LIVE:
        print("[bmparts] DRY-RUN (LIVE≠1): у «BMParts» НЕ писав. Перші рядки:")
        for rr in grid[:4]:
            print("  ", " | ".join(str(x)[:16] for x in rr[:8]))
        return
    ss = gc.open_by_key(ID_BMPARTS_BOOK)
    ws = None
    for w in ss.worksheets():
        if w.title.strip().casefold() == BM_TAB.casefold():
            ws = w
            break
    if ws is None:
        ws = ss.add_worksheet(title=BM_TAB, rows=len(grid) + 10, cols=W)
        print(f"[bmparts] створено вкладку «{BM_TAB}»")
    ws.resize(rows=len(grid) + 10, cols=max(W, 1))
    ws.clear()
    B = 5000
    for j in range(0, len(grid), B):
        ws.update(values=grid[j:j + B], range_name=f"A{j+1}")
        print(f"[bmparts] записано рядки {j+1}..{min(j+B, len(grid))}")
    print(f"[bmparts] ЗАПИСАНО в книгу «BM Parts» ({ID_BMPARTS_BOOK}), вкладка «{BM_TAB}»: "
          f"{len(grid)-1} позицій (актуальне дзеркало наявності).")


if __name__ == "__main__":
    main()
