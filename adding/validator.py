# -*- coding: utf-8 -*-
# Валідатор картки за ПРАВИЛА_PROM.md. Token-free, без API-викликів.
# CRITICAL — Prom відхилить при імпорті; WARN — пройде, але якість під питанням.
# 2026-07-24: підключений у конвеєр додавання (adding/run.py) — CRITICAL не пишеться в Export.
# 2026-07-26: validate_card() знає про рівень повноти — див. пояснення в самій функції.
import re

CRITICAL = "CRITICAL"
WARN = "WARN"

# [Prom] закритий список одиниць виміру
PROM_UNITS = {
    "шт.", "т", "кг", "г", "куб.м", "л", "кв.м", "кв.см", "кв.фут", "кв.дм", "м", "км",
    "дав", "мішок", "пара", "чол.", "упаковка", "сотка", "пог. м", "ящик", "мм", "мл",
    "гр/кв.м", "кг/кв.м", "100 г", "комплект", "набір", "моток", "рулон", "послуга",
    "см", "секція", "бухта", "об'єкт", "сторінка", "т/км", "добу", "ват", "лист",
    "карат", "хвилина", "кВт", "мВт", "бобіна", "палетомісць", "зміна", "од.",
    "година", "день", "тиждень", "місяць",
}

_LETTER = re.compile(r"[A-Za-zА-Яа-яІіЇїЄєҐґ]")
_SEO_NAME = ("купити", "продати", "оптом", "купить", "заказать", "недорого", "дешево")
_LINK = re.compile(r"https?://|www\.|\.com|t\.me/|viber|telegram|whatsapp|instagram", re.I)
_PHONE = re.compile(r"\+?380\d{9}|\b0\d{2}[\s\-]\d{3}[\s\-]?\d{2}[\s\-]?\d{2}\b")


def _has_letter(s):
    return bool(_LETTER.search(s or ""))


def validate_name(name):
    out = []
    n = (name or "").strip()
    if not n:
        return [(CRITICAL, "name_empty", "Назва порожня")]
    if not _has_letter(n):
        out.append((CRITICAL, "name_no_letters", "Назва без літер (лише цифри/символи)"))
    if "-" in n:
        out.append((CRITICAL, "name_dash", "Назва містить «-» (Prom відхилить)"))
    if re.search(r"  +", n):
        out.append((CRITICAL, "name_spaces", "Подвійні пробіли в назві"))
    if len(n) > 110:
        out.append((CRITICAL, "name_len", f"Назва {len(n)}>110 символів"))
    low = n.lower()
    for w in _SEO_NAME:
        if w in low:
            out.append((WARN, "name_seo", f"SEO-слово в назві: {w}"))
    if n == n.upper() and _has_letter(n):
        out.append((WARN, "name_caps", "Назва повністю ВЕЛИКИМИ літерами"))
    return out


def validate_description(desc):
    out = []
    d = (desc or "").strip()
    if not d:
        return [(CRITICAL, "desc_empty", "Опис порожній")]
    if len(d) > 50000:
        out.append((CRITICAL, "desc_len_max", f"Опис {len(d)}>50000 символів"))
    if len(d) < 30:
        out.append((WARN, "desc_short", "Опис <30 символів (Prom: замало)"))
    if _LINK.search(d):
        out.append((WARN, "desc_link", "Опис містить посилання/месенджер (Prom забороняє)"))
    if _PHONE.search(d):
        out.append((WARN, "desc_phone", "Опис містить телефон (Prom забороняє)"))
    return out


def validate_parts_description(desc):
    """Шаблон ЗАПЧАСТИНИ: сумісність + OEM/замінники + CTA."""
    out = []
    low = (desc or "").lower()
    if not re.search(r"підходить на|сумісн|встановлюється на", low):
        out.append((WARN, "part_no_fitment", "Нема блоку сумісності («Підходить на…»)"))
    if not re.search(r"oem|оригінальн|замінник|аналог|номер", low):
        out.append((WARN, "part_no_oem", "Нема OEM-номера / замінників"))
    if "підберемо за вас" not in low:
        out.append((WARN, "part_no_cta", "Нема обов'язкового CTA «Ми підберемо за вас»"))
    return out


def validate_characteristics(chars):
    out = []
    chars = chars or []
    if len(chars) < 2:
        out.append((WARN, "char_min", f"Характеристик {len(chars)}<2 (Prom рекомендує 2-3)"))
    for tpl in chars:
        unit = (tpl[1] if len(tpl) > 1 else "") or ""
        unit = unit.strip()
        if unit and unit not in PROM_UNITS:
            out.append((WARN, "char_unit", f"Невідома одиниця виміру: «{unit}»"))
    return out


def validate_images(urls):
    out = []
    us = [u for u in (urls or []) if u and str(u).strip()]
    if not us:
        return [(CRITICAL, "img_none", "Нема жодного фото (Prom вимагає ≥1)")]
    for u in us:
        if not str(u).lower().startswith("https://"):
            out.append((WARN, "img_http", f"Фото не https: {str(u)[:40]}"))
    return out


def validate_card(card, is_part=True, level=1):
    """card: dict(name, description, chars, images, price, group_id, product_id).
    Повертає список (field, level, code, message).

    level — рівень повноти з adding/completeness.py (1 повна / 2 без дрібниць /
    3 нема фото). Рівень 3 за визначенням їде в Staging_Prom зі статусом
    «чекає фото»: там брак фото — це ОЧІКУВАНИЙ стан, а не помилка. Якби
    img_none лишався CRITICAL, конвеєр відхиляв би картку ще ДО маршрутизації,
    і позиція не потрапляла б узагалі нікуди — ні в Export, ні в чернетку.
    Тому на рівні 3 (і лише для img_none) прапорець знижується до WARN.
    Усі інші CRITICAL — назва з «-», порожній опис, нема ідентифікатора —
    валять картку як і раніше, однаково для Export і для Staging.
    А в Export картка без фото не потрапляє ніколи: route() у completeness.py
    відправляє рівень 3 у Staging безумовно."""
    flags = []
    for f in validate_name(card.get("name")):
        flags.append(("name",) + f)
    for f in validate_description(card.get("description")):
        flags.append(("desc",) + f)
    if is_part:
        for f in validate_parts_description(card.get("description")):
            flags.append(("part",) + f)
    for f in validate_characteristics(card.get("chars")):
        flags.append(("char",) + f)
    for lvl, code, msg in validate_images(card.get("images")):
        if level == 3 and code == "img_none":
            lvl, msg = WARN, "Нема фото — картка йде в чернетку зі статусом «чекає фото»"
        flags.append(("img", lvl, code, msg))
    if not card.get("product_id"):
        flags.append(("req", CRITICAL, "id_empty", "Нема Ідентифікатор_товару"))
    if card.get("price") in (None, "", 0, "0"):
        flags.append(("req", WARN, "price_empty", "Ціна порожня/0"))
    if not card.get("group_id"):
        flags.append(("req", WARN, "group_empty", "Нема групи"))
    return flags


def worst_level(flags):
    if any(l == CRITICAL for (_, l, _, _) in flags):
        return CRITICAL
    return WARN if flags else "OK"


def summarize(flags):
    if not flags:
        return "OK"
    codes = [c for (_, _, c, _) in flags]
    return f"{worst_level(flags)}: " + ", ".join(codes)
