# -*- coding: utf-8 -*-
"""Детермінований двигун картки Prom з фактів BM Parts за ПРАВИЛА_PROM.md:
назва, категорія(→groups), OEM+кроси, характеристики(+вага), 30+ ключовиків ua/ru,
HTML-опис, мета, GTIN. Ціна — з common.pricing (єдина тарифна сітка з репрайсером).
AI-шар (ai_layer) підсилює 10 текстових полів; без ключів — лишається детермінік."""
import html
import re

from common.bmparts_client import (cdn_url, clean_name, fitment_lines, oem_and_replacements,
                                   parse_details)
from common.pricing import final_price
from adding.ai_layer import ai_enrich, merge_ai
from adding.groups import map_group

SELLER = "Vision Dynamics, Київ"

SUPPLIERS = {
    "BMW": "1KXaDLqBsOAtX0MxUoX39jpia9boISxl1xUxPihhU77I",
    "PORSCHE": "1oVSVg1cBxGj-DA66c5_FoAtp6zOthdnF_xTY_ugez2g",
}

UA2RU = {
    "гальмівні": "тормозные", "гальмівний": "тормозной", "гальмівна": "тормозная", "колодки": "колодки",
    "диск": "диск", "диски": "диски", "передні": "передние", "передній": "передний", "передня": "передняя",
    "задні": "задние", "задній": "задний", "фільтр": "фильтр", "масляний": "масляный", "повітряний": "воздушный",
    "паливний": "топливный", "паливна": "топливная", "салону": "салона", "амортизатор": "амортизатор",
    "підшипник": "подшипник", "ремінь": "ремень", "насос": "насос", "радіатор": "радиатор",
    "свічка": "свеча", "свічки": "свечи", "важіль": "рычаг", "опора": "опора", "пильник": "пыльник",
    "комплект": "комплект", "зчеплення": "сцепление", "гумові": "резиновые", "килимки": "коврики",
    "килимок": "коврик", "система": "система", "трубка": "трубка", "гофра": "гофра",
    "проводки": "проводки", "багажника": "багажника", "насадка": "насадка", "глушника": "глушителя",
}


def ua2ru(t):
    def repl(m):
        w = m.group(0)
        r = UA2RU.get(w.lower())
        if not r:
            return w
        return r.capitalize() if w[:1].isupper() else r
    return re.sub(r"[А-Яа-яІіЇїЄєҐґ']+", repl, t or "")


def esc(s):
    return html.escape(str(s or ""))


PROM_UNITS = {"шт.", "шт", "т", "кг", "г", "куб.м", "л", "кв.м", "кв.см", "м", "км", "мм", "мл",
              "пара", "упаковка", "комплект", "набір", "рулон", "послуга", "см"}
_DROP_VAL = {"", "-", "–", "—", "n/a", "na", "нет", "немає", "none", "0", "0.0", "0,0"}
_DROP_NAME = ("країна реєстрації", "страна регистрац", "код виробник", "код производ",
              "штрих", "гарант", "артикул", "svhc")


def clean_details(product):
    """BM Parts details → чисті трійки (назва, одиниця, значення)."""
    out = []
    seen = set()
    for (n, u, v) in parse_details(product.get("details")):
        name = re.sub(r"[\s:]+$", "", str(n or "")).strip()
        name = re.sub(r"\s+\d+$", "", name).strip()
        val = str(v or "").strip()
        low = name.lower()
        if not name or any(s in low for s in _DROP_NAME):
            continue
        if val.lower() in _DROP_VAL:
            continue
        unit = u if u in PROM_UNITS else ""
        m = re.match(r"^([\d.,]+)\s+([^\d\s].*)$", val)
        if m:
            val = m.group(1).replace(",", ".")
            cand = m.group(2).strip().lower()
            if not unit and cand in PROM_UNITS:
                unit = cand
        if val.lower() in _DROP_VAL or low in seen:
            continue
        seen.add(low)
        out.append((name, unit, val))
    return out


# ---------- Назва / сумісність ----------
def _type_phrase(name):
    toks = []
    for w in (name or "").split():
        if re.match(r"^[A-Za-z0-9]", w):
            break
        toks.append(w)
        if len(toks) >= 3:
            break
    t = re.sub(r"[()]", " ", " ".join(toks))
    return re.sub(r"\s+", " ", t).strip()


def _car_tokens(name):
    return re.findall(r"[A-Za-z][A-Za-z0-9]+", name or "")


def _humanize_years(s):
    yr = lambda y: (1900 + int(y)) if int(y) >= 50 else (2000 + int(y))
    s = re.sub(r"\b(\d{2})-(\d{2})\b", lambda m: f"{yr(m.group(1))}-{yr(m.group(2))}", s or "")
    s = re.sub(r"\b(\d{2})-(?!\d)", lambda m: f"{yr(m.group(1))}+", s)
    return s


def _fit_from_name(name):
    if not name:
        return []
    m = re.search(r"[A-Za-z]", name)
    if not m:
        return []
    tail = re.sub(r"\s+", " ", _humanize_years(name[m.start():])).strip(" ,.")
    return [tail] if tail else []


