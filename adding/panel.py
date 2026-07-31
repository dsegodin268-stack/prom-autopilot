# -*- coding: utf-8 -*-
"""«Пульт_Додавання» — вкладка керування конвеєром просто з таблиці.

ІСТОРІЯ. 29.07.2026 власник вирішив, що окрема вкладка-пульт не потрібна, і
вкладка перестала створюватись автоматично. 31.07.2026 рішення ЗМІНЕНО ним же:
керувати всім треба з таблиці, не заходячи на GitHub («він потрібен тільки
розробникам»). Тому вкладка знову створюється сама — при першому ж прогоні,
якщо її нема.

Пріоритет: значення з пульта > змінна оточення (поля воркфлоу) > дефолт.
Вимкнути читання пульта цілком (для тестів і CI): env PANEL=0.

ДЖЕРЕЛА І МАРКИ — СПИСКАМИ. Раніше в пульті було рівно одне джерело й рівно
одна марка, тож за прогін підтягувався тільки BM Parts і тільки BMW. Тепер у
клітинку можна написати кілька через кому: «BM Parts, BMW прайс (Баварія)» і
«BMW, MINI». Випадайка лишилась як підказка (strict=False), щоб можна було
дописати руками другу назву.

КАРТКА З НУЛЯ. Рядок «Картка з нуля (нема в BM Parts)» вмикає збірку повної
картки для позицій, яких у каталозі BM Parts просто нема. Три стани, бо ризик
різний: «Вимкнено» — як раніше, позиція пропускається; «Так, у чернетку» —
збираємо й кладемо в Staging_Prom на перевірку людиною; «Так, одразу в Export»
— тільки для того, хто свідомо готовий пустити такі картки в живу таблицю.
Навіть у третьому режимі картка без фото в Export не поїде ніколи: це стереже
completeness.route_card, і цього правила пульт не скасовує."""
import os
import re

from common.config import (AI_LEVELS, PANEL_TAB, SOURCES, SRC_ALL, SRC_BMPARTS,
                           SUPPLIER_BOOKS, TARGETS)
from common.normalize import num
from common.sheets import find_ws, keyf

TARGET_LABEL = {"export": "Export Products Sheet (жива)",
                "staging": "Staging_Prom (чернетка)"}
LABEL_TARGET = {keyf(v): k for k, v in TARGET_LABEL.items()}
TRUE = {"true", "1", "так", "yes", "on", "✓", "+"}

# Три стани режиму «картка з нуля» — див. докстрінг модуля.
SCRATCH_OFF = "Вимкнено"
SCRATCH_STAGING = "Так, у чернетку"
SCRATCH_EXPORT = "Так, одразу в Export"
SCRATCH = [SCRATCH_OFF, SCRATCH_STAGING, SCRATCH_EXPORT]
SCRATCH_MODE = {keyf(SCRATCH_OFF): "off", keyf(SCRATCH_STAGING): "staging",
                keyf(SCRATCH_EXPORT): "export"}
MODE_SCRATCH = {v: k for k, v in
                zip(("off", "staging", "export"), SCRATCH)}

_SRC_BY_KEY = {keyf(s): s for s in SOURCES}

