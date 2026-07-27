# -*- coding: utf-8 -*-
# Валідатор картки за ПРАВИЛА_PROM.md. Token-free, без API-викликів.
# CRITICAL — Prom відхилить при імпорті; WARN — пройде, але якість під питанням.
# 2026-07-24: підключений у конвеєр додавання (adding/run.py) — CRITICAL не пишеться в Export.
# 2026-07-26: validate_card() знає про рівень повноти — див. пояснення в самій функції.
# 2026-07-27: жодного числа тут більше не написано руками. Усі межі й словники
#   приходять з adding/rules.py — того самого файлу, з якого ГЕНЕРУЄТЬСЯ промпт
#   аудиту ШІ. Доти межа «70» лежала в трьох місцях (шлюз, валідатор, промпт), і
#   розійтись їм ніщо не заважало: код різав по одній, звіт лаявся на другу, ШІ
#   перевіряв третю — мовчки.
import re

from adding.rules import (AVAIL_MAX_DAYS_IN_STOCK, CHARS_MIN, CITIES, DESC_MAX, DESC_MIN,
                          DESC_TEXT_MIN, DESC_TEXT_SOFT_MAX, GTIN_LENGTHS, KW_BAD, KW_MAX,
                          KW_MIN, META_DESC_MAX, META_TITLE_MAX, META_TITLE_WORDS_MAX,
                          NAME_MAX, PROM_UNITS, REGIONS, SEO_WORDS, availability_ok,
                          bad_words_in, city_in, gtin_valid, has_contact, has_emoji,
                          price_ok, seo_words_in, unit_ok)

CRITICAL = "CRITICAL"
WARN = "WARN"

_LETTER = re.compile(r"[A-Za-zА-Яа-яІіЇїЄєҐґ]")
_SEO_NAME = SEO_WORDS
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
    if len(n) > NAME_MAX:
        out.append((CRITICAL, "name_len", f"Назва {len(n)}>{NAME_MAX} символів"))
    # Емодзі й контакти Prom називає забороненими прямо, і модерація такі назви
    # знімає. Тому це CRITICAL, а не побажання: краще картка почекає в чернетці,
    # ніж поїде в каталог і буде прихована вже там, де цього ніхто не побачить.
    if has_emoji(n):
        out.append((CRITICAL, "name_emoji", "Емодзі/нестандартні символи в назві (Prom забороняє)"))
    if has_contact(n):
        out.append((CRITICAL, "name_contact",
                    "Контакти в назві (сайт/пошта/телефон/месенджер) — Prom забороняє"))
    low = n.lower()
    for w in _SEO_NAME:
        if w in low:
            out.append((WARN, "name_seo", f"SEO-слово в назві: {w}"))
    # Місто — WARN, а не CRITICAL: пошук іде по основі слова, і теоретично
    # «одес» може трапитись усередині чужого слова. Хибний CRITICAL зупинив би
    # позицію, хибний WARN — лише рядок у звіті.
    c = city_in(n)
    if c:
        out.append((WARN, "name_region", f"Назва регіону в назві: {c} (Prom забороняє)"))
    if n == n.upper() and _has_letter(n):
        out.append((WARN, "name_caps", "Назва повністю ВЕЛИКИМИ літерами"))
    return out


def validate_description(desc):
    out = []
    d = (desc or "").strip()
    if not d:
        return [(CRITICAL, "desc_empty", "Опис порожній")]
    if len(d) > DESC_MAX:
        out.append((CRITICAL, "desc_len_max", f"Опис {len(d)}>{DESC_MAX} символів"))
    if len(d) < DESC_MIN:
        out.append((WARN, "desc_short", f"Опис <{DESC_MIN} символів (Prom: замало)"))
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
    """Мінімум — 3 (було 2). Це не наша вигадка: довідка Prom «Характеристики
    товарів» каже дослівно «Вказуйте не менше 3 характеристик товару». Число
    лежить у rules.CHARS_MIN, і туди ж дивиться промпт аудиту."""
    out = []
    chars = chars or []
    if len(chars) < CHARS_MIN:
        out.append((WARN, "char_min",
                    f"Характеристик {len(chars)}<{CHARS_MIN} (Prom: не менше {CHARS_MIN})"))
    for tpl in chars:
        unit = (tpl[1] if len(tpl) > 1 else "") or ""
        unit = unit.strip()
        if not unit_ok(unit):
            out.append((WARN, "char_unit", f"Невідома одиниця виміру: «{unit}»"))
    return out


