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
# «артикул» і «гарант» прибрано зі списку викидання 27.07: ПРАВИЛА §5 перелічують
# «Артикул» і «Гарантія» серед ОБОВ'ЯЗКОВИХ характеристик, а цей фільтр їх мовчки
# зрізав — картка їхала в Prom без двох обов'язкових полів. «Код виробника» та
# штрихкод лишаються у викиданні: перший дублює артикул, другий іде окремим
# полем GTIN.
_DROP_NAME = ("країна реєстрації", "страна регистрац", "код виробник", "код производ",
              "штрих", "svhc")


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
    """Коди кузовів/двигунів із назви: G20, B48, X3...

    (?<![A-Za-z0-9]) — 27.07. Без цього погляду назад регулярка виловлювала «x36»
    усередині розміру диска «348x36» і видавала ключовик «BMW x36», якого не існує.
    Токен зараховується, лише якщо перед латинською літерою НЕ стоїть буква чи цифра."""
    return re.findall(r"(?<![A-Za-z0-9])[A-Za-z][A-Za-z0-9]+", name or "")


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
    """Рядки сумісності. Роки олюднюються ЗАВЖДИ.

    27.07: _humanize_years() стояв тільки в запасній гілці _fit_from_name(), тому
    сумісність із каталогу BM Parts їхала в опис як «BMW 3 G20 B48 18-» замість
    «BMW 3 G20 B48 2018+». Покупець читає роки, а не скорочення постачальника."""
    brand = (product.get("brand") or "").strip().lower()
    fit = [_humanize_years(f) for f in fitment_lines(product)
           if f and f.strip().lower() != brand]
    return fit or _fit_from_name(name)


def _first_word(s):
    m = re.match(r"[A-Za-zА-Яа-яІіЇїЄєҐґ']+", s or "")
    return (m.group(0).lower() if m else "")


# _spaced_oem() видалено 26.07 за прямою вказівкою власника: номер BMW ніколи не
# пишеться через пробіли чи дефіси — ні в каталозі, ні в пошуку. Було
# «11 42 7 953 129», має бути «11427953129». Функція додавала розбитий варіант
# у ключові запити, тобто вчила Prom шукати те, чого ніхто не набирає.


def _display_name(raw):
    """Чиста назва без хвоста-скорочення постачальника («... 348x36 18-» → «... 348x36»).

    27.07: раніше це чищення жило всередині _name_for_prom(), тому чисту назву
    бачила лише колонка «Назва_позиції», а опис, мета-заголовок і мета-опис
    брали СИРУ назву з висячим «11-». Один товар мав три різні написання
    заголовка в одній картці. Тепер усі чотири місця беруть один рядок."""
    n = clean_name(raw)
    return re.sub(r"\s*\b\d{2}\s*-?\s*(\d{2})?\s*$", "", n).strip()


def _name_for_prom(raw, art):
    n = _display_name(raw)
    if art and art.lower() not in n.lower():
        n = f"{n} {art}"
    return clean_name(n)[:110]


