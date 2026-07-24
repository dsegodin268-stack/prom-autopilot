# -*- coding: utf-8 -*-
"""Читання каталогу і запис результатів у «Export Products Sheet» (бойова вкладка)."""
import re

from common.config import ID_HUB, EXPORT_TAB, C_CODE, C_QTY


def read_export(gc):
    """-> (ws, vals[2D з паддінгом], idx: код(UPPER)->індекс рядка)."""
    ss = gc.open_by_key(ID_HUB)
    keyf = lambda s: re.sub(r"[^a-z0-9]", "", str(s).lower())
    want = keyf(EXPORT_TAB)
    ws = None
    for w in ss.worksheets():
        if keyf(w.title) == want:
            ws = w
            break
    if ws is None:
        titles = [w.title for w in ss.worksheets()]
        print(f"[fatal] вкладку «{EXPORT_TAB}» не знайдено у хабі. Наявні вкладки: {titles}")
        raise SystemExit(2)
    print(f"[export] вкладка знайдена: «{ws.title}»")
    vals = ws.get_all_values()
    width = max(C_QTY + 1, max((len(r) for r in vals), default=0))
    for r in vals:
        if len(r) < width:
            r.extend([""] * (width - len(r)))
    idx = {}
    for i, r in enumerate(vals):
        if i == 0:
            continue
        code = str(r[C_CODE]).strip().upper()
        if code:
            idx[code] = i
    return ws, vals, idx


def write_updates(ws, updates, chunk=2000):
    """Точковий batch-запис (щоб не перевищити ліміт запиту)."""
    for j in range(0, len(updates), chunk):
        ws.batch_update(updates[j:j + chunk], value_input_option="RAW")
