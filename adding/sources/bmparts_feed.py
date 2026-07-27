# -*- coding: utf-8 -*-
"""Джерело A: bulk-фід BM Parts (POST /prices/prom/{brand}) у форматі імпорту Prom.

Це ЄДИНЕ джерело, яке одразу дає ПОВНУ картку: фото, характеристики, ціну,
наявність і кількість. Тому позиції звідси майже завжди виходять рівня 1
(adding/completeness.py) і можуть їхати прямо в Export.

Тут же живе мапа наявності (stock_map): GET /product/{uuid} наявність НЕ віддає,
її можна взяти лише з цього ж bulk-фіду."""
import csv
import io
import os
import re

from common.config import SRC_BMPARTS
from common.normalize import num
from common.prom_format import read_chars
from common.sheets import keyf
from adding.sources import candidate, key


def warehouse_uuids(bm):
    """Склади: env WAREHOUSES (через кому) або всі склади компанії."""
    env = (os.environ.get("WAREHOUSES") or "").strip()
    wh = env.split(",") if env else [w.get("uuid") for w in bm.warehouses()]
    return [w.strip() for w in wh if w and str(w).strip()]


def feed_rows(bm, brand):
    """CSV фіду -> список рядків. Роздільник визначаємо, бо BM Parts віддає
    то кому, то крапку з комою (у репрайсері та сама логіка)."""
    text = bm.prom_price_csv(brand, warehouse_uuids(bm))
    sample = text[:2000]
    delim = ";" if sample.count(";") >= sample.count(",") else ","
    rows = list(csv.reader(io.StringIO(text), delimiter=delim))
    return rows


def indexer(head):
    """Пошук колонки за будь-якою з назв-синонімів."""
    fi = {keyf(h): i for i, h in enumerate(head)}

    def col(*names, d=None):
        for n in names:
            if keyf(n) in fi:
                return fi[keyf(n)]
        return d
    return col


def cell(row, i):
    return (row[i] if (i is not None and i < len(row) and row[i] is not None) else "")


def stock_map(bm, brand=None):
    """{ключ_коду: (Наявність, Кількість)} з bulk-фіду — для MODE=enrich."""
    brand = brand or os.environ.get("BRAND", "BMW").strip()
    stock = {}
    try:
        rows = feed_rows(bm, brand)
        col = indexer(rows[0])
        ic, ia, iq = col("Код_товару", "Ідентифікатор_товару", d=0), col("Наявність"), col("Кількість")
        for r in rows[1:]:
            if len(r) > ic and r[ic]:
                stock[keyf(r[ic])] = (cell(r, ia).strip(), cell(r, iq).strip())
        print(f"[bm-feed] наявність: {len(stock)} кодів")
    except Exception as e:
        print(f"[bm-feed] фід наявності недоступний ({str(e)[:90]}) — "
              f"Наявність лишиться з картки, Кількість порожня")
    return stock


def _photos(s):
    return [u for u in re.split(r"[,\s]+", str(s or "")) if u.startswith("http")]


def _presence_days(av, qty):
    """Колонка «Наявність» у форматі Prom: «+»/«!» — є, «-»/«0»/порожньо — нема,
    число — стільки днів під замовлення."""
    v = str(av or "").strip()
    if v in ("+", "!", "true", "True") or num(qty) > 0:
        return "available", 0
    if v.isdigit() and v != "0":
        return "order", int(v)
    return "order", 15


def candidates(bm, ex_codes=(), brand=None, limit=0):
    """Нові коди фіду (яких ще нема в Export) -> список candidate()."""
    brand = brand or os.environ.get("BRAND", "BMW").strip()
    rows = feed_rows(bm, brand)
    if len(rows) < 2:
        print(f"[bm-feed] {brand}: фід порожній")
        return []
    head = rows[0]
    col = indexer(head)
    c_code = col("Код_товару", "Ідентифікатор_товару", d=0)
    c_name = col("Назва_позиції_укр", "Назва_позиції", d=1)
    c_price = col("Ціна")
    c_avail, c_qty = col("Наявність"), col("Кількість")
    c_photo = col("Посилання_зображення", "Посилання_зображення_укр")
    c_gname, c_gid = col("Назва_групи"), col("Номер_групи")
    c_maker = col("Виробник")
    have = {keyf(c) for c in ex_codes} | {key(c) for c in ex_codes}

    out, seen = [], set()
    for r in rows[1:]:
        if not r or len(r) <= c_code or not r[c_code]:
            continue
        art = r[c_code].strip()
        k = key(art)
        if not k or k in seen or k in have or keyf(art) in have:
            continue
        seen.add(k)
        presence, days = _presence_days(cell(r, c_avail), cell(r, c_qty))
        c = candidate(
            source=SRC_BMPARTS,
            article=art,
            name_src=cell(r, c_name),
            cost=num(cell(r, c_price)),
            qty=int(num(cell(r, c_qty))),
            presence=presence,
            days=days,
            brand=cell(r, c_maker) or brand,
            photos=_photos(cell(r, c_photo)),
            chars=read_chars(head, r),
            group_hint=cell(r, c_gname) or cell(r, c_gid),
        )
        # позиція з каталогу BM Parts: OEM і сумісність гарантовано прийдуть
        # з GET /product/{uuid} на етапі enrich, у bulk-фіді їх просто немає
        c["matched_bm"] = True
        out.append(c)
        if limit and len(out) >= limit:
            break
    print(f"[bm-feed] {brand}: {len(rows)-1} рядків -> {len(out)} нових кандидатів")
    return out
