#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ЗАДАЧА 1 — синхронізація наявності BM Parts у вкладку «BMParts» (формат Prom).

Один прохід: тягне ВСЮ наявність BM Parts у форматі імпорту Prom.ua
(POST /prices/prom/{brand}) по всіх авто-марках каталогу (або зі змінної
BMPARTS_BRANDS) і ПОВНІСТЮ перезаписує вкладку «BMParts» у хабі.

Оскільки прайсові ендпоінти BM Parts віддають ЛИШЕ товари в наявності,
вкладка = завжди актуальне дзеркало: нова позиція з'явилась -> додалась,
зникла -> прибралась. Запуск щодоби (workflow sync_bmparts.yml).

Пише в таблицю лише при LIVE=1 (інакше DRY-RUN: рахує + друкує перші рядки).
Захист від велетенської таблиці: BMPARTS_TAB_LIMIT (0 = без ліміту)."""
import os, io, json, csv, time
from urllib.parse import quote

ID_HUB="1pesHiOHDq2Y4FYQECakfhIJlq08bg5_Pkm9e2YEDoic"
BM_TAB="BMParts"
LIVE=os.environ.get("LIVE")=="1"
MIN_INTERVAL=float(os.environ.get("BM_MIN_INTERVAL") or 0.8)   # ввічлива пауза між запитами марок
ROW_LIMIT=int(float(os.environ.get("BMPARTS_TAB_LIMIT") or 0)) # 0 = усі позиції

def num(x):
    try: return float(str(x).replace(",",".").replace("\xa0","").replace(" ",""))
    except: return 0.0

def gclient():
    key=os.environ.get("GCP_SA_KEY")
    if not key or not key.strip().startswith("{"): return None
    import gspread
    return gspread.service_account_from_dict(json.loads(key))

def car_brands(bm):
    env=os.environ.get("BMPARTS_BRANDS")
    if env: return [b.strip() for b in env.split(",") if b.strip()]
    try:
        r=bm.s.get("https://api.bm.parts/catalog/cars/brands/", timeout=60); r.raise_for_status()
        return [b.get("name") for b in (r.json().get("car_brands") or []) if b.get("name")]
    except Exception as e:
        print(f"[bmparts] список авто-марок FAIL: {str(e)[:100]} — fallback BMW"); return ["BMW"]

def prom_rows(bm, brand, whs):
    """POST /prices/prom/{brand} -> CSV у Prom-форматі. Повертає (header, rows)."""
    url=f"https://api.bm.parts/prices/prom/{quote(brand)}"
    try:
        r=bm.s.post(url, json={"warehouses": whs}, timeout=120)
        if r.status_code!=200: return None, []
        text=r.text
    except Exception:
        return None, []
    sample=text[:2000]; delim=";" if sample.count(";")>=sample.count(",") else ","
    rows=list(csv.reader(io.StringIO(text), delimiter=delim))
    if len(rows)<2: return None, []
    return rows[0], rows[1:]

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
    brands=car_brands(bm)
    print(f"[bmparts] авто-марок для синхронізації: {len(brands)}")
    header=None; seen=set(); out_rows=[]; brands_hit=0; last=0.0
    for brand in brands:
        dt=time.time()-last
        if dt<MIN_INTERVAL: time.sleep(MIN_INTERVAL-dt)
        last=time.time()
        h, rows=prom_rows(bm, brand, whs)
        if not rows: continue
        if header is None and h: header=h
        n=0
        for r in rows:
            if not r: continue
            code=str(r[0]).strip()               # Код_товару — перша колонка Prom-формату
            if not code or code in seen: continue
            seen.add(code); out_rows.append(r); n+=1
            if ROW_LIMIT and len(out_rows)>=ROW_LIMIT: break
        if n: brands_hit+=1; print(f"[bmparts] {brand}: {n}")
        if ROW_LIMIT and len(out_rows)>=ROW_LIMIT:
            print(f"[bmparts] досягнуто BMPARTS_TAB_LIMIT={ROW_LIMIT} — зупиняюсь"); break
    if header is None:
        print("[bmparts] жодних даних (усі марки порожні або помилка) — вкладку НЕ чіпаю"); return
    W=len(header)
    grid=[header]+[(r+[""]*(W-len(r)))[:W] for r in out_rows]
    print(f"[bmparts] зібрано {len(out_rows)} унікальних позицій у наявності по {brands_hit} марках")
    if not LIVE:
        print(f"[bmparts] DRY-RUN (LIVE≠1): у «{BM_TAB}» НЕ писав. Заголовок і перші рядки:")
        print("  HEAD:", " | ".join(str(x) for x in header[:10]))
        for r in grid[1:4]: print("  ROW :", " | ".join(str(x)[:18] for x in r[:10]))
        return
    ss=gc.open_by_key(ID_HUB)
    ws=None
    for w in ss.worksheets():
        if w.title.strip().casefold()==BM_TAB.casefold(): ws=w; break
    if ws is None:
        ws=ss.add_worksheet(title=BM_TAB, rows=len(grid)+10, cols=W)
        print(f"[bmparts] створено вкладку «{BM_TAB}»")
    ws.resize(rows=len(grid)+10, cols=W)
    ws.clear()                                   # повне дзеркало: старе стирається, пишемо свіже
    B=5000
    for j in range(0, len(grid), B):
        ws.update(values=grid[j:j+B], range_name=f"A{j+1}")
    print(f"[bmparts] ЗАПИСАНО в «{BM_TAB}»: {len(grid)-1} позицій (актуальне дзеркало наявності BM Parts).")

if __name__=="__main__": main()
