# -*- coding: utf-8 -*-
"""Єдине місце для ID таблиць, назв вкладок і констант колонок."""
import os

# Google-таблиці
ID_HUB = "1pesHiOHDq2Y4FYQECakfhIJlq08bg5_Pkm9e2YEDoic"        # головний HUB (Prom тягне фід)
ID_BMW = "1KXaDLqBsOAtX0MxUoX39jpia9boISxl1xUxPihhU77I"        # прайс BMW (Баварія Моторс)
ID_PORSCHE = "1oVSVg1cBxGj-DA66c5_FoAtp6zOthdnF_xTY_ugez2g"    # прайс Porsche
ID_BMPARTS_BOOK = os.environ.get("BMPARTS_SHEET_ID") or "1sGAA3KRHKm4oeNtL56MpAr3BaMWBmajZ7hGtDnb12Q0"  # окрема книга «BM Parts»

# Вкладки HUB
EXPORT_TAB = "Export Products Sheet"   # БОЙОВА: Prom тягне фід звідси
REPORT_TAB = "Звіт_Ціни"               # журнал репрайсера
REVIEW_TAB = "Огляд_Додавання"         # кандидати на додавання
STAGING_TAB = "Staging_Prom"
BM_TAB = "BMParts"                     # вкладка в окремій книзі BM Parts

# Формат ЕКСПОРТУ Prom, 0-based індекси колонок Export Products Sheet
C_CODE = 0    # A Код_товару
C_NAME = 1    # B Назва_позиції
C_PRICE = 8   # I Ціна
C_AVAIL = 15  # P Наявність
C_QTY = 16    # Q Кількість

# LIVE: за замовчуванням ПИШЕ в бойову таблицю.
# DRY-RUN лише при ЯВНОМУ LIVE=0 (або 0/false/no). Порожнє чи невиставлене значення = ПИШЕ.
# Причина зміни 24.07: у GitHub не була виставлена змінна vars.LIVE -> у воркфлоу
# прилітало LIVE="" -> старе `== "1"` давало DRY-RUN -> Export Products Sheet місяцями
# не оновлювався (а «Звіт_Ціни» писався завжди, бо не мав цієї перевірки — звідси й
# ілюзія «звіт свіжий, Export старий»). Тепер мовчазний DRY-RUN неможливий.
LIVE = (os.environ.get("LIVE") or "1").strip().lower() not in ("0", "false", "no", "off")