def _fitment(product, name):
    brand = (product.get("brand") or "").strip().lower()
    fit = [f for f in fitment_lines(product) if f and f.strip().lower() != brand]
    return fit or _fit_from_name(name)


def _first_word(s):
    m = re.match(r"[A-Za-zА-Яа-яІіЇїЄєҐґ']+", s or "")
    return (m.group(0).lower() if m else "")


def _spaced_oem(a):
    d = re.sub(r"\D", "", str(a or ""))
    if len(d) == 11:
        return f"{d[:2]} {d[2:4]} {d[4]} {d[5:8]} {d[8:]}"
    return ""


def _name_for_prom(raw, art):
    n = clean_name(raw)
    n = re.sub(r"\s*\b\d{2}(\s+\d{2})?\s*$", "", n).strip()
    if art and art.lower() not in n.lower():
        n = f"{n} {art}"
    return clean_name(n)[:110]


# ---------- Опис (ПРАВИЛА §3a) ----------
def html_desc(product, lang):
    name = (product.get("name") or "").strip().rstrip(".")
    oem, repl = oem_and_replacements(product)
    details = clean_details(product)
    if lang == "ru":
        nm = ua2ru(name)
        L = {"q": "оригинальное качество для вашего авто",
             "fit": "Прямая замена изношенного узла, возвращает штатную работу.",
             "oem": "Оригинальный (OEM) номер", "rep": "Аналоги / замена", "ch": "Характеристики",
             "ship": "Отправка ежедневно по Украине. Гарантия соответствия.",
             "cta": "Не уверены, подойдёт ли именно на ваше авто? <strong>Мы подберём за вас</strong> — "
                    "напишите марку, модель, год и VIN-код."}
    else:
        nm = name
        L = {"q": "оригінальна якість для вашого авто",
             "fit": "Пряма заміна зношеного вузла, відновлює штатну роботу.",
             "oem": "Оригінальний (OEM) номер", "rep": "Аналоги / замінники", "ch": "Характеристики",
             "ship": "Відправка щодня по Україні. Гарантія відповідності.",
             "cta": "Не впевнені, чи підійде саме на ваше авто? <strong>Ми підберемо за вас</strong> — "
                    "напишіть марку, модель, рік і VIN-код."}
    p = []
    p.append(f"<p>\U0001F697 <strong>{esc(nm)}</strong> — {L['q']}.</p>")
    p.append(f"<p>✅ {L['fit']}</p>")
    fitc = _fitment(product, name)
    if fitc:
        lab = "Подходит на" if lang == "ru" else "Підходить на"
        p.append(f"<p>\U0001F50E <strong>{lab}:</strong> {esc(', '.join(fitc))}.</p>")
    if oem:
        p.append(f"<p>\U0001F527 <strong>{L['oem']}:</strong> {esc(', '.join(oem))}.</p>")
    if repl:
        p.append(f"<p>\U0001F501 <strong>{L['rep']}:</strong> {esc(', '.join(repl[:12]))}.</p>")
    if details:
        lis = "".join(f"<li>{esc(ua2ru(n) if lang == 'ru' else n)}: {esc(v)}{(' ' + esc(u)) if u else ''}</li>"
                      for (n, u, v) in details[:8])
        p.append(f"<p>\U0001F4CB <strong>{L['ch']}:</strong></p><ul>{lis}</ul>")
    p.append(f"<p>\U0001F4E6 {L['ship']}</p>")
    p.append(f"<p>❓ {L['cta']}</p>")
    return "".join(p)


# ---------- Ключовики (ПРАВИЛА §4) ----------
TYPE_SYNONYMS = {
    "гофра": ["кожух проводки", "гофра кабельна"],
    "трубка": ["патрубок", "шланг"],
    "трубопровід": ["патрубок", "шланг"],
    "насадка": ["наконечник глушника"],
    "насадки": ["наконечники глушника"],
    "колодки": ["гальмівні колодки"],
    "фільтр": ["фильтр"],
    "амортизатор": ["стійка амортизатора"],
    "диск": ["гальмівний диск"],
    "емблема": ["шильдик", "логотип", "наклейка"],
    "літери": ["напис", "шильдик", "наклейка"],
    "килимки": ["коврики"],
    "радіатор": ["радіатор охолодження"],
}


