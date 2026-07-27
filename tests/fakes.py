# -*- coding: utf-8 -*-
"""Підробки Google Sheets і BM Parts для сухого прогону БЕЗ мережі.

Навіщо. Конвеєр додавання має рівно два виходи назовні — таблиця і API BM Parts.
Якщо підмінити обидва, увесь ланцюг (пульт -> кандидати -> огляд -> валідатор ->
Export/Staging) можна ганяти в CI за частку секунди й ловити регресії ДО того,
як вони доїдуть до бойової таблиці. Жодного запиту в мережу тут не робиться.

Підробка навмисно поводиться як gspread у дрібницях, на яких легко обпектися:
  • get_all_values() повертає РЯДКИ, а не типи (булеве -> "TRUE"/"FALSE");
  • хвостові порожні рядки й колонки обрізаються;
  • update() пише блоком від початку діапазону («A1:O5» -> якір A1).
"""
import csv
import io
import re


def _a1(ref):
    """«B9» / «A1:O5» -> (рядок, колонка) якоря, 1-based."""
    m = re.match(r"^([A-Za-z]+)(\d+)", str(ref).split(":")[0].split("!")[-1])
    if not m:
        return 1, 1
    col = 0
    for ch in m.group(1).upper():
        col = col * 26 + (ord(ch) - 64)
    return int(m.group(2)), col


def _s(v):
    if v is True:
        return "TRUE"
    if v is False:
        return "FALSE"
    return "" if v is None else str(v)


class FakeWorksheet:
    def __init__(self, sh, title, wid, cols=26):
        self.spreadsheet = sh
        self.title = title
        self.id = wid
        self._cols = cols
        self.grid = []
        self.formats = []          # сюди лягають batch_update-запити оформлення

    # --- внутрішнє ---
    def _ensure(self, r, c):
        while len(self.grid) < r:
            self.grid.append([])
        row = self.grid[r - 1]
        while len(row) < c:
            row.append("")

    def _put(self, r, c, v):
        self._ensure(r, c)
        self.grid[r - 1][c - 1] = _s(v)

    # --- API gspread ---
    def get_all_values(self):
        last_r = 0
        last_c = 0
        for i, row in enumerate(self.grid, 1):
            for j, v in enumerate(row, 1):
                if str(v).strip():
                    last_r, last_c = max(last_r, i), max(last_c, j)
        out = []
        for row in self.grid[:last_r]:
            out.append([str(row[j]) if j < len(row) else "" for j in range(last_c)])
        return out

    def row_values(self, n):
        vals = self.get_all_values()
        return vals[n - 1] if len(vals) >= n else []

    def update(self, values=None, range_name="A1", value_input_option="RAW"):
        r0, c0 = _a1(range_name)
        for dr, row in enumerate(values or []):
            for dc, v in enumerate(row):
                self._put(r0 + dr, c0 + dc, v)

    def clear(self):
        self.grid = []

    def append_rows(self, rows, value_input_option="RAW"):
        start = len(self.get_all_values()) + 1
        for dr, row in enumerate(rows):
            for dc, v in enumerate(row):
                self._put(start + dr, 1 + dc, v)

    def batch_update(self, data, value_input_option="RAW"):
        for d in data:
            self.update(values=d["values"], range_name=d["range"])


class FakeSpreadsheet:
    def __init__(self):
        self._ws = []
        self.requests = []

    def worksheets(self):
        return list(self._ws)

    def add_worksheet(self, title, rows=1000, cols=26):
        ws = FakeWorksheet(self, title, wid=len(self._ws) + 1, cols=cols)
        self._ws.append(ws)
        return ws

    def ws(self, title):
        for w in self._ws:
            if w.title == title:
                return w
        return None

    def batch_update(self, body):
        self.requests.append(body)


# ---------------------------------------------------------------- BM Parts ---
FEED_HEAD = ["Код_товару", "Назва_позиції_укр", "Ціна", "Наявність", "Кількість",
             "Посилання_зображення", "Назва_групи", "Виробник",
             "Назва_Характеристики", "Одиниця_виміру_Характеристики", "Значення_Характеристики",
             "Назва_Характеристики", "Одиниця_виміру_Характеристики", "Значення_Характеристики",
             "Назва_Характеристики", "Одиниця_виміру_Характеристики", "Значення_Характеристики"]

