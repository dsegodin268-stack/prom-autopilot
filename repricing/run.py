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
запис Ціна/Наявність/Кількість у Export Products Sheet.

LIVE: пише ЗАВЖДИ, окрім явного LIVE=0 (див. common/config.py).
ЗВІТ: вкладка «Звіт_Ціни» формується ПАРАЛЕЛЬНО з Export — одразу після основного
запису в Export, і ще раз після крос-перевірки autonova. Звіт НІКОЛИ не пишеться,
якщо не писався Export (DRY-RUN), щоб вони не розходилися. Вимкнути: REPORT=0.

Порядок запису (важливо!): СПОЧАТКУ пишемо основний прохід у Export (гарантовано,
швидко), і ЛИШЕ ПОТІМ виконуємо повільну крос-перевірку autonova, що дописує свої
уточнення інкрементально. Так «в бойовий Export пишеться все» навіть якщо повільну
крос-перевірку вб'ють на середині / вона впаде по мережі.

Зміни 2026-07-24: видалено IMAP-гілку і статичний кеш autonova_web_cache.csv;
УВІМКНЕНО якірний захист (раніше був мертвим кодом); крос-перевірку autonova
перенесено ПІСЛЯ основного запису + інкрементальний дозапис її результатів;
LIVE тепер дефолтно ПИШЕ; «Звіт_Ціни» формується паралельно з Export і прив'язаний
до нього (нема запису в Export -> нема й звіту)."""
import os

from common.config import EXPORT_TAB, C_NAME, C_PRICE, C_AVAIL, C_QTY, ID_BMW, ID_PORSCHE, LIVE
from common.normalize import num
from common.pricing import price_with_competitor
from common.sheets import gclient
from repricing import guard
from repricing.export_writer import read_export, write_updates, avail_cell
from repricing.overrides import get_overrides, get_competitors
from repricing.report import write_report
from repricing.sources.bmw_porsche_sheets import read_all_tabs
from repricing.sources.autonova_drive import pull_autonova_drive
from repricing.sources.autonova_web import pull_autonova_web, recheck_autonova_faster
from repricing.sources.bmw_pairs import pull_pairs_from_best
from repricing.sources.bmparts_prices import pull_bmparts


def _report(gc, catalog, best, instock, overrides, comps, guard_status, final_price_map, tag):
    """Звіт «Звіт_Ціни» — ПАРАЛЕЛЬНО з Export: пишемо одразу після основного запису
    в Export і ще раз після крос-перевірки autonova, з тих самих даних.

    Два залізні правила:
      * якщо Export не писався (DRY-RUN, LIVE=0) — звіт теж НЕ пишемо. Саме
        розбіжність «звіт свіжий / Export старий» і збивала з пантелику;
      * падіння звіту ніколи не валить прогін — Export уже записано."""
    if (os.environ.get("REPORT") or "").strip() == "0":
        print("[report] звіт вимкнено вручну (REPORT=0)")
        return
    if not LIVE:
        print("[report] DRY-RUN (LIVE=0): звіт НЕ чіпав, щоб не розходився з Export")
        return
    try:
        write_report(gc, catalog, best, instock, overrides, comps, guard_status, final_price_map)
        print(f"[report] {tag}")
    except Exception as e:
        print("[report] не вдався (Export це не зачіпає):", str(e)[:140])


def _calc_row(code, i, vals, best, instock, overrides, comps, anchor,
              guard_status, final_price_map, held):
    """Рахує I(Ціна)/P(Наявність)/Q(Кількість) для ОДНОГО кода.
    Мутує vals[i], guard_status, final_price_map, held.
    -> список update-діапазонів (порожній, якщо нема постачальника)."""
    it = best.get(code)
    if not it:
        return []  # нема постачальника — рядок НЕ чіпаємо взагалі
    row = vals[i]
    cur = num(row[C_PRICE])
    has_manual = bool(overrides.get(code) or comps.get(code))
    newp = overrides.get(code) or price_with_competitor(it["cost"], comps.get(code))
    ok, status = guard.check(code, newp, cur, anchor, has_manual)
    guard_status[code] = status
    final_price_map[code] = int(newp)
    aq = instock.get(code, 0)  # наявність + кількість пишемо завжди (склад — не ціна)
    row[C_AVAIL], row[C_QTY] = avail_cell(aq, it.get("days"))
    rn = i + 1
    ups = [{"range": f"P{rn}:Q{rn}", "values": [[row[C_AVAIL], row[C_QTY]]]}]
    if ok:
        row[C_PRICE] = int(newp)
        ups.append({"range": f"I{rn}", "values": [[int(newp)]]})
    else:
        held.append((code, cur, int(newp)))
    return ups


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

    # --- 3) розрахунок + якірний захист (ОСНОВНИЙ прохід по всьому каталогу) ---
    only = os.environ.get("LIVE_ONLY")
    keep = set(a.strip().upper() for a in only.split(",") if a.strip()) if only else None
    catalog = {code: {"name": vals[i][C_NAME], "price": vals[i][C_PRICE]} for code, i in idx.items()}
    guard_status = {}
    final_price_map = {}
    held = []
    updates = []
    matched = 0
    for code, i in idx.items():
        if code not in best:
            continue  # нема постачальника
        if keep and code not in keep:
            continue  # канарка LIVE_ONLY
        matched += 1
        updates += _calc_row(code, i, vals, best, instock, overrides, comps, anchor,
                             guard_status, final_price_map, held)
    price_upd = sum(1 for u in updates if u["range"].startswith("I"))
    print(f"[calc] зіставлено {matched}, ціну оновлено {price_upd}, утримано {len(held)} (якірний захист)")

    # --- 4) ЗАПИС основного проходу ПЕРШИМ (до повільної крос-перевірки!) ---
    if LIVE and updates:
        write_updates(ws, updates)
        print(f"[export] ЗАПИСАНО основний прохід у «{EXPORT_TAB}»: ціна {price_upd} + "
              f"наявність/кількість {matched} рядків (утримані ціни та без постачальника не чіпав). "
              f"Prom підтягне фідом.")
    elif not LIVE:
        print(f"[export] DRY-RUN (LIVE≠1): у «{EXPORT_TAB}» НЕ писав. Приклади порахованого:")
        shown = 0
        for code, i in idx.items():
            if code in final_price_map and shown < 8:
                print(f" {code}: ціна={final_price_map[code]} статус={guard_status.get(code)} "
                      f"наяв={vals[i][C_AVAIL]} к-ть={vals[i][C_QTY]}")
                shown += 1

    # --- 4б) ЗВІТ одразу ж, ПАРАЛЕЛЬНО з Export (а не в самому кінці прогону) ---
    _report(gc, catalog, best, instock, overrides, comps, guard_status, final_price_map,
            f"«Звіт_Ціни» синхронізовано з основним записом Export ({matched} позицій)")

    # --- 5) КРОС-ПЕРЕВІРКА autonova ПІСЛЯ основного запису (уточнення, НЕ блокує запис).
    # Позиції «під замовлення» з прайсів (BMW/Porsche/Drive/BMParts) можуть бути в наявності
    # на autonova -> ставимо кращу наявність/термін і ціну з найшвидшого джерела; дозаписуємо
    # інкрементально (пачками), щоб проміжний прогрес зберігся, навіть якщо прогін уб'ють. ---
    if cookie:
        order_codes = [c for c in idx
                       if c in best and best[c].get("presence") == "order"
                       and best[c].get("brand") != "Авто-web"]
        print(f"[recheck] «під замовлення» з прайсів для крос-перевірки autonova: {len(order_codes)}")
        if order_codes:
            buf = []

            def _flush():
                if buf:
                    if LIVE:
                        write_updates(ws, buf)
                    buf.clear()

            def _write_upgrade(k):
                if keep and k not in keep:
                    return
                i = idx.get(k)
                if i is None:
                    return
                buf.extend(_calc_row(k, i, vals, best, instock, overrides, comps, anchor,
                                     guard_status, final_price_map, held))
                if len(buf) >= 80:  # пачка ~40 позицій (I + P:Q) — тримаємо квоту запису
                    _flush()

            upgraded = recheck_autonova_faster(order_codes, best, instock, cookie, on_upgrade=_write_upgrade)
            _flush()
            tag = "ЗАПИСАНО в Export" if LIVE else "DRY-RUN (не писав)"
            print(f"[export] крос-перевірка autonova: прискорено {len(upgraded)} позицій — {tag}.")

            # --- 6) ЗВІТ переписуємо, щоб він показав і результати крос-перевірки ---
            if upgraded:
                _report(gc, catalog, best, instock, overrides, comps, guard_status, final_price_map,
                        f"«Звіт_Ціни» оновлено після крос-перевірки autonova (+{len(upgraded)} позицій)")

    if held:
        print(f"[guard] УТРИМАНІ ціни ({len(held)}; перші 30) — сильне зниження/нижче якоря без конкурента:")
        for a, c, nw in held[:30]:
            print(f"[guard] {a}: {c:.0f} -> {nw}")


if __name__ == "__main__":
    main()
