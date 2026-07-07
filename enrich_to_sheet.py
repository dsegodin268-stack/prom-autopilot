# enrich_to_sheet.py — збагачення картки з BM Parts -> запис ОПИСУ у хаб-таблицю (Код_товару).
# Prom авто-фід сам затягує таблицю в базу. Ключ Prom НЕ потрібен (пишемо в таблицю, не в API).
# Env: GCP_SA_KEY (сервіс-акаунт, Editor), BMPARTS (токен BM Parts).
# Режими:
#   inspect (без WRITE_ARTICLE): друкує вкладки, заголовки, і кандидатів (є в таблиці І в BM Parts).
#   write   (WRITE_ARTICLE=<арт>): збагачує 1 товар, валідує, пише ЛИШЕ клітинку опису його рядка.
import os
import json
import time

ID_HUB = "1pesHiOHDq2Y4FYQECakfhIJlq08bg5_Pkm9e2YEDoic"
PRODUCTS_TAB = os.environ.get("PRODUCTS_TAB", "Export Products Sheet")


def gclient():
    import gspread
    return gspread.service_account_from_dict(json.loads(os.environ["GCP_SA_KEY"]))


def col_idx(header, *names):
    low = [str(h).strip().lower() for h in header]
    for n in names:
        n = n.lower()
        for i, h in enumerate(low):
            if h == n:
                return i
    for n in names:                       # запасне — часткове співпадіння
        n = n.lower()
        for i, h in enumerate(low):
            if n in h:
                return i
    return -1


def main():
    from bmparts import BMParts, assemble_card
    from validator import validate_card, summarize, worst_level, CRITICAL
    gc = gclient()
    ss = gc.open_by_key(ID_HUB)
    print("TABS:", [w.title for w in ss.worksheets()])
    ws = ss.worksheet(PRODUCTS_TAB)
    rows = ws.get_all_values()
    if not rows:
        print("порожня вкладка"); return
    header = rows[0]
    ci_art = col_idx(header, "Код_товару", "Ідентифікатор_товару", "артикул", "sku")
    ci_desc = col_idx(header, "Опис", "Опис_укр", "description")
    ci_name = col_idx(header, "Назва_позиції", "Назва", "name")
    print(f"cols: article=[{ci_art}]{header[ci_art] if ci_art >= 0 else '-'} | "
          f"desc=[{ci_desc}]{header[ci_desc] if ci_desc >= 0 else '-'} | "
          f"name=[{ci_name}]{header[ci_name] if ci_name >= 0 else '-'}")
    if ci_art < 0 or ci_desc < 0:
        print("НЕ знайшов колонку артикул/опис — перевір заголовки:", header[:15]); return

    bm = BMParts()
    want = os.environ.get("WRITE_ARTICLE", "").strip()

    if want:                                             # --- РЕЖИМ ЗАПИСУ ---
        target = None
        for ri in range(1, len(rows)):
            cell = rows[ri][ci_art].strip() if ci_art < len(rows[ri]) else ""
            if cell == want:
                target = ri; break
        if target is None:
            print(f"артикул {want} НЕ в таблиці"); return
        prod = bm.get_product(want)
        if not prod:
            print(f"BM Parts не знайшов {want}"); return
        card = assemble_card(prod)
        flags = validate_card(card, is_part=True)
        print("ВАЛІДАТОР:", summarize(flags))
        crit = [c for (_, l, c, _) in flags if l == CRITICAL]
        if crit:
            print("CRITICAL — НЕ пишу:", crit); return
        old = rows[target][ci_desc] if ci_desc < len(rows[target]) else ""
        print("НАЗВА:", card["name"])
        print("СТАРИЙ ОПИС (перші 160):", (old or "")[:160])
        print("НОВИЙ ОПИС (перші 400):", card["description"][:400])
        ws.update_cell(target + 1, ci_desc + 1, card["description"])   # ЛИШЕ клітинка опису
        print(f"OK: опис записано у рядок {target + 1}, колонка {ci_desc + 1} (артикул {want}).")
        print(">>> Prom затягне його авто-фідом за розкладом.")
        return

    # --- РЕЖИМ INSPECT: знайти кандидатів (є в таблиці І в BM Parts) ---
    arts = []
    for ri in range(1, len(rows)):
        a = rows[ri][ci_art].strip() if ci_art < len(rows[ri]) else ""
        if a:
            arts.append(a)
    print(f"всього артикулів у таблиці: {len(arts)}; перевіряю перші 40 у BM Parts...")
    found = []
    for a in arts[:40]:
        try:
            u = bm.search_uuid(a)
        except Exception as e:
            u = None
            print("  ", a, "err", str(e)[:60])
        if u:
            found.append(a)
            print("  ЗБІГ:", a, "->", u)
        if len(found) >= 5:
            break
        time.sleep(0.25)
    print("КАНДИДАТИ для канарки:", found)
    if found:
        print(f">>> Постав WRITE_ARTICLE={found[0]} щоб записати опис цьому товару.")


if __name__ == "__main__":
    main()