# (ключ, підпис, дефолт, підказка, список значень для випадайки)
ROWS = [
    ("source", "Джерела", SRC_BMPARTS,
     "Можна кілька через кому: «BM Parts, BMW прайс (Баварія)». BM Parts дає повну картку; прайси — лише артикул, назву й ціну.",
     SOURCES),
    ("brand", "Марки (для BM Parts)", "BMW",
     "Можна кілька через кому: «BMW, MINI». Марка авто у фіді BM Parts. Для прайсів постачальників не використовується.",
     None),
    ("scratch", "Картка з нуля (нема в BM Parts)", SCRATCH_OFF,
     "Позиція є в прайсі, але її нема в каталозі BM Parts. «Вимкнено» — пропускати. Інакше ШІ збирає картку з нуля. Без фото в Export не поїде ніколи.",
     SCRATCH),
    ("max", "Скільки позицій за раз", "200",
     "0 = без обмеження. Для прайсів кожна позиція = запит у довідник BM Parts (~2.5 с).",
     None),
    ("target", "Куди писати готові", TARGET_LABEL["export"],
     "Стосується ЛИШЕ карток рівня 1. Рівні 2 і 3 завжди йдуть у Staging_Prom.",
     [TARGET_LABEL["export"], TARGET_LABEL["staging"]]),
    ("ai", "Рівень ШІ", AI_LEVELS[-1],
     "«Без ШІ» — тільки детермінований двигун. ШІ ніколи не чіпає код, ціну, наявність і фото.",
     AI_LEVELS),
    ("instock_only", "Тільки в наявності", False,
     "Пропускати позиції під замовлення.",
     None),
    ("min_cost", "Мін. собівартість, ₴", "0",
     "Відсіює дріб'язок, на якому не заробити. 0 = не відсіювати.",
     None),
    ("status", "Останній запуск", "",
     "Заповнюється автоматично після кожного прогону.",
     None),
]
_ORDER = [r[0] for r in ROWS]

# Читаємо пульт ЗА ПІДПИСОМ, а не за номером рядка: власник міг лишити старий
# пульт, у якому рядка «Картка з нуля» ще нема, і позиційне читання зсунуло б
# усі значення на одне вниз. Старі підписи додані як синоніми.
_BY_LABEL = {keyf(label): k for k, label, _d, _h, _o in ROWS}
_BY_LABEL[keyf("Джерело")] = "source"
_BY_LABEL[keyf("Марка (для BM Parts)")] = "brand"


def enabled():
    return (os.environ.get("PANEL") or "1").strip().lower() not in ("0", "false", "no", "off")


def split_list(text):
    """«BM Parts, BMW прайс» -> ['BM Parts', 'BMW прайс']. Кома, крапка з комою,
    скісна риска й перенос рядка — усе розділювачі: власник пише як зручно."""
    return [p.strip() for p in re.split(r"[,;/\n]+", str(text or "")) if p.strip()]


def parse_sources(text):
    """Список джерел із клітинки. Невідому назву не мовчимо — пишемо в журнал,
    інакше одруківка тихо звузила б прогін до одного джерела."""
    out = []
    for p in split_list(text):
        s = _SRC_BY_KEY.get(keyf(p))
        if s == SRC_ALL:
            return [SRC_BMPARTS] + list(SUPPLIER_BOOKS)
        if s and s not in out:
            out.append(s)
        elif not s:
            print(f"[пульт] невідоме джерело «{p}» — пропускаю")
    return out or [SRC_BMPARTS]


def parse_brands(text, default="BMW"):
    out, seen = [], set()
    for p in split_list(text):
        u = p.upper()
        if u not in seen:
            seen.add(u)
            out.append(p)
    return out or [default]


def sources_of(st):
    """Список джерел прогону. Працює і зі старим st, де було лише st['source']."""
    return st.get("sources") or parse_sources(st.get("source") or SRC_BMPARTS)


def brands_of(st):
    return st.get("brands") or parse_brands(st.get("brand") or "BMW")


def _validation_reqs(ws):
    reqs = []
    for i, (k, _label, _d, _h, opts) in enumerate(ROWS):
        rng = {"sheetId": ws.id, "startRowIndex": i + 1, "endRowIndex": i + 2,
               "startColumnIndex": 1, "endColumnIndex": 2}
        if opts:
            # strict=False лише там, де значень може бути кілька через кому:
            # інакше Google не дав би зберегти «BM Parts, BMW прайс (Баварія)».
            strict = k not in ("source", "brand")
            reqs.append({"setDataValidation": {"range": rng, "rule": {
                "condition": {"type": "ONE_OF_LIST",
                              "values": [{"userEnteredValue": o} for o in opts]},
                "showCustomUi": True, "strict": strict}}})
        elif k == "instock_only":
            reqs.append({"setDataValidation": {"range": rng, "rule": {
                "condition": {"type": "BOOLEAN"}, "strict": True}}})
    return reqs


