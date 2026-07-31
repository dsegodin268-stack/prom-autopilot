#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""МОДУЛЬ «ДОДАВАННЯ ПОЗИЦІЙ» — точка входу (запуск: python -m adding.run).

MODE=review : джерела з «Пульт_Додавання» -> кандидати -> «Огляд_Додавання»
              (фото, ціна, РІВЕНЬ повноти, чого бракує, галка «Взяти»).
MODE=enrich : відмічені «Взяти» -> контент BM Parts -> card_builder -> ВАЛІДАТОР
              -> Export (лише рівень 1) або Staging_Prom (рівні 2 і 3).
MODE=ai_scan: те саме, що enrich, але НІЧОГО НЕ ПИШЕ в Export і Staging —
              лише проганяє відмічені позиції через увесь конвеєр (збірка,
              валідатор, ШІ-аудит) і кладе присуд у колонку «Статус». Це
              «примірка»: видно, що саме поїде і де проблема, ще до запису.
MODE=panel  : лише створити/оновити пульт і вийти.
MODE=ai_check : нічого не додає — по черзі пінгує КОЖНОГО ШІ-провайдера
              й каже, чий ключ живий, у кого ліміт, а чий не приймається
              (adding/ai_check.py). Товарних даних у запиті нема.

Різниця ai_check і ai_scan одним рядком: ai_check перевіряє КЛЮЧІ, ai_scan —
ПОЗИЦІЇ. Обидва нічого не змінюють у таблиці, крім клітинки статусу.

