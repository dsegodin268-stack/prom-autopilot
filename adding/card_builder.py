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
from repricing.export_writer import avail_cell
from adding.ai_layer import ai_enrich, merge_ai
from adding.groups import map_group

SELLER = "Vision Dynamics, Київ"
CITY = "Київ"

# SUPPLIERS + supplier_articles() видалено 26.07: вони вміли дістати з прайсу лише
# артикули, без цін і наявності, і не мали жодного виклику. Прайси постачальників
# тепер читає adding/sources/supplier_book.py через той самий read_all_tabs(),
# що й нічний репрайсер, — отже правила наявності й «найдешевша перемагає» одні.

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


# _spaced_oem() видалено 26.07 за прямою вказівкою власника: номер BMW ніколи не
# пишеться через пробіли чи дефіси — ні в каталозі, ні в пошуку. Було
# «11 42 7 953 129», має бути «11427953129». Функція додавала розбитий варіант
# у ключові запити, тобто вчила Prom шукати те, чого ніхто не набирає.


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
    # Голі «Київ» і «Україна» прибрано 26.07: Prom зіставляє запит із ЦІЛОЮ
    # фразою зі списку, а не з окремими словами в різних фразах. Слово «Київ»
    # саме по собі не ловить нічого, зате з'їдає слот. Локальний запит ловиться
    # лише повною фразою — її й додаємо, і тільки одну.
    if typ_l and carbrand:
        add(f"{typ_l} {carbrand} {'Киев' if lang == 'ru' else CITY}")
    return kws[:32]


# ---------- Мета ----------
def meta_title(product, lang):
    """HTML-заголовок ≤120. Каталожний номер має бути в ньому ЗАВЖДИ.

    Було: (назва + номер + « купити Київ. Vision Dynamics»)[:120] — у довгих
    назв хвіст із назвою магазину виштовхував номер за межу зрізу, і позиція
    переставала знаходитись за каталожним номером. Тепер місце під номер
    резервується першим, а хвіст додається лише якщо він поміщається цілим."""
    name = product.get("name") or ""
    art = str(product.get("article") or "").strip()
    core = re.sub(r"\s+", " ", (ua2ru(name) if lang == "ru" else name)).strip()
    art_part = f" {art}" if art and art.lower() not in core.lower() else ""
    core = core[:120 - len(art_part)].strip()
    t = core + art_part
    tail = " купить Киев. Vision Dynamics" if lang == "ru" else " купити Київ. Vision Dynamics"
    return (t + tail) if len(t) + len(tail) <= 120 else t


def meta_desc(product, lang):
    """HTML-опис ≤250. OEM-номер так само не має зрізатися хвостом."""
    name = product.get("name") or ""
    oem, _ = oem_and_replacements(product)
    base = re.sub(r"\s+", " ", (ua2ru(name) if lang == "ru" else name)).strip()
    o = (f" OEM {oem[0]}." if oem else "")
    tail = (" Оригинал и аналоги, отправка ежедневно по Украине. Vision Dynamics, Киев."
            if lang == "ru" else
            " Оригінал і аналоги, відправка щодня по Україні. Vision Dynamics, Київ.")
    s = base[:250 - len(o)].strip() + o
    return (s + tail) if len(s) + len(tail) <= 250 else s


def gtin_from(product):
    for b in (product.get("barcodes") or []):
        d = re.sub(r"\D", "", str(b))
        if len(d) in (8, 12, 13, 14):
            return d
    return ""