def ensure_panel(sh):
    """Створює вкладку з підписами, дефолтами і випадайками; наявні значення
    власника НЕ перетирає — оновлює лише підписи й підказки."""
    ws = find_ws(sh, PANEL_TAB, create_cols=3)
    vals = ws.get_all_values()
    # ключ -> значення, а не підпис -> значення: підписи ми якраз і міняємо
    # («Джерело» стало «Джерела»), і по старому підпису значення б загубилось.
    cur = {}
    for r in vals[1:]:
        if r and r[0]:
            k = _BY_LABEL.get(keyf(r[0]))
            if k:
                cur[k] = r[1] if len(r) > 1 else ""
    out = [["Параметр", "Значення", "Підказка"]]
    for k, label, default, hint, _opts in ROWS:
        had = cur.get(k, "")
        v = had if str(had).strip() != "" else default
        out.append([label, v, hint])
    ws.update(values=out, range_name=f"A1:C{len(out)}", value_input_option="USER_ENTERED")

    reqs = [
        {"updateSheetProperties": {
            "properties": {"sheetId": ws.id, "gridProperties": {"frozenRowCount": 1}},
            "fields": "gridProperties.frozenRowCount"}},
        {"updateDimensionProperties": {
            "range": {"sheetId": ws.id, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 1},
            "properties": {"pixelSize": 250}, "fields": "pixelSize"}},
        {"updateDimensionProperties": {
            "range": {"sheetId": ws.id, "dimension": "COLUMNS", "startIndex": 1, "endIndex": 2},
            "properties": {"pixelSize": 280}, "fields": "pixelSize"}},
        {"updateDimensionProperties": {
            "range": {"sheetId": ws.id, "dimension": "COLUMNS", "startIndex": 2, "endIndex": 3},
            "properties": {"pixelSize": 560}, "fields": "pixelSize"}},
    ] + _validation_reqs(ws)
    ws.spreadsheet.batch_update({"requests": reqs})
    print(f"[пульт] «{PANEL_TAB}» готовий")
    return ws


def _read_cells(sh):
    """{ключ: текст} з вкладки пульта. Нема вкладки — створюємо (31.07: власник
    керує з таблиці, тож пульт має з'явитись сам, а не після походу на GitHub).
    Читаємо за підписом; якщо підпис невпізнаний — за номером рядка, щоб
    саморобні перейменування не ламали прогін."""
    try:
        ws = find_ws(sh, PANEL_TAB)
        vals = ws.get_all_values()
    except BaseException as e:  # find_ws кидає SystemExit, коли вкладки нема
        print(f"[пульт] вкладки нема ({str(e)[:70]}) — створюю")
        try:
            ws = ensure_panel(sh)
            vals = ws.get_all_values()
        except Exception as e2:
            print(f"[пульт] не вдалося створити ({str(e2)[:70]}) — беру воркфлоу")
            return {}
    if len(vals) < 2:
        print(f"[пульт] «{PANEL_TAB}» порожня — беру значення з воркфлоу")
        return {}
    kv = {}
    for i, r in enumerate(vals[1:]):
        if not r or not str(r[0]).strip():
            continue
        k = _BY_LABEL.get(keyf(r[0])) or (_ORDER[i] if i < len(_ORDER) else None)
        if k:
            kv[k] = str(r[1]).strip() if len(r) > 1 else ""
    return kv


def _defaults():
    """Значення з воркфлоу (env) — те, що діє, коли пульта нема або PANEL=0."""
    env_target = (os.environ.get("TARGET") or "export").strip().lower()
    scr = keyf(os.environ.get("SCRATCH") or "")
    return {"sources": parse_sources(os.environ.get("SOURCE") or SRC_BMPARTS),
            "brands": parse_brands(os.environ.get("BRAND") or "BMW"),
            "scratch": SCRATCH_MODE.get(scr, scr if scr in ("off", "staging", "export") else "off"),
            "max": int(num(os.environ.get("MAX") or 0)),
            "target": env_target if env_target in TARGETS else "export",
            "ai": (os.environ.get("AI_LEVEL") or AI_LEVELS[-1]).strip(),
            "instock_only": (os.environ.get("INSTOCK_ONLY") or "").strip().lower() in TRUE,
            "min_cost": num(os.environ.get("MIN_COST") or 0)}


