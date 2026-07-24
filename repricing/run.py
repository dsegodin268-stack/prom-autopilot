#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""МОДУЛЬ «ОНОВЛЕННЯ ЦІН» — точка входу (запуск: python -m repricing.run).

Водоспад собівартості (перше влучення виграє):
  1) BMW Sheet + Porsche Sheet (Google-прайси)
  2) AutoNova-Drive (zip з Drive-теки, наповнює Apps Script)
  3) BMW-пари з аркушів (подвоєні номери через дефіс)
  4) autonova-web (живий catalogue-api під дилерською кукі AUTONOVA_COOKIE)
  5) BM Parts /prices/list
Далі: ціна = override || конкурент−1 || тариф -> якірний захист (guard) ->
запис Ціна/Наявність/Кількість у Export Products Sheet (лише при LIVE=1) ->
журнал «Звіт_Ціни».

Зміни 2026-07-24: видалено IMAP-гілку і статичний кеш autonova_web_cache.csv;
УВІМКНЕНО якірний захист (раніше був мертвим кодом)."""
import os

from common.config import ID_BMW, ID_PORSCHE, EXPORT_TAB, C_NAME, C_PRICE, C_AVAIL, C_QTY, LIVE
from common.normalize import num
from common.pricing import price_with_competitor
from common.sheets import gclient
from repricing import guard
from repricing.export_writer import read_export, write_updates
from repricing.overrides import get_overrides, get_competitors
from repricing.report import write_report
from repricing.sources.bmw_porsche_sheets import read_all_tabs
from repricing.sources.autonova_drive import pull_autonova_drive
from repricing.sources.autonova_web import pull_autonova_web
from repricing.sources.bmw_pairs import pull_pairs_from_best
from repricing.sources.bmparts_prices import pull_bmparts


def main():
    gc = gclient()
    if not gc:
        print("[fatal] нема GCP_SA_KEY — без доступу до Google-таблиць працювати нема з чим")
        return
    best = {}
    instock = {}

    # --- 1) основні прайси ---
    read_all_tabs(gc, ID_BMW, "BMW", best, instock)
    read_all_tabs(gc, ID_PORSCHE, "Porsche", best, instock, force="available")
    folder = os.environ.get("AUTONOVA_FOLDER_ID")
    if folder:
        pull_autonova_drive(folder, best, instock)
    else:
        print("[autonova] нема AUTONOVA_FOLDER_ID — джерело AutoNova-Drive пропущено")
    print(f"[supply] собівартість зібрано: {len(best)} артикулів, у наявності {len(instock)}")

    overrides = get_overrides(gc)
    comps = get_competitors(gc)
    anchor = guard.load_anchor()

    ws, vals, idx = read_export(gc)
    print(f"[export] каталог «{EXPORT_TAB}»: {len(idx)} кодів")

    # --- 2) добір кодів БЕЗ постачальника: пари -> autonova-web -> BM Parts ---
    _miss = [c for c in idx if c not in best]
    print(f"[supply+] без постачальника: {len(_miss)}; приклади: " + " | ".join(str(c) for c in _miss[:10]))
    pull_pairs_from_best(_miss, best, instock)

    _miss = [c for c in idx if c not in best]
    cookie = os.environ.get("AUTONOVA_COOKIE")
    if cookie:
        cookie = cookie.replace("\r", "").replace("\n", "").strip()
    if _miss and cookie:
        pull_autonova_web(_miss, best, instock, cookie)
    elif _miss:
        print("[autonova-web] нема AUTONOVA_COOKIE — крок пропущено (додай секрет AUTONOVA_COOKIE)")

    _miss = [c for c in idx if c not in best]
    if _miss:
        pull_bmparts(_miss, best, instock)
    _left = [c for c in idx if c not in best]
    print(f"[supply+] після добору: собівартість {len(best)}; лишилось без постачальника {len(_left)}")

    # --- 3) розрахунок + якірний захист + підготовка запису ---
    only = os.environ.get("LIVE_ONLY")
    keep = set(a.strip().upper() for a in only.split(",") if a.strip()) if only else None
    catalog = {}
    guard_status = {}
    final_price_map = {}
    held = []
    updates = []
    matched = 0
    for code, i in idx.items():
        row = vals[i]
        cur = num(row[C_PRICE])
        catalog[code] = {"name": row[C_NAME], "price": row[C_PRICE]}
        it = best.get(code)
        if not it:
            continue  # нема постачальника — рядок НЕ чіпаємо взагалі
        if keep and code not in keep:
            continue  # канарка LIVE_ONLY
        matched += 1
        has_manual = bool(overrides.get(code) or comps.get(code))
        newp = overrides.get(code) or price_with_competitor(it["cost"], comps.get(code))
        ok, status = guard.check(code, newp, cur, anchor, has_manual)
        guard_status[code] = status
        final_price_map[code] = int(newp)

        aq = instock.get(code, 0)  # наявність + кількість пишемо завжди (склад — не ціна)
        if aq > 0:
            row[C_AVAIL] = "+"
            row[C_QTY] = int(aq)
        else:
            row[C_AVAIL] = "15"
            row[C_QTY] = ""
        rn = i + 1
        updates.append({"range": f"P{rn}:Q{rn}", "values": [[row[C_AVAIL], row[C_QTY]]]})
        if ok:
            row[C_PRICE] = int(newp)
            updates.append({"range": f"I{rn}", "values": [[int(newp)]]})
        else:
            held.append((code, cur, int(newp)))
    price_upd = sum(1 for u in updates if u["range"].startswith("I"))
    print(f"[calc] зіставлено {matched}, ціну оновлено {price_upd}, утримано {len(held)} (якірний захист)")

    # --- 4) запис ---
    if LIVE and updates:
        write_updates(ws, updates)
        print(f"[export] ЗАПИСАНО в «{EXPORT_TAB}»: ціна {price_upd} + наявність/кількість {matched} рядків "
              f"(утримані ціни та без постачальника не чіпав). Prom підтягне фідом.")
    else:
        print(f"[export] DRY-RUN (LIVE≠1): у «{EXPORT_TAB}» НЕ писав. Приклади порахованого:")
        shown = 0
        for code, i in idx.items():
            if code in final_price_map and shown < 8:
                print(f" {code}: ціна={final_price_map[code]} статус={guard_status.get(code)} "
                      f"наяв={vals[i][C_AVAIL]} к-ть={vals[i][C_QTY]}")
                shown += 1

    try:
        write_report(gc, catalog, best, instock, overrides, comps, guard_status, final_price_map)
    except Exception as e:
        print("[report]", str(e)[:140])
    if held:
        print(f"[guard] УТРИМАНІ ціни ({len(held)}; перші 30) — сильне зниження/нижче якоря без конкурента:")
        for a, c, nw in held[:30]:
            print(f"[guard] {a}: {c:.0f} -> {nw}")


if __name__ == "__main__":
    main()