# ---------- Кандидат -> формат BM Parts ----------
def product_from_candidate(c):
    """candidate() -> словник у формі product BM Parts.

    Увесь двигун картки написаний під формат BM Parts. Для позиції з прайсу
    постачальника дешевше і безпечніше привести кандидата до цього формату,
    ніж заводити другу гілку коду, яка неминуче розійдеться з першою."""
    prod = dict(c.get("bm_product") or {})
    prod.setdefault("article", c.get("article"))
    if not prod.get("name"):
        prod["name"] = c.get("name_src") or ""
    if not prod.get("brand"):
        prod["brand"] = c.get("brand") or ""
    if not prod.get("images") and c.get("photos"):
        prod["images"] = list(c["photos"])
    if not prod.get("oe") and c.get("oem"):
        prod["oe"] = [{"number": o, "is_oem": True} for o in c["oem"]]
    if not prod.get("cars") and c.get("fitment"):
        prod["cars"] = list(c["fitment"])
    if not prod.get("nodes") and c.get("group_hint"):
        prod["nodes"] = c["group_hint"]
    # ціна тут — СОБІВАРТІСТЬ того постачальника, у якого купуємо цю позицію
    prod["price"] = c.get("cost")
    return prod


# ---------- Складання повного набору полів ----------
def build_fields(product, cand=None, use_ai=True):
    """product (+ кандидат) -> усі поля картки Prom.

    cand потрібен для двох речей, які НЕ можна брати з каталогу BM Parts:
      • собівартість — від постачальника, у якого купуємо;
      • наявність і кількість — так само від нього, за тим самим правилом
        avail_cell(), що й у нічного репрайсера, інакше перший же нічний прогін
        перепише щойно додану картку і власник побачить стрибок.
    Раніше тут стояло жорстке «Наявність»: «+» — тобто кожна нова позиція
    оголошувалась наявною, навіть якщо вона під замовлення."""
    art = str(product.get("article") or (cand or {}).get("article") or "").strip()
    name_ua = _name_for_prom(product.get("name"), art)
    name_ru = _name_for_prom(ua2ru(product.get("name") or ""), art)
    imgs = [cdn_url(p) for p in (product.get("images") or [])]
    if not imgs and cand:
        imgs = [cdn_url(p) for p in (cand.get("photos") or [])]
    details = clean_details(product) or list((cand or {}).get("chars") or [])
    w = product.get("weight")
    if w and not any(n.lower() in ("вага", "вес") for (n, _, _) in details):
        details = [("Вага", "кг", str(w).replace(",", "."))] + details
    cost = (cand or {}).get("cost") if cand else product.get("price")
    price = final_price(cost) or ""
    qty = (cand or {}).get("qty") or 0
    days = (cand or {}).get("days") if cand else 0
    if cand and cand.get("presence") != "available":
        qty = 0
    avail, qty_cell = avail_cell(qty, days if cand else 15)
    gid, gname = map_group(product)
    f = {"Код_товару": art, "Ідентифікатор_товару": art,
         "Назва_позиції": name_ru or name_ua, "Назва_позиції_укр": name_ua,
         "Пошукові_запити": ", ".join(gen_keywords(product, "ru")),
         "Пошукові_запити_укр": ", ".join(gen_keywords(product, "ua")),
         "Опис": html_desc(product, "ru"), "Опис_укр": html_desc(product, "ua"),
         "HTML_заголовок": meta_title(product, "ru"), "HTML_заголовок_укр": meta_title(product, "ua"),
         "HTML_опис": meta_desc(product, "ru"), "HTML_опис_укр": meta_desc(product, "ua"),
         "Ціна": price, "Валюта": "UAH", "Одиниця_виміру": "шт.",
         "Наявність": avail, "Кількість": qty_cell,
         "Номер_групи": gid, "Назва_групи": gname,
         "Виробник": product.get("brand") or (cand or {}).get("brand") or "",
         "Посилання_зображення": ", ".join(imgs)}
    if w:
        f["Вага,кг"] = str(w).replace(",", ".")
    gt = gtin_from(product)
    if gt:
        f["Код_маркування_(GTIN)"] = gt
    if use_ai:
        # thin=True — позиції, якої нема в каталозі BM Parts: фактів обмаль,
        # тому профіль ШІ прямо забороняє вигадувати кузови, двигуни й роки
        thin = bool(cand) and not cand.get("matched_bm")
        ai = ai_enrich(product, clean_details, _fitment, thin=thin)  # без ключа -> None -> детермінік
        if ai:
            merge_ai(f, ai)
    return f, name_ua, imgs, details, price