# 1) повна позиція в наявності, тип впізнається -> рівень 1 -> Export
# 2) усе на місці, АЛЕ типу нема в GROUPS       -> рівень 2 -> Staging «нема група»
# 3) без фото, під замовлення 15 днів           -> рівень 3 -> Staging «чекає фото»
# 4) фото є, характеристик обмаль               -> рівень 2 -> Staging «на перевірку»
#
# Позиція 2 (масляний фільтр) з'явилась тут 27.07 як постійний вартовий: у сіді
# GROUPS нема запису для масляних фільтрів, тому map_group() чесно повертає ''.
# Така картка НЕ має потрапляти в бойову таблицю — інакше товар лягає в каталог
# Prom без групи й покупець його не знаходить. Вигадувати номер групи не можна.
FEED_ROWS = [
    ["34116792217", "Диск гальмівний передній BMW 3 F30", "2400", "+", "3",
     "https://cdn.bm.parts/f0.jpg", "Гальмівні диски", "BMW",
     "Виробник", "", "BMW", "Діаметр", "мм", "330", "Вісь", "", "передня"],
    ["11427953129", "Фільтр масляний BMW 3 F30", "300", "+", "5",
     "https://cdn.bm.parts/f1.jpg", "Фільтри", "BMW",
     "Виробник", "", "BMW", "Висота", "мм", "80", "Тип", "", "масляний"],
    ["34116794300", "Колодки гальмівні передні BMW 3 F30", "1200", "15", "0",
     "", "Гальма", "BMW",
     "Виробник", "", "BMW", "Вісь", "", "передня", "Тип", "", "дискові"],
    ["63117214941", "Фара права BMW 3 F30", "9500", "+", "1",
     "https://cdn.bm.parts/f3.jpg", "Оптика", "BMW",
     "Виробник", "", "BMW", "", "", "", "", "", ""],
]

_PRODUCTS = {
    "34116792217": {
        "article": "34116792217", "brand": "BMW", "name": "Диск гальмівний передній BMW 3 F30",
        "images": ["images/f0.jpg"], "nodes": "Гальмівні диски",
        "details": {"Виробник": "BMW", "Діаметр [мм]": "330", "Вісь": "передня"},
        "oe": [{"number": "34116792217", "is_oem": True}],
        "cars": [{"brand": "BMW", "model": "3 F30", "years": "12-18"}],
    },
    "11427953129": {
        "article": "11427953129", "brand": "BMW", "name": "Фільтр масляний BMW 3 F30",
        "images": ["images/f1.jpg"], "nodes": "Фільтри",
        "details": {"Виробник": "BMW", "Висота [мм]": "80", "Тип": "масляний"},
        "oe": [{"number": "11427953129", "is_oem": True}],
        "cars": [{"brand": "BMW", "model": "3 F30", "years": "12-18"}],
    },
    "34116794300": {
        "article": "34116794300", "brand": "BMW", "name": "Колодки гальмівні передні BMW 3 F30",
        "images": [], "nodes": "Гальма",
        "details": {"Виробник": "BMW", "Вісь": "передня", "Тип": "дискові"},
        "oe": [{"number": "34116794300", "is_oem": True}],
        "cars": [{"brand": "BMW", "model": "3 F30", "years": "12-18"}],
    },
    "63117214941": {
        "article": "63117214941", "brand": "BMW", "name": "Фара права BMW 3 F30",
        "images": ["images/f3.jpg"], "nodes": "Оптика",
        "details": {"Виробник": "BMW"},
        "oe": [{"number": "63117214941", "is_oem": True}],
        "cars": [{"brand": "BMW", "model": "3 F30", "years": "12-18"}],
    },
}


def _norm(s):
    return re.sub(r"[^0-9A-Za-z]", "", str(s or "")).upper()


class FakeBM:
    """Рівно ті методи BMParts, якими користується конвеєр. Без HTTP."""

    def __init__(self, rows=None):
        self.rows = rows if rows is not None else FEED_ROWS
        self.calls = []

    def warehouses(self):
        return [{"uuid": "wh-1"}]

    def prom_price_csv(self, brand, warehouses):
        self.calls.append(("feed", brand))
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";", lineterminator="\n")
        w.writerow(FEED_HEAD)
        for r in self.rows:
            w.writerow(r)
        return buf.getvalue()

    def get_product(self, code, by_code=True):
        self.calls.append(("product", code))
        return _PRODUCTS.get(_norm(code))