def validate_gtin(gtin):
    """GTIN перевіряється контрольною цифрою, а не довжиною.

    До 27.07 перевірялась ЛИШЕ довжина: 13 випадкових цифр проходили як
    справжній EAN. Google такий товар відхиляє в Merchant Center — позиція
    зникає з Google Покупок, і причина ніде не написана. Порожній GTIN — не
    помилка: у більшості автозапчастин штрихкода немає взагалі, і Google прямо
    дозволяє його не вказувати."""
    g = str(gtin or "").strip()
    if not g:
        return []
    if not re.fullmatch(r"\d+", g):
        return [(WARN, "gtin_format", "GTIN містить не лише цифри (пробіли/дефіси заборонені)")]
    if len(g) not in GTIN_LENGTHS:
        return [(WARN, "gtin_len",
                 f"GTIN {len(g)} цифр — дозволено {'/'.join(str(x) for x in GTIN_LENGTHS)}")]
    if not gtin_valid(g):
        return [(WARN, "gtin_check", "GTIN не проходить контрольну цифру GS1 (Google відхилить)")]
    return []


def validate_availability(avail, days):
    """«В наявності» — лише якщо відправка ≤3 днів (правило Prom, не наше).

    Це та сама вимога, через яку в конвеєрі стоїть avail_cell(): позиція під
    замовлення мусить показувати реальний строк. Тут — контроль на воротах, щоб
    жоден новий шлях у код не проніс «в наявності» повз нього."""
    if availability_ok(avail, days):
        return []
    return [(WARN, "avail_days",
             f"«В наявності» при строку {days} дн. — Prom дозволяє лише до "
             f"{AVAIL_MAX_DAYS_IN_STOCK} днів")]


# ---------- Мета, ключовики, довжина опису (чекліст ПРАВИЛА §10) ----------
# 27.07: цих чотирьох перевірок не було ВЗАГАЛІ. Тому картка з 9 ключовиками,
# мета-заголовком на 96 символів і без артикула в меті проходила валідатор
# мовчки й лягала в Export. Тепер рахує код, а не око.
# META_TITLE_MAX, META_DESC_MAX, KW_MIN/KW_MAX, DESC_TEXT_* прийшли з rules.py —
# тут вони більше не оголошуються. Назви лишились ті самі, щоб старі імпорти
# (і тести) працювали без правок.
_TAG = re.compile(r"<[^>]+>")
_KW_BAD = KW_BAD
# Основи, а не словникові форми: «у Києві» — це «києв», а не «київ». Перший
# варіант списку ловив лише називний відмінок, тому «Купити недорого в Києві»
# проходило як чисте.
_CITIES = CITIES
# МІСТО і КРАЇНА — різні речі, і плутати їх не можна.
#   У ключових запитах шкодять обидві: за «фільтр Україна» деталь ніхто не шукає,
#   а місце у списку (15-40 фраз) така фраза з'їдає.
#   У мета-описі назва країни — це звичайна фраза про доставку («відправка щодня
#   по Україні»), яку Google показує в сніпеті й яка нікого не вводить в оману.
#   Забороняє ж §0-bis саме нав'язування МІСТА («купити в Києві») — його й ловимо.
# Поки список був один, прапорець meta_desc_region висів на КОЖНІЙ картці, і сенс
# валідатора зникав: коли попередження стоїть завжди, його перестають читати.
_REGIONS = REGIONS


def validate_meta(title, desc, article=""):
    """HTML-заголовок і HTML-опис: довжина, артикул, заборонені слова, місто.

    27.07 додано межу в СЛОВАХ. Довідка Prom про метатеги називає дві межі
    поруч: «не довше 12-ти слів або 70-ти символів». Дванадцять коротких слів
    легко вкладаються в 70 символів, тому перевірка довжини їх не ловила."""
    out = []
    art = str(article or "").strip().lower()
    for kind, val, limit, code in (("заголовок", title, META_TITLE_MAX, "meta_title"),
                                   ("опис", desc, META_DESC_MAX, "meta_desc")):
        v = str(val or "").strip()
        if not v:
            out.append((WARN, f"{code}_empty", f"Мета-{kind} порожній"))
            continue
        if len(v) > limit:
            out.append((WARN, f"{code}_len", f"Мета-{kind} {len(v)}>{limit} символів"))
        if code == "meta_title" and len(v.split()) > META_TITLE_WORDS_MAX:
            out.append((WARN, "meta_title_words",
                        f"Мета-заголовок {len(v.split())} слів > {META_TITLE_WORDS_MAX} (Prom)"))
        low = v.lower()
        if art and art not in low:
            out.append((WARN, f"{code}_no_art", f"Мета-{kind} без каталожного номера"))
        # У меті перевіряються ЛИШЕ рекламні слова. Загальні («автозапчастини»,
        # «запчастини для BMW») — це звичайна мова мета-опису, який читає людина
        # у видачі Google, а не окремий пошуковий запит, що з'їдає місце у списку.
        seo = seo_words_in(low)
        if seo:
            out.append((WARN, f"{code}_seo",
                        f"Заборонене слово в мета-{kind}і: {seo[0]}"))
        for r in _CITIES:
            if r in low:
                out.append((WARN, f"{code}_region", f"Місто у мета-{kind}і: {r}"))
                break
    return out