Правила, які тут тримаються буквально:
  • ціна, валюта, наявність і кількість — від постачальника, у якого купуємо;
    довідник BM Parts дає лише контент;
  • CRITICAL від валідатора в Export не потрапляє НІКОЛИ;
  • картка без фото не потрапляє в Export НІКОЛИ (рівень 3 -> Staging)."""
import os
import re

import gspread

from common.config import EXPORT_TAB, ID_HUB, LIVE, REVIEW_TAB, SRC_BMPARTS, STAGING_TAB
from common.normalize import num
from common.prom_format import write_chars
from common.sheets import find_ws, keyf, open_hub
from adding.ai_layer import audit_card, audit_line, providers_ready
from adding.card_builder import build_fields, product_from_candidate, repair_card
from adding.completeness import level_card, route_card
from adding.panel import brands_of, ensure_panel, read_panel, write_status
from adding.review import do_review, parse_avail
from adding.sources import candidate, key
from adding.sources.bmparts_feed import stock_map
from adding.sources.lookup import bm_lookup
from adding.validator import CRITICAL, summarize, validate_card, worst_level

MODE = os.environ.get("MODE", "review").strip().lower()
MAX = int(num(os.environ.get("MAX") or 0))
TRUE = {"true", "1", "так", "yes", "on", "✓", "+"}


def _row_from_fields(ex_head, f, chars):
    """Скаляри — за назвою колонки; характеристики — за розкладкою шапки
    (common/prom_format.py сам розбирає, трійки там чи пари)."""
    row = [f.get(h, "") for h in ex_head]
    return write_chars(ex_head, row, chars)


def _valid_card(f, chars, imgs, price, art):
    """Поля картки в тому вигляді, у якому їх бачить валідатор.

    Винесено окремо 27.07: після другого проходу ШІ (repair_card) тексти в `f`
    змінюються, і картку треба перевірити ЩЕ РАЗ — тими самими воротами, а не
    полегшеними. Дві копії цього словника неминуче розійшлися б, і перевірка
    після правки почала б відрізнятися від перевірки до неї."""
    return {"name": f.get("Назва_позиції_укр"), "description": f.get("Опис_укр"),
            "chars": chars, "images": imgs, "price": price,
            "product_id": art, "group_id": f.get("Номер_групи"),
            # meta_title / meta_desc / keywords додано 27.07: без них валідатор
            # не бачив половини чекліста §10 — довжину мета-полів, кількість
            # ключовиків, наявність каталожного номера в меті.
            "meta_title": f.get("HTML_заголовок_укр"),
            "meta_desc": f.get("HTML_опис_укр"),
            "keywords": f.get("Пошукові_запити_укр"),
            # Російські двійники (27.07). Без них перевірка мови бачила лише
            # половину картки: у бойову таблицю пішла назва «Пыльник
            # амортизатора (переднього)» — саме російське поле, до якого код
            # тоді не мав доступу.
            "name_ru": f.get("Назва_позиції"),
            "keywords_ru": f.get("Пошукові_запити"),
            # 28.07. Опис і мета російською додані після рядка 4039: у ньому
            # російський опис містив український блок характеристик, а код про
            # це поле нічого не знав і мовчав.
            "description_ru": f.get("Опис"),
            "meta_title_ru": f.get("HTML_заголовок"),
            "meta_desc_ru": f.get("HTML_опис"),
            # Друга вісь — розділ каталогу Prom. Передаємо ОБИДВА поля:
            # валідатор звіряє посилання з ідентифікатором, бо в бойовій
            # таблиці вони мусять описувати той самий розділ.
            "section_id": f.get("Ідентифікатор_підрозділу"),
            "section_url": f.get("Посилання_підрозділу")}


def manual_photos(text):
    """Колонка «Фото вручну (посилання)» -> список URL.

    Навіщо вона. ШІ не вміє робити фотографії, а Prom не пропускає позицію без
    жодного зображення. Тому для картки з нуля єдиний спосіб дотягти її до
    Export — щоб власник вклеїв посилання на фото прямо в огляді. Розділювачі
    ті самі, що всюди: кома, крапка з комою, пробіл, перенос рядка."""
    out = []
    for p in re.split(r"[\s,;|]+", str(text or "").strip()):
        p = p.strip()
        if p.lower().startswith(("http://", "https://")) and p not in out:
            out.append(p)
    return out


def _cand_from_row(head_i, r):
    """Рядок «Огляд_Додавання» -> candidate(). Огляд — контракт між етапами:
    усе, що потрібно для ціни й наявності, вже лежить у рядку, тому прайс
    постачальника вдруге не читається і переплутати джерело неможливо."""
    g = lambda name, d="": (r[head_i[name]].strip()
                            if head_i.get(name) is not None and head_i[name] < len(r) and r[head_i[name]]
                            else d)
    presence, days = parse_avail(g("Наявність"))
    qty = int(num(g("К-ть")))
    return candidate(
        source=g("Джерело", SRC_BMPARTS),
        article=g("Артикул"),
        name_src=g("Назва (як у джерелі)"),
        cost=num(g("Собівартість, ₴")),
        qty=qty if presence == "available" else 0,
        presence=presence,
        days=days,
        brand="",
        # Фото власника мають пріоритет: bm_lookup ставить свої, лише коли
        # список порожній, тож вручну вклеєне посилання нічим не затреться.
        photos=manual_photos(g("Фото вручну (посилання)")),
    )


def _staging(sh, ex_head):
    """Вкладка чернетки з тією ж шапкою, що й Export, — щоб рядок звідти можна
    було просто перенести в бойову таблицю без перескладання колонок."""
    ws = find_ws(sh, STAGING_TAB, create_cols=max(len(ex_head), 31))
    try:
        first = ws.row_values(1)
    except Exception:
        first = []
    if not first:
        ws.update(values=[ex_head], range_name="A1", value_input_option="RAW")
    return ws


def do_enrich(sh, st, scan=False):
    """Збірка карток за галками «Взяти».

    scan=True — режим «примірка» (MODE=ai_scan, кнопка в таблиці). Проганяємо
    рівно той самий конвеєр: довідник, card_builder, валідатор, ШІ-аудит,
    ШІ-правка, маршрут. Різниця РІВНО одна — нічого не дописуємо ні в Export,
    ні в Staging_Prom. Присуд лягає в колонку «Статус».

    Чому саме прапорець, а не окрема функція перевірки: окрема функція неминуче
    почала б судити інакше, ніж бойовий прогін, і перевірка перестала б щось
    означати. Тут же власник бачить те саме рішення, яке ухвалить справжній
    запуск."""
    rv = find_ws(sh, REVIEW_TAB)
    rows = rv.get_all_values()
    if not rows:
        raise SystemExit("огляд порожній")
    head = rows[0]
    head_i = {}
    for i, h in enumerate(head):
        head_i.setdefault(keyf(h), i)
    hi = {name: head_i.get(keyf(name)) for name in
          ["Джерело", "Артикул", "Назва (як у джерелі)", "Собівартість, ₴",
           "Наявність", "К-ть", "Взяти", "Статус", "Фото вручну (посилання)"]}
    if hi["Взяти"] is None or hi["Артикул"] is None:
        raise SystemExit(f"в «{REVIEW_TAB}» нема колонок «Взяти»/«Артикул» — "
                         f"перезапусти MODE=review")

    export = find_ws(sh, EXPORT_TAB)
    ex_vals = export.get_all_values()
    ex_head = ex_vals[0]
    ex_codes = {key(r[0]) for r in ex_vals[1:] if r and r[0]}

    selected = []
    for rn, r in enumerate(rows[1:], start=2):
        c_take = hi["Взяти"]
        if len(r) <= c_take or keyf(r[c_take]) not in TRUE:
            continue
        c = _cand_from_row(hi, r)
        if c["article"]:
            selected.append((rn, c))
    if MAX:
        selected = selected[:MAX]
    print(f"[add] відмічено «Взяти»: {len(selected)}")
    if not selected:
        print("[add] нема відмічених — постав галки «Взяти»")
        return

    from adding.review import _bm
    bm = _bm()
    # Свіжа наявність BM Parts: між оглядом і enrich могли минути дні.
    # Для позицій із прайсів наявність лишається та, що в огляді, — її джерело
    # прайс постачальника, а не BM Parts.
    # 31.07: марок тепер може бути кілька, тож фід читаємо по кожній і зливаємо
    # в одну мапу. Раніше бралась одна st["brand"], і позиція іншої марки тихо
    # лишалася зі старою наявністю з огляду.
    stock = {}
    if bm and any(c["source"] == SRC_BMPARTS for _rn, c in selected):
        for br in brands_of(st):
            try:
                part = stock_map(bm, br)
            except Exception as e:
                print(f"[add] наявність {br}: помилка {str(e)[:70]}")
                continue
            print(f"[add] наявність BM Parts / {br}: {len(part)} позицій")
            stock.update(part)

    scratch_mode = st.get("scratch", "off")
    # Куди можуть їхати картки з нуля. «staging» означає: навіть ідеальна
    # картка з нуля лишається в чернетці — її ніхто не звіряв із реальністю.
    scratch_target = st["target"] if scratch_mode == "export" else "staging"
    if scratch_mode != "off":
        print(f"[add] картка з нуля: увімкнено, максимум — "
              f"{'Export' if scratch_mode == 'export' else 'Staging_Prom'}")
    if scan:
        print("[add] РЕЖИМ ПЕРЕВІРКИ (ai_scan): у таблицю нічого не дописується, "
              "пишу лише «Статус»")

    use_ai = st.get("ai") != "Без ШІ"
    # МОВЧАННЯ ШІ МУСИТЬ БУТИ ВИДНО (27.07). У прогоні №18 у журналі не було
    # жодного рядка «[ai]», а в «Статусі» — жодного зауваження, і це читалося
    # як «ШІ перевірив, усе добре». Насправді ШІ не перевіряв нічого: ключа не
    # було в жодного з 12 провайдерів. Тепер стан ladder друкується один раз на
    # прогін, а якщо ключів нема — про це пишеться в кожному рядку статусу.
    # Це не блокує конвеєр: картки складаються кодом і без ШІ.
    ready = providers_ready() if use_ai else []
    if not use_ai:
        no_ai = "ШІ вимкнено в пульті"
        print("[add] ШІ: вимкнено в пульті («Без ШІ»)")
    elif not ready:
        no_ai = "ШІ не перевіряв: нема ключа жодного провайдера"
        print("[add] ⚠ ШІ: нема ключа ЖОДНОГО провайдера — картки складаються "
              "без ШІ, зауважень від моделі не буде. Додай хоча б один ключ у "
              "Settings → Secrets.")
    else:
        no_ai = ""
        print(f"[add] ШІ: доступні провайдери — {', '.join(ready)}")
    to_export, to_staging, mark = [], [], {}
    seen = set()
    for rn, c in selected:
        art, k = c["article"], key(c["article"])
        try:
            if k in ex_codes or k in seen:
                mark[rn] = "вже в Export"
                print(f"[add] {art}: вже в Export — пропуск")
                continue
            if bm:
                bm_lookup(bm, c)
            # ПОЗИЦІЯ, ЯКОЇ НЕМА В КАТАЛОЗІ BM PARTS (31.07).
            # Було: така позиція з джерела BM Parts просто зникала («continue»),
            # а з прайсу постачальника йшла далі й лягала в чернетку майже
            # порожньою. Тепер обидва випадки веде один прапорець c["scratch"]:
            # card_builder попросить ШІ зібрати картку з нуля за окремими
            # правилами. Вимкнено в пульті — поведінка стара, один в один.
            if not c["matched_bm"]:
                if c["source"] == SRC_BMPARTS and scratch_mode == "off":
                    mark[rn] = "нема в BM Parts"
                    print(f"[add] {art}: не знайдено в BM Parts")
                    continue
                if scratch_mode != "off":
                    c["scratch"] = True
                    print(f"[add] {art}: нема в BM Parts — збираю картку з нуля")
            if c["source"] == SRC_BMPARTS and c["matched_bm"]:
                av, qt = stock.get(keyf(art), ("", ""))
                if av:
                    c["presence"], c["days"] = parse_avail(av)
                    c["qty"] = int(num(qt)) if c["presence"] == "available" else 0

            prod = product_from_candidate(c)
            f, name_ua, imgs, chars, price = build_fields(prod, cand=c, use_ai=use_ai)

            # --- ВАЛІДАТОР на воротах (ПРАВИЛА §10) ---
            # Рівень рахуємо ДО валідації: картці рівня 3 брак фото ставиться в
            # провину лише як WARN, бо вона й так їде в чернетку «чекає фото».
            # Інакше валідатор відхиляв би її тут і позиція гинула б мовчки.
            #
            # 27.07: рахуємо по ГОТОВІЙ картці (level_card), а не по кандидату.
            # Раніше стояло level(c) — тобто рівень визначала СИРОВИНА з прайсу,
            # ще до того, як card_builder зібрав характеристики, підтягнув фото
            # й змапив групу. Через це позиція з 10 характеристиками і 3 фото
            # отримувала «рівень 2: нема характеристик, сумісності» й лягала в
            # чернетку. Тепер судимо те, що реально поїде в таблицю.
            lv = level_card(chars, imgs, f.get("Номер_групи"),
                            f.get("Ідентифікатор_підрозділу"))
            card = _valid_card(f, chars, imgs, price, art)
            flags = validate_card(card, is_part=True, level=lv)
            verdict = summarize(flags)
            codes = {c for (_fl, _lv, c, _m) in flags}
            if worst_level(flags) == CRITICAL:
                mark[rn] = f"відхилено валідатором: {verdict[:90]}"
                print(f"[add] ⛔ {art}: {verdict}")
                continue

            # --- ДРУГА ДУМКА ШІ (дорадча, ПРАВИЛА §10 + Google) ---
            # Іде ПІСЛЯ валідатора і лише для карток, які вже пройшли: на
            # відхиленій витрачати добову квоту немає сенсу. Нема ключів /
            # вичерпано квоту / провайдер мовчить -> audit_line порожній, і
            # конвеєр працює точно так само, як досі.
            # known — те, що вже порахував валідатор за каноном. Передається
            # свідомо: модель має право лише на 6 зауважень, і хай витрачає їх
            # на те, чого код не бачить, а не на переказ довідника. Плюс ці
            # рядки лишаються у відповіді, навіть якщо ШІ мовчить, — розбіжність
            # із канонічною таблицею мусить бути видно завжди.
            canon_notes = [m for (_fl, _lv, c, m) in flags
                           if c.startswith(("canon_", "lang_"))]
            audit = audit_card(f, chars=chars, images=imgs, article=art,
                               group=f.get("Номер_групи"), known=canon_notes,
                               use_ai=use_ai)

            # --- ТРЕТІЙ КРОК: ШІ ДОПОВНЮЄ, А НЕ ЛИШЕ СВІТИТЬ ЧЕРВОНИМ ---
            # Вимога власника: «ШІ… буде це все перевіряти по жорсткій
            # інструкції, І ДОПОВНЮВАТИ, і робити повноцінну картку, яка одразу
            # залітає вже в кабінет». Досі аудит лише писав зауваження в рядок
            # статусу — тобто робота лишалася власникові. Тепер знайдене
            # віддається назад моделі з наказом переписати рівно ті поля.
            #
            # Торкається ВИКЛЮЧНО 10 текстових полів (назви, описи, мета,
            # пошукові): merge_ai фізично не вміє писати в інші ключі, а
            # repairable() ще й відсіює зауваження без префікса «поле:». Тому
            # ціна, наявність, група, характеристики й фото лишаються такими,
            # якими їх порахував код, — ПРАВИЛА §8 не порушені.
            fixed = []
            if audit and audit.get("verdict") == "fix":
                fixed = repair_card(f, prod, audit.get("issues"), use_ai=use_ai)
            if fixed:
                # ПЕРЕВІРКА ПІСЛЯ ПРАВКИ — та сама, не полегшена. Відповідь
                # другого проходу така сама сира, як і першого: якщо модель
                # «виправила» назву в 300 символів, це має спливти ТУТ, а не
                # у відмові Prom. Тому цикл повний: валідатор -> аудит.
                card = _valid_card(f, chars, imgs, price, art)
                flags = validate_card(card, is_part=True, level=lv)
                verdict = summarize(flags)
                codes = {c for (_fl, _lv, c, _m) in flags}
                if worst_level(flags) == CRITICAL:
                    mark[rn] = f"відхилено після правки ШІ: {verdict[:80]}"
                    print(f"[add] ⛔ {art}: після правки {verdict}")
                    continue
                canon_notes = [m for (_fl, _lv, c, m) in flags
                           if c.startswith(("canon_", "lang_"))]
                audit = audit_card(f, chars=chars, images=imgs, article=art,
                                   group=f.get("Номер_групи"), known=canon_notes,
                                   use_ai=use_ai)
            ai_note = audit_line(audit)
            if fixed:
                ai_note = (ai_note + " | " if ai_note else "") + f"✍ {', '.join(fixed)}"
            if no_ai:
                ai_note = (ai_note + " | " if ai_note else "") + no_ai

            # Маршрут — теж по ГОТОВІЙ картці (27.07). route_card перевіряє
            # рівно те, що поїде в таблицю: фото, ≥3 непорожні характеристики,
            # номер групи Prom і ідентифікатор підрозділу. Три окремі
            # запобіжники, що стояли тут раніше («не піде без фото», «нема
            # групи», «нема підрозділу»), увійшли всередину route_card — тому
            # видалені: дублювати ту саму умову в двох місцях означає рано чи
            # пізно змінити її лише в одному.
            # Картці з нуля стеля окрема: її зміст писала модель, а не каталог
            # постачальника, тому за замовчуванням вона зупиняється в чернетці.
            # Пустити такі одразу в Export можна лише свідомо — окремим пунктом
            # пульта. Решта воріт (фото, група, підрозділ) працюють як завжди.
            dest, status = route_card(chars, imgs, f.get("Номер_групи"),
                                      f.get("Ідентифікатор_підрозділу"),
                                      scratch_target if c.get("scratch") else st["target"])
            if c.get("scratch"):
                status = "з нуля: " + status
            # І ЩЕ ОДИН запобіжник — за каноном (27.07). Таблиця експорту
            # оголошена канонічним шаблоном, а в ній у кожної запчастини є
            # обов'язковий набір характеристик і «Код запчастини»: саме за цим
            # полем Prom підчіплює крос-довідник, тобто показує позицію тому,
            # хто шукає за номером. Картка без нього формально валідна — і саме
            # тому мовчки лягала б у бойову таблицю напівпорожньою. Тепер чекає
            # в чернетці. Рівень WARN, а не CRITICAL, теж свідомо: CRITICAL у
            # валідаторі означає `continue`, тобто позиція зникла б узагалі.
            if dest == "export" and ("canon_chars" in codes or "canon_part_code" in codes):
                why = "; ".join(m for (_fl, _lv, c, m) in flags
                                if c in ("canon_chars", "canon_part_code"))
                dest, status = "staging", f"не за каноном: {why[:70]}"
            row = _row_from_fields(ex_head, f, chars)
            (to_export if dest == "export" else to_staging).append(row)
            seen.add(k)
            # У режимі перевірки статус пишемо в майбутньому часі: «поїде в…».
            # Інакше власник побачив би «готово → Export» і був би певен, що
            # рядок уже в таблиці, хоча ми свідомо нічого не записали.
            arrow = "поїде в" if scan else "→"
            mark[rn] = ((f"перевірка: " if scan else "")
                        + f"{status} {arrow} {'Export' if dest == 'export' else 'Staging'}"
                        + ("" if verdict == "OK" else f" ({verdict[:60]})")
                        + (f" | {ai_note[:120]}" if ai_note else ""))
            print(f"[add] ✅ {art} | рівень {lv} | {name_ua[:38]} | ціна {price} | "
                  f"наяв {f.get('Наявність','')} к-ть {f.get('Кількість','')} | "
                  f"х-к {len(chars)} | фото {len(imgs)} | -> {dest} | {verdict}"
                  + (f" | {ai_note}" if ai_note else ""))
        except Exception as e:
            mark[rn] = "помилка"
            print(f"[add] {art}: ПОМИЛКА {e}")

    if scan:
        print(f"[add] перевірка завершена: пішло б у Export {len(to_export)}, "
              f"у Staging_Prom {len(to_staging)}. Нічого не записано — "
              f"дивись колонку «Статус».")
    elif to_export and LIVE:
        export.append_rows(to_export, value_input_option="RAW")
        print(f"[add] ✅ дописано {len(to_export)} карток у «{export.title}» (жива таблиця)")
    elif to_export:
        print(f"[add] DRY-RUN (LIVE=0): {len(to_export)} карток НЕ записано в Export")
    if to_staging and not scan:
        _staging(sh, ex_head).append_rows(to_staging, value_input_option="RAW")
        print(f"[add] ✅ дописано {len(to_staging)} карток у «{STAGING_TAB}» (на перевірку)")
    if not to_export and not to_staging:
        print("[add] нових карток нема (усе вже в Export / без даних / відхилено валідатором)")

    c_stat = hi["Статус"]
    if mark and c_stat is not None:
        rv.batch_update([{"range": gspread.utils.rowcol_to_a1(rn, c_stat + 1), "values": [[stt]]}
                         for rn, stt in mark.items()], value_input_option="RAW")

    try:
        from adding.ai_layer import usage_report
        ai_line = f" | ШІ: {usage_report()}"
    except Exception:
        ai_line = ""
    if scan:
        write_status(sh, f"перевірка позицій: {len(selected)} відмічено, "
                         f"пішло б у Export {len(to_export)}, у чернетку "
                         f"{len(to_staging)}, не пройшли "
                         f"{len(selected) - len(to_export) - len(to_staging)}"
                         f"{ai_line}")
    else:
        write_status(sh, f"enrich: Export {len(to_export)}, Staging {len(to_staging)}, "
                         f"відмічено {len(selected)}{ai_line}")


def main():
    # ПЕРЕВІРКА ШІ — до відкриття таблиці. Це діагностика ключів, і вона мусить
    # дійти до журналу навіть тоді, коли Google недоступний: інакше падіння
    # доступу до таблиці виглядало б як «ШІ не працює», хоча ШІ ні до чого.
    if MODE in ("ai_check", "ai-check"):
        from adding.ai_check import run_check
        sh = None
        try:
            sh = open_hub(os.environ.get("HUB_ID", ID_HUB))
        except BaseException as e:
            print(f"[ai-check] таблиця недоступна ({str(e)[:60]}) — звіт лише в журнал")
        run_check(sh)
        return

    sh = open_hub(os.environ.get("HUB_ID", ID_HUB))
    if MODE == "panel":
        ensure_panel(sh)
        return
    # 31.07: пульт знову створюється сам (усередині read_panel), якщо вкладки
    # нема — керування має бути в таблиці, а не в полях воркфлоу.
    st = read_panel(sh)
    if MODE == "enrich":
        do_enrich(sh, st)
    elif MODE in ("ai_scan", "ai-scan", "scan"):
        do_enrich(sh, st, scan=True)
    else:
        _st, cands = do_review(sh, st)
        write_status(sh, f"review: {len(cands)} кандидатів, джерела "
                         f"{', '.join(st.get('sources') or [st['source']])}")


if __name__ == "__main__":
    main()