def gen_keywords(product, lang):
    name = product.get("name") or ""
    brand = product.get("brand") or ""
    art = product.get("article") or ""
    oem, repl = oem_and_replacements(product)
    typ = _type_phrase(name)
    typ_l = ua2ru(typ) if lang == "ru" else typ
    cars = _car_tokens(name)
    carbrand = cars[0] if cars else brand
    models = [c for c in cars[1:]][:6]
    kws = []

    def add(*xs):
        for x in xs:
            x = re.sub(r"\s+", " ", str(x)).strip()
            if x and x.lower() not in [k.lower() for k in kws]:
                kws.append(x)

    add(typ_l)
    if typ_l and carbrand:
        add(f"{typ_l} {carbrand}")
    for syn in TYPE_SYNONYMS.get(_first_word(typ), []):
        s = ua2ru(syn) if lang == "ru" else syn
        add(s)
        if carbrand:
            add(f"{s} {carbrand}")
    if carbrand:
        add(carbrand, f"{carbrand} {art}")
    for m in models:
        add(f"{carbrand} {m}")
        if typ_l:
            add(f"{typ_l} {carbrand} {m}")
    add(art)
    sp = _spaced_oem(art)
    if sp:
        add(sp)
    for o in oem[:5]:
        add(o)
    for r in repl[:5]:
        add(r.split()[-1] if r else r)
    orig = "оригинал" if lang == "ru" else "оригінал"
    zap = "запчасти" if lang == "ru" else "запчастини"
    if typ_l:
        add(f"{typ_l} {orig}")
    if carbrand:
        add(f"{zap} {carbrand}", f"{carbrand} {orig}")
    add("Київ" if lang != "ru" else "Киев", "Україна" if lang != "ru" else "Украина")
    return kws[:32]


# ---------- Мета ----------
def meta_title(product, lang):
    name = product.get("name") or ""
    art = product.get("article") or ""
    t = re.sub(r"\s+", " ", (ua2ru(name) if lang == "ru" else name)).strip()
    if art and art not in t:
        t = f"{t} {art}"
    tail = " купить Киев. Vision Dynamics" if lang == "ru" else " купити Київ. Vision Dynamics"
    return (t + tail)[:120]


def meta_desc(product, lang):
    name = product.get("name") or ""
    oem, _ = oem_and_replacements(product)
    base = ua2ru(name) if lang == "ru" else name
    o = (f" OEM {oem[0]}." if oem else "")
    tail = (" Оригинал и аналоги, отправка ежедневно по Украине. Vision Dynamics, Киев."
            if lang == "ru" else
            " Оригінал і аналоги, відправка щодня по Україні. Vision Dynamics, Київ.")
    return (base + o + tail)[:250]


def gtin_from(product):
    for b in (product.get("barcodes") or []):
        d = re.sub(r"\D", "", str(b))
        if len(d) in (8, 12, 13, 14):
            return d
    return ""


# ---------- Складання повного набору полів ----------
def build_fields(product):
    art = str(product.get("article") or "").strip()
    name_ua = _name_for_prom(product.get("name"), art)
    name_ru = _name_for_prom(ua2ru(product.get("name") or ""), art)
    imgs = [cdn_url(p) for p in (product.get("images") or [])]
    details = clean_details(product)
    w = product.get("weight")
    if w and not any(n.lower() in ("вага", "вес") for (n, _, _) in details):
        details = [("Вага", "кг", str(w).replace(",", "."))] + details
    price = final_price(product.get("price")) or ""
    gid, gname = map_group(product)
    f = {"Код_товару": art, "Ідентифікатор_товару": art,
         "Назва_позиції": name_ru or name_ua, "Назва_позиції_укр": name_ua,
         "Пошукові_запити": ", ".join(gen_keywords(product, "ru")),
         "Пошукові_запити_укр": ", ".join(gen_keywords(product, "ua")),
         "Опис": html_desc(product, "ru"), "Опис_укр": html_desc(product, "ua"),
         "HTML_заголовок": meta_title(product, "ru"), "HTML_заголовок_укр": meta_title(product, "ua"),
         "HTML_опис": meta_desc(product, "ru"), "HTML_опис_укр": meta_desc(product, "ua"),
         "Ціна": price, "Валюта": "UAH", "Одиниця_виміру": "шт.", "Наявність": "+",
         "Номер_групи": gid, "Назва_групи": gname,
         "Виробник": product.get("brand") or "", "Посилання_зображення": ", ".join(imgs)}
    if w:
        f["Вага,кг"] = str(w).replace(",", ".")
    gt = gtin_from(product)
    if gt:
        f["Код_маркування_(GTIN)"] = gt
    ai = ai_enrich(product, clean_details, _fitment)  # без ключа/помилка -> None -> детермінік
    if ai:
        merge_ai(f, ai)
    return f, name_ua, imgs, details, price


def supplier_articles(gc, supplier):
    """Унікальні артикули з прайс-книги постачальника (BMW/PORSCHE) — кандидати."""
    sid = SUPPLIERS.get(supplier.upper())
    if not sid:
        print(f"[src] невідомий постачальник {supplier}")
        return []
    out = []
    seen = set()
    try:
        ss = gc.open_by_key(sid)
    except Exception as e:
        print(f"[src] {supplier}: нема доступу {str(e)[:60]}")
        return []
    for ws in ss.worksheets():
        try:
            vals = ws.get_all_values()
        except Exception:
            continue
        for r in vals:
            a = (r[0] if r else "").strip()
            if not a or not re.search(r"\d", a) or len(a) < 4:
                continue
            u = a.upper()
            if u not in seen:
                seen.add(u)
                out.append(a)
    print(f"[src] {supplier}: {len(out)} унікальних артикулів")
    return out