def validate_keywords(kws, article=""):
    """Пошукові запити: 15-40 фраз, без заборонених слів, без сміття, з артикулом."""
    out = []
    if isinstance(kws, str):
        kws = [k.strip() for k in kws.split(",")]
    kws = [k for k in (kws or []) if str(k).strip()]
    if not kws:
        return [(WARN, "kw_empty", "Нема пошукових запитів")]
    if len(kws) < KW_MIN:
        out.append((WARN, "kw_few", f"Запитів {len(kws)}<{KW_MIN} (ПРАВИЛА §10)"))
    if len(kws) > KW_MAX:
        out.append((WARN, "kw_many", f"Запитів {len(kws)}>{KW_MAX} (ПРАВИЛА §10)"))
    low = [str(k).lower() for k in kws]
    # Кожна фраза перевіряється ОКРЕМО: рекламне слово шкодить будь-де, а
    # загальне — лише коли з нього складається вся фраза (див. rules.bad_words_in).
    bad = sorted({w for k in low for w in bad_words_in(k)})
    if bad:
        out.append((WARN, "kw_seo", "Заборонені слова в запитах: " + ", ".join(bad)))
    reg = sorted({r for r in _REGIONS for k in low if r in k})
    if reg:
        out.append((WARN, "kw_region", "Регіон у запитах: " + ", ".join(reg)))
    junk = [k for k in kws if "(" in str(k) or ")" in str(k) or len(str(k).strip()) < 3]
    if junk:
        out.append((WARN, "kw_junk", f"Сміттєві запити: {', '.join(str(j) for j in junk[:3])}"))
    if len(set(low)) != len(low):
        out.append((WARN, "kw_dup", "Є однакові запити"))
    art = str(article or "").strip().lower()
    if art and not any(art in k for k in low):
        out.append((WARN, "kw_no_art", "Каталожного номера нема в запитах"))
    return out


def validate_desc_length(desc):
    """ПРАВИЛА §3: 400-800 КОРИСНИХ символів, тобто без HTML-тегів."""
    text = _TAG.sub(" ", str(desc or ""))
    text = re.sub(r"\s+", " ", text).strip()
    n = len(text)
    if n < DESC_TEXT_MIN:
        return [(WARN, "desc_thin", f"Опис {n}<{DESC_TEXT_MIN} корисних символів (ПРАВИЛА §3)")]
    if n > DESC_TEXT_SOFT_MAX * 2:
        return [(WARN, "desc_fat", f"Опис {n} символів — удвічі більше за верхню межу {DESC_TEXT_SOFT_MAX}")]
    return []


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
    # Мета, ключовики й довжина опису перевіряються, ЛИШЕ якщо їх передали:
    # старі виклики validate_card() (і 132 тести) нічого не ламають.
    art = card.get("product_id") or ""
    if "meta_title" in card or "meta_desc" in card:
        for f in validate_meta(card.get("meta_title"), card.get("meta_desc"), art):
            flags.append(("meta",) + f)
    if "keywords" in card:
        for f in validate_keywords(card.get("keywords"), art):
            flags.append(("kw",) + f)
    if is_part and card.get("description"):
        for f in validate_desc_length(card.get("description")):
            flags.append(("desc",) + f)
    if not card.get("product_id"):
        flags.append(("req", CRITICAL, "id_empty", "Нема Ідентифікатор_товару"))
    if card.get("price") in (None, "", 0, "0"):
        flags.append(("req", WARN, "price_empty", "Ціна порожня/0"))
    elif not price_ok(card.get("price")):
        # Prom окремим рядком забороняє «технічні» ціни на кшталт 1 грн: такий
        # товар алгоритм маркетплейсу ховає як занижений за ціною.
        flags.append(("req", WARN, "price_tech",
                      f"«Технічна» ціна {card.get('price')} — Prom забороняє"))
    if not card.get("group_id"):
        flags.append(("req", WARN, "group_empty", "Нема групи"))
    # Наступні дві перевірки — лише якщо поля передали. Старі виклики
    # validate_card() від цього нічого не отримують і нічого не втрачають.
    for f in validate_gtin(card.get("gtin")):
        flags.append(("gtin",) + f)
    if "avail" in card:
        for f in validate_availability(card.get("avail"), card.get("days")):
            flags.append(("avail",) + f)
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
