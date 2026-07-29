#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Проба BM Parts (запуск: python -m tools.bmparts_probe [артикул|BULK:BMW|LIST]).
LIST — шапка й перші рядки /prices/list (діагностика колонок наявності/кількості);
BULK:<марка> — склади + перші 15 рядків prom_price_csv; інакше — картка одного
артикула через build-ланцюг + валідатор."""
import os
import sys

from common.bmparts_client import BMParts, assemble_card
from adding.validator import summarize, validate_card


def main():
    art = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("PROBE_ARTICLE", "")).strip()
    bm = BMParts()
    if art.upper() == "LIST":
        # Той самий запит, що робить repricing/sources/bmparts_prices.py.
        # Мета: побачити СПРАВЖНІ назви колонок (наявність/кількість), бо
        # нічний прогін показав «додано 35 кодів (у наявності: 0)».
        whs = [w.get("uuid") for w in bm.warehouses() if w.get("uuid")]
        print("[list] складів: %d" % len(whs))
        r = bm.s.post("https://api.bm.parts/prices/list",
                      json={"warehouses": whs, "format": "csv", "products_type": "code"},
                      timeout=180)
        print("[list] HTTP %s; байт: %d" % (r.status_code, len(r.text or "")))
        lines = (r.text or "").splitlines()
        print("[list] рядків: %d" % len(lines))
        for ln in lines[:12]:
            print("[list] " + ln[:400])
        sys.exit(0)
    if art.upper().startswith("BULK"):
        brand = art.split(":", 1)[1].strip() if ":" in art else "BMW"
        whs = bm.warehouses()
        wh = [w["uuid"] for w in whs]
        print("[bulk] склади(%d): %s" % (len(whs), ", ".join("%s=%s" % (w.get("name"), w.get("uuid")) for w in whs)))
        csv_text = bm.prom_price_csv(brand, wh)
        lines = csv_text.splitlines()
        print("[bulk] бренд=%s всього рядків=%d" % (brand, len(lines)))
        for ln in lines[:15]:
            print("[bulk] " + ln[:300])
        sys.exit(0)
    prod = bm.get_product(art)
    if not prod:
        print(f"[bmparts] артикул {art!r} не знайдено")
        sys.exit(1)
    card = assemble_card(prod)
    print("=== КАРТКА ===")
    print("Назва:", card["name"])
    print("Фото:", len(card["images"]), "| Характеристик:", len(card["chars"]))
    print("--- Опис ---")
    print(card["description"])
    print("=== ВАЛІДАТОР ===", summarize(validate_card(card, is_part=True)))


if __name__ == "__main__":
    main()