# ---------- Опис (ПРАВИЛА §3a) ----------
def html_desc(product, lang):
    name = _display_name(product.get("name")).rstrip(".")
    oem, repl = oem_and_replacements(product)
    details = clean_details(product)
    if lang == "ru":
        nm = ua2ru(name)
        L = {"q": "оригинальное качество для вашего авто",
             "fit": "Прямая замена изношенного узла, возвращает штатную работу.",
             "oem": "Оригинальный (OEM) номер", "art": "Каталожный номер",
             "rep": "Аналоги / замена", "ch": "Характеристики",
             "ship": "Отправка ежедневно по Украине. Гарантия соответствия.",
             "cta": "Не уверены, подойдёт ли именно на ваше авто? <strong>Мы подберём за вас</strong> — "
                    "напишите марку, модель, год и VIN-код."}
    else:
        nm = name
        L = {"q": "оригінальна якість для вашого авто",
             "fit": "Пряма заміна зношеного вузла, відновлює штатну роботу.",
             "oem": "Оригінальний (OEM) номер", "art": "Каталожний номер",
             "rep": "Аналоги / замінники", "ch": "Характеристики",
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
    else:
        # 27.07. Позиція з прайсу, якої нема в довіднику BM Parts, не має жодного
        # OEM — і в описі не лишалось ЖОДНОГО номера. Головне правило власника:
        # покупець мусить знайти позицію за каталожним номером, а Google індексує
        # саме текст опису. Артикул тут — і є той номер, іншого в нас нема.
        art = re.sub(r"\s+", "", str(product.get("article") or ""))
        if art:
            p.append(f"<p>\U0001F527 <strong>{L['art']}:</strong> {esc(art)}.</p>")
    if repl:
        p.append(f"<p>\U0001F501 <strong>{L['rep']}:</strong> {esc(', '.join(repl[:12]))}.</p>")
    # [:4], а не [:8] — 27.07. ПРАВИЛА §3: опис НЕ дублює блок характеристик Prom
    # (той самий набір уже стоїть у колонках Назва/Одиниця/Значення), дозволено
    # лише 2-4 підсумкові пункти. Раніше сюди виводилось до 8 рядків — покупець
    # бачив однакову таблицю двічі, а Google рахував це за дубль контенту.
    if details:
        lis = "".join(f"<li>{esc(ua2ru(n) if lang == 'ru' else n)}: {esc(v)}{(' ' + esc(u)) if u else ''}</li>"
                      for (n, u, v) in details[:4])
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


_KW_BAD = ("купити", "купить", "продати", "оптом", "замовити", "заказать",
           "недорого", "дешево", "запчастини", "запчасти")


def _part_token(s):
    """Каталожний номер із рядка замінника.

    27.07. Було `r.split()[-1]`: рядок «11427854445 (BMW)» перетворювався на
    ключовик «(BMW)» — сміття, яке ніхто не шукає, а справжній альтернативний
    номер 11427854445 у список не потрапляв узагалі. Тепер дужки зрізаються,
    а з решти береться токен із цифрами — саме він і є номером
    («MANN HU6004X» → HU6004X, «11427854445 (BMW)» → 11427854445)."""
    s = re.sub(r"\([^)]*\)", " ", str(s or ""))
    toks = [t.strip(".,;") for t in s.split() if t.strip(".,;")]
    nums = [t for t in toks if any(ch.isdigit() for ch in t)]
    return (nums[-1] if nums else (toks[-1] if toks else ""))


def _kw_ok(k):
    """Останній фільтр ключовиків: без заборонених слів і без сміття.

    27.07 додано відсів ОДНОГО СЛОВА БЕЗ ЦИФР. Prom шукає збіг усередині однієї
    фрази, тому ключовик «BMW» означає «показуй мою картку на кожен запит зі
    словом BMW»: покупець, який шукає диски, бачить фільтр і йде геть, а сама
    деталь від цього не знаходиться жодного разу. Те саме з голим «фильтр».
    Цифри — свідомий виняток: «11427953129» теж одне слово, але це каталожний
    номер, за яким позицію мусить знаходити пошук. Це пряма вимога власника і
    вона важливіша за правило про цілі фрази."""
    k = (k or "").strip()
    if len(k) < 3 or "(" in k or ")" in k:
        return False
    if len(k.split()) == 1 and not re.search(r"\d", k):
        return False
    low = k.lower()
    return not any(b in low for b in _KW_BAD)


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
    if typ_l and art:
        add(f"{typ_l} {art}")
    for o in oem[:5]:
        add(o)
        if typ_l:
            add(f"{typ_l} {o}")
    for r in repl[:5]:
        add(_part_token(r))
    orig = "оригинал" if lang == "ru" else "оригінал"
    if typ_l:
        add(f"{typ_l} {orig}")
        if carbrand:
            add(f"{carbrand} {typ_l}")
    if carbrand:
        add(f"{carbrand} {orig}")
    # 27.07 прибрано два ключовики, які прямо порушували ПРАВИЛА §2:
    #   «запчастини {бренд}» — §2 забороняє загальні слова («запчастини», «авто»):
    #      за таким запитом магазин конкурує з усім ринком і не виграє нічого;
    #   «{тип} {бренд} Київ» — §2 забороняє регіони в пошукових запитах, а §0-bis
    #      окремо каже не тягнути міста з чужих карток у нашу мету.
    # Замість них додано реальні фрази з артикулом і OEM — їх справді набирають.
    return [k for k in kws if _kw_ok(k)][:40]


# ---------- Мета ----------
META_TITLE_MAX = 70   # ПРАВИЛА §4/§10: Google ріже сніпет приблизно тут
META_DESC_MAX = 160   # ПРАВИЛА §4/§10


def _trim(s, limit):
    """Обрізає до limit, але по межі слова — щоб не лишався огризок."""
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    if len(s) <= limit:
        return s
    cut = s[:limit]
    sp = cut.rfind(" ")
    return (cut[:sp] if sp > limit * 0.6 else cut).strip(" ,.-")


def meta_title(product, lang):
    """HTML-заголовок ≤70. Каталожний номер має бути в ньому ЗАВЖДИ.

    27.07, дві правки:
      • ліміт 120 → 70. §4 і чекліст §10 вимагають ≤70, а код мовчки пускав
        заголовки на 91-96 символів — Google обрізав їх на видачі.
      • прибрано хвіст « купити Київ. Vision Dynamics». §0-bis прямо каже, що
        міста і слово «купити» зі знімків чужих карток — заборонені правилами
        і НЕ копіюються в нашу мету. Хвіст стояв у КОЖНІЙ картці.
    Місце під номер резервується першим: у довгих назв саме він вилітав за межу
    зрізу, і позиція переставала знаходитись за каталожним номером."""
    name = _display_name(product.get("name"))
    art = str(product.get("article") or "").strip()
    core = re.sub(r"\s+", " ", (ua2ru(name) if lang == "ru" else name)).strip()
    art_part = f" {art}" if art and art.lower() not in core.lower() else ""
    return (_trim(core, META_TITLE_MAX - len(art_part)) + art_part).strip()


def meta_desc(product, lang):
    """HTML-опис ≤160 (було 250). Каталожний номер — обов'язково.

    Було: якщо в товару нема жодного OEM (позиція з прайсу, якої нема в довіднику),
    у мета-опис не потрапляв ЖОДЕН номер — §0 вимагає протилежного. Тепер за
    відсутності OEM береться артикул. Місто з хвоста прибрано (§0-bis)."""
    name = _display_name(product.get("name"))
    art = str(product.get("article") or "").strip()
    oem, _ = oem_and_replacements(product)
    base = re.sub(r"\s+", " ", (ua2ru(name) if lang == "ru" else name)).strip()
    num = (oem[0] if oem else art)
    o = (f" OEM {num}." if num else "")
    tail = (" Оригинал и аналоги, отправка ежедневно по Украине."
            if lang == "ru" else
            " Оригінал і аналоги, відправка щодня по Україні.")
    s = _trim(base, META_DESC_MAX - len(o)) + o
    return (s + tail) if len(s) + len(tail) <= META_DESC_MAX else s


def enforce_limits(f, art=""):
    """Єдиний шлюз жорстких меж Prom/Google. Працює і для детермініка, і для ШІ.

    Що робить:
      • мета-заголовок ≤70, мета-опис ≤160 (§4, §10);
      • каталожний номер присутній в обох мета-полях (§0);
      • ключовики: без заборонених слів і сміття, не більше 40 (§2, §10).
    Нічого не «покращує» — лише не пускає за межі. Оцінку якості робить
    валідатор (adding/validator.py), а не цей шлюз."""
    art = str(art or "").strip()
    for k, limit in (("HTML_заголовок", META_TITLE_MAX), ("HTML_заголовок_укр", META_TITLE_MAX),
                     ("HTML_опис", META_DESC_MAX), ("HTML_опис_укр", META_DESC_MAX)):
        v = str(f.get(k) or "")
        if not v:
            continue
        if art and art.lower() not in v.lower():
            v = f"{_trim(v, limit - len(art) - 1)} {art}"
        f[k] = _trim(v, limit)
    for k in ("Пошукові_запити", "Пошукові_запити_укр"):
        v = str(f.get(k) or "")
        if not v:
            continue
        kws, seen = [], set()
        for x in v.split(","):
            x = re.sub(r"\s+", " ", x).strip()
            if _kw_ok(x) and x.lower() not in seen:
                seen.add(x.lower())
                kws.append(x)
        f[k] = ", ".join(kws[:40])
    return f


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
    # Жорсткі межі ставляться ПІСЛЯ ШІ, а не до нього. Раніше текст від провайдера
    # їхав у Export як є: мета-заголовок на 200 символів чи «купити» в ключовиках
    # ніхто не ловив, бо детермінований генератор таких не робить, а перевірка
    # стояла до злиття. Тепер один і той самий шлюз проходять обидва джерела тексту.
    enforce_limits(f, art)
    return f, name_ua, imgs, details, price
