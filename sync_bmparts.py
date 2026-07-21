#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ЗАДАЧА 1 — синхронізація наявності BM Parts в ОКРЕМУ книгу «BM Parts» (вкладка «BMParts»).
Раніше писало у вкладку головної Prom-таблиці; 2026-07-19 винесено, щоб не роздувати її.

ВАЖЛИВО: per-brand ендпоінт /prices/prom/{brand} повертає 0 по всіх марках
(підтверджено логами), тож використовуємо POST /prices/list — усі бренди
ОДНИМ запитом (перевірено: ~124k позицій у наявності). Прайсові ендпоінти
BM Parts віддають ЛИШЕ товари в наявності, тому вкладка = завжди актуальне
дзеркало: нове з'явилось -> додалось, зникло -> прибралось.

Пише в таблицю лише при LIVE=1 (інакше DRY-RUN).
Захист розміру: BMPARTS_TAB_LIMIT (0 = усі позиції; база велика — ~124k рядків)."""
import os, io, csv, json

ID_HUB="1pesHiOHDq2Y4FYQECakfhIJlq08bg5_Pkm9e2YEDoic"   # головна таблиця Prom (сюди БІЛЬШЕ не пишемо)
# 2026-07-19: дзеркало BM Parts винесено в ОКРЕМУ книгу «BM Parts», щоб не роздувати
# головну таблицю (було 125k рядків / 21.7 МБ у ній). Залежностей у Prom-таблиці немає:
# перевірено пошуком по всіх аркушах з формулами + Apps Script + кодом — ніхто її не читає.
ID_BMPARTS=os.environ.get("BMPARTS_SHEET_ID") or "1sGAA3KRHKm4oeNtL56MpAr3BaMWBmajZ7hGtDnb12Q0"
BM_TAB="BMParts"
LIVE=os.environ.get("LIVE")=="1"
ROW_LIMIT=int(float(os.environ.get("BMPARTS_TAB_LIMIT") or 0))  # 0 = усі позиції

def gclient():
    key=os.environ.get("GCP_SA_KEY")
    if not key or not key.strip().startswith("{"): return None
    import gspread
    return gspread.service_account_from_dict(json.loads(key))

def main():
    token=os.environ.get("BMPARTS_TOKEN")
    if not token: print("[fatal] нема BMPARTS_TOKEN — пропуск"); return
    gc=gclient()
    if not gc: print("[fatal] нема GCP_SA_KEY — без доступу до таблиці"); return
    try:
        from bmparts import BMParts
        bm=BMParts(token)
        whs=[w.get("uuid") for w in bm.warehouses() if w.get("uuid")]
    except Exception as e:
        print(f"[fatal] BM Parts init FAIL: {str(e)[:120]}"); return
    # Один запит на ВСЮ наявність (усі бренди). format=csv, code замість uuid.
    try:
        r=bm.s.post("https://api.bm.parts/prices/list",
                    json={"warehouses":whs,"format":"csv","products_type":"code"}, timeout=300)
        if r.status_code!=200:
            print(f"[fatal] /prices/list HTTP {r.status_code}"); return
        text=r.text
    except Exception as e:
        print(f"[fatal] /prices/list FAIL: {str(e)[:120]}"); return
    sample=text[:2000]; delim=";" if sample.count(";")>=sample.count(",") else ","
    rows=list(csv.reader(io.StringIO(text), delimiter=delim))
    if len(rows)<2:
        print("[bmparts] /prices/list порожній — вкладку НЕ чіпаю"); return
    header=rows[0]; data=rows[1:]
    total=len(data)
    if ROW_LIMIT and total>ROW_LIMIT:
        print(f"[bmparts] обрізаю до BMPARTS_TAB_LIMIT={ROW_LIMIT} (з {total})"); data=data[:ROW_LIMIT]
    W=len(header)
    grid=[header]+[(rr+[""]*(W-len(rr)))[:W] for rr in data]
    print(f"[bmparts] /prices/list: {total} позицій у наявності, {W} колонок. Заголовок: {header[:12]}")
    if not LIVE:
        print("[bmparts] DRY-RUN (LIVE≠1): у «BMParts» НЕ писав. Перші рядки:")
        for rr in grid[:4]: print("  ", " | ".join(str(x)[:16] for x in rr[:8]))
        return
    ss=gc.open_by_key(ID_BMPARTS)   # окрема книга «BM Parts» (не головна Prom-таблиця)
    ws=None
    for w in ss.worksheets():
        if w.title.strip().casefold()==BM_TAB.casefold(): ws=w; break
    if ws is None:
        ws=ss.add_worksheet(title=BM_TAB, rows=len(grid)+10, cols=W); print(f"[bmparts] створено вкладку «{BM_TAB}»")
    ws.resize(rows=len(grid)+10, cols=max(W,1))
    ws.clear()  # повне дзеркало: старе стирається, пишемо свіже
    B=5000
    for j in range(0, len(grid), B):
        ws.update(values=grid[j:j+B], range_name=f"A{j+1}")
        print(f"[bmparts] записано рядки {j+1}..{min(j+B,len(grid))}")
    print(f"[bmparts] ЗАПИСАНО в книгу «BM Parts» ({ID_BMPARTS}), вкладка «{BM_TAB}»: "
          f"{len(grid)-1} позицій (актуальне дзеркало наявності BM Parts).")

if __name__=="__main__": main()