def read_panel(sh):
    """Налаштування прогону: пульт > env > дефолт."""
    s = _defaults()
    if not enabled():
        print("[пульт] вимкнено (PANEL=0) — беру значення з воркфлоу")
    else:
        kv = _read_cells(sh)
        if kv.get("source"):
            s["sources"] = parse_sources(kv["source"])
        if kv.get("brand"):
            s["brands"] = parse_brands(kv["brand"])
        if kv.get("scratch"):
            m = SCRATCH_MODE.get(keyf(kv["scratch"]))
            if m:
                s["scratch"] = m
            elif keyf(kv["scratch"]) in TRUE:
                s["scratch"] = "staging"   # старе «Так» = найбезпечніший режим
        if kv.get("max"):
            s["max"] = int(num(kv["max"]))
        t = LABEL_TARGET.get(keyf(kv.get("target", "")))
        if t:
            s["target"] = t
        elif keyf(kv.get("target", "")) in TARGETS:
            s["target"] = keyf(kv["target"])
        if kv.get("ai") in AI_LEVELS:
            s["ai"] = kv["ai"]
        if kv.get("instock_only", "") != "":
            s["instock_only"] = keyf(kv.get("instock_only", "")) in TRUE
        if kv.get("min_cost"):
            s["min_cost"] = num(kv["min_cost"])
    # Сумісність зі старим кодом і тестами, які читають st["source"]/st["brand"].
    s["source"] = s["sources"][0]
    s["brand"] = s["brands"][0]
    print(f"[пульт] джерела={', '.join(s['sources'])} | марки={', '.join(s['brands'])} | "
          f"з нуля={s['scratch']} | max={s['max']} | куди={s['target']} | ШІ={s['ai']} | "
          f"лише в наявності={s['instock_only']} | мін.собівартість={s['min_cost']:.0f}")
    return s


def _status_to_panel(sh, line):
    """Дублює підсумок у клітинку «Останній запуск» самого пульта — власник
    дивиться саме туди, коли керує прогоном з таблиці."""
    try:
        ws = find_ws(sh, PANEL_TAB)
        vals = ws.get_all_values()
        for i, r in enumerate(vals):
            if r and _BY_LABEL.get(keyf(r[0])) == "status":
                ws.update(values=[[line]], range_name=f"B{i + 1}",
                          value_input_option="RAW")
                return
    except BaseException:
        pass


def write_status(sh, text):
    """Пише «Останній запуск» у клітинку Q1 вкладки «Огляд_Додавання» —
    меню «⚙️ Prom» у таблиці показує його першим пунктом (Код.gs, lastRun_) —
    і дублює в пульт, якщо вкладка пульта є."""
    from common.config import REVIEW_TAB
    line = text
    try:
        from datetime import datetime, timedelta, timezone
        try:
            from zoneinfo import ZoneInfo
            now = datetime.now(ZoneInfo("Europe/Kyiv"))
        except Exception:
            now = datetime.now(timezone(timedelta(hours=3)))
        stamp = now.strftime("%d.%m %H:%M")
        line = f"{stamp} — {text}"
        ws = find_ws(sh, REVIEW_TAB, create_cols=17)
        try:
            # у «Огляд_Додавання» сітка з 15 колонок (A..O) — Q1 за межами;
            # розширюємо, інакше APIError 400 «exceeds grid limits» (add #27)
            if int(getattr(ws, "col_count", 0) or 0) < 17:
                ws.resize(cols=17)
        except Exception:
            pass
        ws.update(values=[[line]], range_name="Q1", value_input_option="RAW")
    except BaseException as e:
        print(f"[пульт] статус не записано: {str(e)[:70]}")
    _status_to_panel(sh, line)
