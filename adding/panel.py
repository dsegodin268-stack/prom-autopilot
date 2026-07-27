# -*- coding: utf-8 -*-
"""«Пульт_Додавання» — інтерфейс керування конвеєром прямо в таблиці.

Власник не має ходити в GitHub Actions, щоб вибрати джерело. Він відкриває
вкладку, обирає зі списку «Джерело» (BM Parts / прайс BMW / прайс Porsche /
усі), ставить скільки позицій за раз і куди писати — і запускає. Воркфлоу
add.yml лишається як був: його поля стають ЗАПАСНИМИ значеннями на випадок,
коли клітинка пульта порожня або вкладки ще нема.

Пріоритет: значення з пульта > змінна оточення > дефолт.
Вимкнути пульт цілком (для тестів і CI): env PANEL=0."""
import os

from common.config import AI_LEVELS, PANEL_TAB, SOURCES, SRC_BMPARTS, TARGETS
from common.normalize import num
from common.sheets import find_ws, keyf

TARGET_LABEL = {"export": "Export Products Sheet (бойова)",
                "staging": "Staging_Prom (чернетка)"}
LABEL_TARGET = {keyf(v): k for k, v in TARGET_LABEL.items()}
TRUE = {"true", "1", "так", "yes", "on", "✓", "+"}

# (ключ, підпис, дефолт, підказка, список значень для випадайки)
ROWS = [
    ("source", "Джерело", SRC_BMPARTS,
     "Звідки брати кандидатів. BM Parts дає повну картку; прайси — лише артикул, назву й ціну.",
     SOURCES),
    ("brand", "Марка (для BM Parts)", "BMW",
     "Марка авто у фіді BM Parts. Для прайсів постачальників не використовується.",
     None),
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


def enabled():
    return (os.environ.get("PANEL") or "1").strip().lower() not in ("0", "false", "no", "off")


def ensure_panel(sh):
    """Створює вкладку з підписами, дефолтами і випадайками; наявні значення
    власника НЕ перетирає — оновлює лише підписи й підказки."""
    ws = find_ws(sh, PANEL_TAB, create_cols=3)
    vals = ws.get_all_values()
    cur = {keyf(r[0]): (r[1] if len(r) > 1 else "") for r in vals[1:] if r and r[0]}
    out = [["Параметр", "Значення", "Підказка"]]
    for _k, label, default, hint, _opts in ROWS:
        had = cur.get(keyf(label), "")
        v = had if str(had).strip() != "" else default
        out.append([label, v, hint])
    ws.update(values=out, range_name=f"A1:C{len(out)}", value_input_option="USER_ENTERED")

    reqs = [
        {"updateSheetProperties": {
            "properties": {"sheetId": ws.id, "gridProperties": {"frozenRowCount": 1}},
            "fields": "gridProperties.frozenRowCount"}},
        {"updateDimensionProperties": {
            "range": {"sheetId": ws.id, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 1},
            "properties": {"pixelSize": 210}, "fields": "pixelSize"}},
        {"updateDimensionProperties": {
            "range": {"sheetId": ws.id, "dimension": "COLUMNS", "startIndex": 1, "endIndex": 2},
            "properties": {"pixelSize": 260}, "fields": "pixelSize"}},
        {"updateDimensionProperties": {
            "range": {"sheetId": ws.id, "dimension": "COLUMNS", "startIndex": 2, "endIndex": 3},
            "properties": {"pixelSize": 520}, "fields": "pixelSize"}},
    ]
    for i, (k, _label, _d, _h, opts) in enumerate(ROWS):
        rng = {"sheetId": ws.id, "startRowIndex": i + 1, "endRowIndex": i + 2,
               "startColumnIndex": 1, "endColumnIndex": 2}
        if opts:
            reqs.append({"setDataValidation": {"range": rng, "rule": {
                "condition": {"type": "ONE_OF_LIST",
                              "values": [{"userEnteredValue": o} for o in opts]},
                "showCustomUi": True, "strict": True}}})
        elif k == "instock_only":
            reqs.append({"setDataValidation": {"range": rng, "rule": {
                "condition": {"type": "BOOLEAN"}, "strict": True}}})
    ws.spreadsheet.batch_update({"requests": reqs})
    print(f"[пульт] «{PANEL_TAB}» готовий")
    return ws


def read_panel(sh):
    """Налаштування прогону: пульт > env > дефолт."""
    env_target = (os.environ.get("TARGET") or "export").strip().lower()
    s = {"source": (os.environ.get("SOURCE") or SRC_BMPARTS).strip(),
         "brand": (os.environ.get("BRAND") or "BMW").strip(),
         "max": int(num(os.environ.get("MAX") or 0)),
         "target": env_target if env_target in TARGETS else "export",
         "ai": (os.environ.get("AI_LEVEL") or AI_LEVELS[-1]).strip(),
         "instock_only": (os.environ.get("INSTOCK_ONLY") or "").strip().lower() in TRUE,
         "min_cost": num(os.environ.get("MIN_COST") or 0)}
    if not enabled():
        print("[пульт] вимкнено (PANEL=0) — беру значення з воркфлоу")
        return s
    try:
        ws = find_ws(sh, PANEL_TAB, create_cols=3)
        vals = ws.get_all_values()
        if len(vals) < 2:
            ensure_panel(sh)
            vals = find_ws(sh, PANEL_TAB).get_all_values()
    except Exception as e:
        print(f"[пульт] недоступний ({str(e)[:70]}) — беру значення з воркфлоу")
        return s
    kv = {}
    for i, r in enumerate(vals[1:]):
        if i < len(_ORDER) and r and len(r) > 1:
            kv[_ORDER[i]] = str(r[1]).strip()

    if kv.get("source") in SOURCES:
        s["source"] = kv["source"]
    if kv.get("brand"):
        s["brand"] = kv["brand"]
    if kv.get("max"):
        s["max"] = int(num(kv["max"]))
    t = LABEL_TARGET.get(keyf(kv.get("target", "")))
    if t:
        s["target"] = t
    elif keyf(kv.get("target", "")) in TARGETS:
        s["target"] = keyf(kv["target"])
    if kv.get("ai") in AI_LEVELS:
        s["ai"] = kv["ai"]
    if kv.get("instock_only") != "":
        s["instock_only"] = keyf(kv.get("instock_only", "")) in TRUE
    if kv.get("min_cost"):
        s["min_cost"] = num(kv["min_cost"])
    print(f"[пульт] джерело={s['source']} | марка={s['brand']} | max={s['max']} | "
          f"куди={s['target']} | ШІ={s['ai']} | лише в наявності={s['instock_only']} | "
          f"мін.собівартість={s['min_cost']:.0f}")
    return s


def write_status(sh, text):
    """Пише рядок «Останній запуск» — власник бачить результат там же, де кнопки."""
    try:
        ws = find_ws(sh, PANEL_TAB)
        ws.update(values=[[text]],
                  range_name=f"B{_ORDER.index('status') + 2}",
                  value_input_option="RAW")
    except Exception as e:
        print(f"[пульт] статус не записано: {str(e)[:70]}")
