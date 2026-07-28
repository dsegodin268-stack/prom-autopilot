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
from adding.ai_layer import ai_enrich, card_facts, merge_ai, repair_fields, repair_on
from adding import canon
from adding.groups import map_place
# Жорсткі межі Prom і Google лежать РІВНО В ОДНОМУ місці — adding/rules.py.
# Доти кожне число було записане тричі: тут (шлюз), у валідаторі й руками в
# промпті аудиту. Три копії одного числа розходяться завжди, і розходились:
# шлюз різав мету по 70, валідатор мовчав про слова, промпт називав третє число.
from adding.rules import (GTIN_LENGTHS, KW_MAX, NAME_MAX, PROM_UNITS as RULES_UNITS,
                          bad_words_in, gtin_valid)
from adding.rules import META_DESC_MAX as RULES_META_DESC_MAX
from adding.rules import META_TITLE_MAX as RULES_META_TITLE_MAX

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


# 27.07. Словник вище — це 40 слів у НАЗИВНОМУ відмінку, а назви позицій пишуть
# у будь-якому: «Пильник амортизатора (переднього)». Слово «переднього» у
# словнику відсутнє, тому воно проходило крізь перекладач недоторканим, і
# російська назва виходила напівукраїнською: «Пыльник амортизатора
# (переднього)». Prom таку назву приймає, а покупець читає її як помилку — і
# російськомовний пошук по ній не спрацьовує.
#
# Тому два додаткові шари. Перший — КОРЕНІ: беремо найдовший збіг на початку
# слова й міняємо тільки його, закінчення лишається. Другий — ЗАКІНЧЕННЯ: список
# упорядкований, перемагає перший збіг, тому довші пари стоять вище коротших
# («ього» мусить спрацювати раніше за «ого»).
UA2RU_STEM = {
    "гальмівн": "тормозн", "гальм": "тормоз", "передн": "передн", "задн": "задн",
    "фільтр": "фильтр", "маслян": "маслян", "повітрян": "воздушн",
    "паливн": "топливн", "пильник": "пыльник", "пильн": "пыльн",
    "амортизатор": "амортизатор", "підшипник": "подшипник", "ремін": "ремен",
    "рем'ян": "ремен", "радіатор": "радиатор", "свічк": "свеч", "важіл": "рычаг",
    "важел": "рычаг", "стійк": "стойк", "опор": "опор", "зчеплен": "сцеплен",
    "гумов": "резинов", "килимк": "коврик", "килимок": "коврик",
    "глушник": "глушител", "глушител": "глушител",
    "прокладк": "прокладк", "колектор": "коллектор", "впускн": "впускн",
    "випускн": "выпускн", "охолодж": "охлажд", "зчіпн": "сцепн",
    "кермов": "рулев", "кульов": "шаров", "сайлентблок": "сайлентблок",
    "накладк": "накладк", "датчик": "датчик", "лямбд": "лямбд",
    "насадк": "насадк", "багажник": "багажник", "двигун": "двигател",
    "коробк": "коробк", "поворот": "поворот", "щітк": "щетк",
    "склоочисник": "стеклоочистител", "лобов": "лобов", "капот": "капот",
    "бампер": "бампер", "фар": "фар", "ліхтар": "фонар", "решітк": "решетк",
    "крил": "крыл", "двер": "двер", "замок": "замок", "троса": "троса",
    "трос": "трос", "шланг": "шланг", "патрубок": "патрубок",
    "хомут": "хомут", "болт": "болт", "гайк": "гайк", "шайб": "шайб",
    "втулк": "втулк", "сальник": "сальник", "маховик": "маховик",
    "генератор": "генератор", "стартер": "стартер", "акумулятор": "аккумулятор",
    "помп": "помп", "термостат": "термостат", "компресор": "компрессор",
    "турбін": "турбин", "інтеркулер": "интеркулер", "форсунк": "форсунк",
    "каталізатор": "катализатор", "резонатор": "резонатор", "труб": "труб",
    "гофр": "гофр", "комплект": "комплект", "набір": "набор",
    "стабілізатор": "стабилизатор", "підвіск": "подвеск", "ричаг": "рычаг",
    "маточин": "ступиц", "гальмо": "тормоз", "циліндр": "цилиндр",
    "суппорт": "суппорт", "супорт": "суппорт", "шків": "шкив",
    "натягувач": "натяжител", "ролик": "ролик", "ланцюг": "цеп",
    "розподільн": "распределительн", "колінчаст": "коленчат", "вал": "вал",
    "поршн": "поршн", "кільц": "кольц", "клапан": "клапан", "головк": "головк",
    "блок": "блок", "піддон": "поддон", "кришк": "крышк", "корпус": "корпус",
    "кріплен": "креплен", "підкрилок": "подкрылок", "захист": "защит",
    "дзеркал": "зеркал", "скло": "стекл", "склян": "стеклян",
    "омивач": "омыват", "бачок": "бачок", "жиклер": "жиклер",
    "провід": "провод", "проводк": "проводк", "запалюван": "зажиган",
    "котушк": "катушк", "реле": "реле", "запобіжник": "предохранител",
    "лампа": "лампа", "лампочк": "лампочк", "сигнал": "сигнал",
    "нижн": "нижн", "верхн": "верхн", "прав": "прав", "лів": "лев",
    "внутрішн": "внутренн", "зовнішн": "наружн", "салон": "салон",
    "кабін": "кабин", "мотор": "мотор", "вентилятор": "вентилятор",
    "пічк": "печк", "кондиціонер": "кондиционер", "осушувач": "осушител",
}

# Закінчення. Порядок має значення: перший збіг виграє, тому довші пари стоять
# вище коротших — інакше «ього» ніколи б не спрацювало через «ого».
_UA2RU_END = (
    ("ього", "его"), ("ьому", "ему"), ("ння", "ние"),
    ("ної", "ной"), ("ною", "ной"), ("ними", "ными"), ("ими", "ыми"),
    ("ів", "ов"), ("ий", "ый"), ("ій", "ий"), ("ім", "ем"),
    ("іх", "их"), ("их", "ых"), ("ої", "ой"), ("ою", "ой"),
    ("і", "ые"), ("ї", "и"),
)

# М'які основи російських прикметників: у них «ий» лишається «ий»
# (передний, задний, нижний), тверде «ый» тут — помилка.
_SOFT_RU = {"передн", "задн", "нижн", "верхн", "внутренн", "средн", "дальн"}

# Основи, у яких порожнє закінчення означає м'який знак: «глушник» -> не
# «глушител», а «глушитель».
_SOFT_END = ("тел", "ател", "ител")

# Ознаки того, що слово лишилось українським: літери, яких у російській нема,
# або характерні українські закінчення.
_UA_MARK = re.compile(r"[іїєґІЇЄҐ]|ього\b|ьої\b|ння\b")


def _stem_ru(low):
    """Найдовший корінь зі словника, що починає слово. '' якщо збігу нема."""
    best = ""
    for st in UA2RU_STEM:
        if low.startswith(st) and len(st) > len(best):
            best = st
    return best


def _word_ru(w):
    """Одне слово укр -> рос. Повертає None, якщо перекласти не вдалось."""
    low = w.lower()
    exact = UA2RU.get(low)
    if exact:
        return exact
    st = _stem_ru(low)
    if not st:
        return None
    ru_st = UA2RU_STEM[st]
    tail = low[len(st):]
    if not tail:
        # «глушник» -> «глушитель», а не «глушител»
        return ru_st + "ь" if ru_st.endswith(_SOFT_END) else ru_st
    if ru_st in _SOFT_RU and tail in ("я", "є", "е"):
        return ru_st + "яя" if tail == "я" else ru_st + "ее"   # задня -> задняя
    for ua, ru in _UA2RU_END:
        if not tail.endswith(ua):
            continue
        if ua == "ий" and ru_st in _SOFT_RU:
            break                      # передний, а не передный
        tail = tail[:-len(ua)] + ru
        break
    return ru_st + tail


def ua2ru(t):
    """Українська назва -> російська. Якщо переклад вийшов НЕПОВНИМ — повертаємо
    оригінал.

    Причина правила «або все, або нічого»: чиста українська назва — нормальний
    товарний вигляд, а суміш («Пыльник амортизатора (переднього)») виглядає як
    недогляд і ламає російськомовний пошук. Краще лишити як було."""
    src = t or ""

    def repl(m):
        w = m.group(0)
        r = _word_ru(w)
        if not r:
            return w
        return r.capitalize() if w[:1].isupper() else r

    out = re.sub(r"[А-Яа-яІіЇїЄєҐґ']+", repl, src)
    if out != src and _UA_MARK.search(out):
        return src
    return out


def esc(s):
    return html.escape(str(s or ""))


# Список одиниць — з adding/rules.py. Тут лежала СКОРОЧЕНА копія того самого
# списку, що у валідаторі: шлюз вважав одиницю невідомою і мовчки зрізав її
# («година», «доба», «кВт», «лист»), а валідатор ту саму одиницю знав і теж
# мовчав. Дві копії одного списку розходяться завжди.
PROM_UNITS = RULES_UNITS
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
    return clean_name(n)[:NAME_MAX]


# ---------- Характеристики за каноном (adding/canon.py) ----------
# Досі в картку їхали ЛИШЕ характеристики з details BM Parts — тобто те, що
# постачальник поклав у свій каталог. Але Prom має ВЛАСНИЙ обов'язковий набір, і
# головна в ньому — «Код запчастини»: саме вона чіпляє позицію до крос-довідника
# маркетплейсу, після чого Prom САМ малює блоки «Сумісний транспорт» і
# «Оригінальні номери». Без неї покупець не знаходить позицію за каталожним
# номером ніде, крім тексту опису, — а це і був головний закид власника.
#
# Значення тут не вигадуються: марка, моделі, роки й кроси беруться з фактів
# BM Parts, а назви характеристик і їхній порядок — з canon.py, зчитаного з
# бойової таблиці. Чого нема у фактах — лишається порожнім, і canon.order_chars()
# такий блок просто викидає.

_YEAR_RE = re.compile(r"(?:19|20)\d{2}")
_RANGE_RE = re.compile(r"((?:19|20)\d{2})\s*[-–—]\s*((?:19|20)\d{2})")
_YEARS_MAX = 20

# Місце встановлення — з назви позиції. Стем, а не ціле слово: «передний»,
# «передній», «передня», «передние» — це одне й те саме місце.
_PLACES = (("передн", "Передній"), ("задн", "Задній"),
           ("лів", "Лівий"), ("лев", "Лівий"), ("прав", "Правий"),
           ("верхн", "Верхній"), ("нижн", "Нижній"))

# Марки АВТО (не брендів деталей). Потрібні рівно для одного рішення:
# «Тип запчастини» = Оригінал чи Аналог. Febi чи MANN — теж бренд, але деталь
# їхнього виробництва оригіналом не є, і писати покупцю протилежне не можна.
_CAR_MAKES = frozenset((
    "bmw", "bmw motorrad", "mini", "audi", "volkswagen", "vw", "vag",
    "mercedes-benz", "mercedes", "porsche", "porshe", "porcher",
    "land rover", "jaguar", "lexus", "toyota", "volvo", "skoda", "seat",
))


def _solid(s):
    """Каталожний номер СУЦІЛЬНО: 11427953129, а не «11 42 7 953 129».

    Пряма вимога власника і водночас технічна: з пробілами крос-довідник Prom
    номер не впізнає, а Google не склеює його з тим, що набирає покупець."""
    return re.sub(r"[\s\-–—]+", "", str(s or "")).strip()


# Ряд цифр, розбитий пробілами, у ВІЛЬНОМУ тексті: «31 30 6 791 712».
# Три групи й не менше 7 цифр — щоб під правило не потрапили роки («2011 2019»
# — дві групи) і взагалі будь-яка пара чисел поруч.
_NUM_RUN = re.compile(r"(?<![\w.,])\d+(?: \d+){2,}(?![\w])(?![.,]\d)")


def _solid_nums(s):
    """Те саме, що _solid(), але всередині довільного тексту: збиває докупи
    лише ряди цифр, розділені пробілами, і не чіпає ні бренд, ні решту рядка.

    «Оригінальний (OEM) номер: 31 30 6 791 712.» -> «…: 31306791712.»"""
    def _join(m):
        t = m.group(0)
        return t.replace(" ", "") if len(re.sub(r"\D", "", t)) >= 7 else t
    return _NUM_RUN.sub(_join, str(s or ""))


def _oem_repl(product):
    """oem_and_replacements(), але номери вже в канонічному вигляді.

    BM Parts віддає OEM BMW у «людському» записі — «31 30 6 791 712». У картку
    він мусить іти суцільно: з пробілами крос-довідник Prom номер не впізнає, а
    Google не склеює його з тим, що набирає покупець. Поки чистка стояла лише в
    _cross() і в MPN, той самий номер їхав у трьох полях РІЗНИМ: в описі — з
    пробілами, у ключовиках — обидва варіанти (другий просто займав слот), а в
    мета-опис робочий номер не потрапляв узагалі, і його дописували ворота
    enforce_limits(). Тому чистимо ОДИН раз тут, а не в п'яти місцях по-різному."""
    oem, repl = oem_and_replacements(product)
    out, seen = [], set()
    for o in oem or ():
        s = _solid(o)
        if s and s.upper() not in seen:
            seen.add(s.upper())
            out.append(s)
    return out, [_solid_nums(r) for r in (repl or ())]


def _fit_brand(product, cand, fits):
    """Марка АВТО для «Сумісність з маркою».

    Це не те саме, що «Виробник»: там бренд деталі. Марку авто дає перший токен
    рядка сумісності («BMW 3 G20 B48 2018+»), бо cars[] у BM Parts складається
    саме в такому порядку; якщо сумісності нема — латинський токен із назви."""
    for line in fits:
        w = str(line or "").split()
        if w and re.match(r"^[A-Za-z]", w[0]):
            return w[0]
    cars = _car_tokens(_display_name(product.get("name")))
    if cars:
        return cars[0]
    return str(product.get("brand") or (cand or {}).get("brand") or "").strip()


def _model_of(line, brand):
    """«BMW 3 G20 B48 2018+» -> «3 G20». Модель плюс код кузова, якщо він поряд.

    Далі не беремо свідомо: наступний токен — це вже код двигуна (B48), і в
    полі «Сумісність з моделлю» він робить значення, за яким ніхто не фільтрує."""
    w = [x for x in re.sub(r"\s+", " ", str(line or "")).strip().split() if x]
    if w and brand and w[0].lower() == str(brand).lower():
        w = w[1:]
    w = [x for x in w if not _YEAR_RE.search(x) and x != "+"]
    if not w:
        return ""
    model = w[0]
    if len(w) > 1 and re.match(r"^[A-Za-z]\d{2,3}$", w[1]):
        model = f"{model} {w[1]}"
    return model.strip(" ,.-")


def _models(fits, brand):
    return [m for m in (_model_of(l, brand) for l in fits) if m]


def _years(fits):
    """Роки випуску списком: «2010-2015» -> 2010|2011|…|2015.

    Фасетний фільтр Prom шукає КОНКРЕТНИЙ рік, тому діапазон розкривається.
    Відкритий діапазон («2018+») лишається однією позначкою: домальовувати йому
    кінець означало б написати покупцю рік, якого ми не знаємо."""
    out = []
    for line in fits:
        s = str(line or "")
        used = []
        for m in _RANGE_RE.finditer(s):
            a, b = int(m.group(1)), int(m.group(2))
            if 0 <= b - a <= _YEARS_MAX:
                out += [str(y) for y in range(a, b + 1)]
                used.append(m.group(0))
        for u in used:
            s = s.replace(u, " ")
        out += _YEAR_RE.findall(s)
    return out[:_YEARS_MAX * 2]


def _places(name):
    low = str(name or "").lower()
    out = []
    for stem, val in _PLACES:
        if stem in low and val not in out:
            out.append(val)
    return out


def _cross(oem, repl, art):
    """Кросс-номери: OEM + номери замінників, БЕЗ власного артикула.

    Свій же номер у списку крос-номерів — це «ця деталь замінюється сама на
    себе»: Prom показує його покупцю в блоці аналогів і картка виглядає
    зламаною. Роздільник тут «;», а не «|», — у Prom вони різні."""
    a = _solid(art)
    out = []
    for v in list(oem or []) + [_part_token(r) for r in (repl or [])]:
        s = _solid(v)
        if s and s.upper() != a.upper():
            out.append(s)
    return out[:20]


def _is_original(product, art, oem, brand_fit):
    """Оригінал чи аналог. Помилка тут коштує дорого в обидва боки: назвати
    аналог оригіналом — обман покупця, назвати оригінал BMW аналогом —
    втрачений продаж, бо саме за словом «оригінал» його й шукають."""
    a = _solid(art)
    if a and any(_solid(o).upper() == a.upper() for o in (oem or [])):
        return True
    b = str(product.get("brand") or "").strip().lower()
    return bool(b) and (b in _CAR_MAKES or b == str(brand_fit or "").strip().lower())


def canon_chars(product, cand=None, details=None):
    """Повний канонічний набір характеристик картки автозапчастини.

    Спершу канонічні блоки Prom, потім характеристики постачальника. Порядок
    робить canon.order_chars(): він же схлопує дублі (перший виграє, тобто наш
    канонічний блок б'є однойменний блок BM Parts), викидає порожні значення й
    ріже хвіст до 29 блоків — стільки їх у бойовій шапці, решту
    common/prom_format.write_chars відкидає МОВЧКИ."""
    art = _solid(product.get("article") or (cand or {}).get("article"))
    name = _display_name(product.get("name"))
    fits = _fitment(product, name)
    brand_fit = _fit_brand(product, cand, fits)
    oem, repl = _oem_repl(product)
    ch = [
        (canon.CH_STATE, "", canon.VAL_STATE_NEW),
        (canon.CH_BRAND_FIT, "", brand_fit),
        (canon.CH_MODEL_FIT, "", canon.join_multi(_models(fits, brand_fit))),
        (canon.CH_YEARS, "", canon.join_multi(_years(fits))),
        (canon.CH_PART_TYPE, "", canon.part_type_value(
            _is_original(product, art, oem, brand_fit))),
        (canon.CH_PART_CODE, "", art),
        (canon.CH_CROSS, "", canon.join_cross(_cross(oem, repl, art))),
        (canon.CH_TECH, "", canon.VAL_TECH_CAR),
        (canon.CH_PLACE, "", canon.join_multi(_places(product.get("name")))),
    ]
    return canon.order_chars(ch + list(details or []))


# ---------- Опис (ПРАВИЛА §3a) ----------
def html_desc(product, lang):
    name = _display_name(product.get("name")).rstrip(".")
    oem, repl = _oem_repl(product)
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


# Заборонені слова — з rules.py. Тут лежала ТРЕТЯ копія списку (у валідаторі
# була друга), і саме вона вирішувала, що поїде в Prom. Списки вже розійшлись:
# тут не було «продать», а у валідаторі було.
# Загальні слова («авто», «запчастини») перевіряються ІНАКШЕ, ніж рекламні:
# ціле слово і лише коли з них складається вся фраза — див. rules.generic_only().
# Раніше підрядок «запчастини» різав і законний запит «автозапчастини BMW F30».


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
    return not bad_words_in(k)


def gen_keywords(product, lang):
    name = product.get("name") or ""
    brand = product.get("brand") or ""
    art = product.get("article") or ""
    oem, repl = _oem_repl(product)
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
    return [k for k in kws if _kw_ok(k)][:KW_MAX]


# ---------- Мета ----------
# Числа — з rules.py (там же джерело кожного: довідка Prom про метатеги для
# заголовка, власна межа проєкту для опису). Імена лишились ті самі, бо на них
# спираються тести й старі імпорти.
META_TITLE_MAX = RULES_META_TITLE_MAX
META_DESC_MAX = RULES_META_DESC_MAX


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
    oem, _ = _oem_repl(product)
    base = re.sub(r"\s+", " ", (ua2ru(name) if lang == "ru" else name)).strip()
    num = (oem[0] if oem else art)
    o = (f" OEM {num}." if num else "")
    tail = (" Оригинал и аналоги, отправка ежедневно по Украине."
            if lang == "ru" else
            " Оригінал і аналоги, відправка щодня по Україні.")
    s = _trim(base, META_DESC_MAX - len(o)) + o
    return (s + tail) if len(s) + len(tail) <= META_DESC_MAX else s


# Поля, у яких каталожний номер мусить бути суцільним. Технічні колонки
# (Кросс-номери, MPN, Код_запчастини) сюди не входять: вони й так проходять
# через _solid(), а числа в них — не «текст», а значення.
_SOLID_FIELDS = ("Назва_позиції", "Назва_позиції_укр",
                 "Пошукові_запити", "Пошукові_запити_укр",
                 "Опис", "Опис_укр",
                 "HTML_заголовок", "HTML_заголовок_укр",
                 "HTML_опис", "HTML_опис_укр")


def enforce_limits(f, art=""):
    """Єдиний шлюз жорстких меж Prom/Google. Працює і для детермініка, і для ШІ.

    Що робить:
      • мета-заголовок ≤70, мета-опис ≤160 (§4, §10);
      • каталожний номер присутній в обох мета-полях (§0);
      • каталожні номери СУЦІЛЬНО, без пробілів, у всіх текстових полях (§0);
      • ключовики: без заборонених слів і сміття, не більше 40 (§2, §10).
    Нічого не «покращує» — лише не пускає за межі. Оцінку якості робить
    валідатор (adding/validator.py), а не цей шлюз."""
    art = str(art or "").strip()
    # Номер суцільно — тут, а не лише в джерелі даних: через ці самі ворота
    # проходить і текст, переписаний ШІ, а він теж любить «людський» запис
    # «31 30 6 791 712». Ворота мусять тримати правило незалежно від автора.
    for k in _SOLID_FIELDS:
        if f.get(k):
            f[k] = _solid_nums(str(f[k]))
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
        f[k] = ", ".join(kws[:KW_MAX])
    return f


def gtin_from(product):
    """Штрихкод для колонки «Код_маркування_(GTIN)».

    27.07 додано контрольну цифру GS1. Раніше перевірялась лише ДОВЖИНА, тому
    будь-які 13 цифр вважались штрихкодом. Google Merchant Center відхиляє
    товар із неправильним GTIN, а Prom такий код мовчки приймає — тобто помилку
    видно було б аж у відхиленому фіді Google, через тиждень і без пояснення.
    Краще не віддати GTIN зовсім (поле не обов'язкове), ніж віддати вигаданий:
    порожнє поле — це «нема даних», а хибне — це «ми брешемо про товар»."""
    for b in (product.get("barcodes") or []):
        d = re.sub(r"\D", "", str(b))
        if len(d) in GTIN_LENGTHS and gtin_valid(d):
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
    gid, gname, sid, surl = map_place(product)
    brand = product.get("brand") or (cand or {}).get("brand") or ""
    chars = canon_chars(product, cand=cand, details=details)
    f = {"Код_товару": art, "Ідентифікатор_товару": art,
         "Назва_позиції": name_ru or name_ua, "Назва_позиції_укр": name_ua,
         "Пошукові_запити": ", ".join(gen_keywords(product, "ru")),
         "Пошукові_запити_укр": ", ".join(gen_keywords(product, "ua")),
         "Опис": html_desc(product, "ru"), "Опис_укр": html_desc(product, "ua"),
         "HTML_заголовок": meta_title(product, "ru"), "HTML_заголовок_укр": meta_title(product, "ua"),
         "HTML_опис": meta_desc(product, "ru"), "HTML_опис_укр": meta_desc(product, "ua"),
         "Ціна": price, "Валюта": canon.SCALAR_DEFAULTS["Валюта"],
         # Тип_товару=r, Знижка, Ярлик, Товар_в_ProSale — не «магія», а те, що
         # стоїть у 3960/3960 бойових рядків (adding/canon.py). Досі ці колонки
         # їхали в Prom ПОРОЖНІМИ, тобто щойно додана позиція відрізнялась від
         # решти магазину знижкою і відсутністю в ProSale.
         "Тип_товару": canon.SCALAR_DEFAULTS["Тип_товару"],
         "Знижка": canon.SCALAR_DEFAULTS["Знижка"],
         "Ярлик": canon.SCALAR_DEFAULTS["Ярлик"],
         "Товар_в_ProSale": canon.SCALAR_DEFAULTS["Товар_в_ProSale"],
         "Одиниця_виміру": canon.unit_for(name_ua),
         "Наявність": avail, "Кількість": qty_cell,
         # ДВІ ОСІ. Група — вітрина магазину; підрозділ — каталог самого Prom,
         # і без нього позиції нема в маркетплейсному пошуку. Посилання не
         # пишеться руками: його рахує canon.section_url() з ідентифікатора,
         # щоб номер і адреса фізично не могли розійтися.
         "Номер_групи": gid, "Назва_групи": gname,
         "Ідентифікатор_підрозділу": sid, "Посилання_підрозділу": surl,
         "Виробник": brand,
         "Країна_виробник": canon.country_for(brand),
         # MPN — той самий каталожний номер, лише в полі, яке читає Google
         # Merchant. Без нього фід або відхиляється, або товар не склеюється з
         # такими самими в інших магазинів.
         "Номер_пристрою_(MPN)": _solid(art),
         "Посилання_зображення": canon.join_images(imgs)}
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
    # Повертаємо КАНОНІЧНИЙ набір, а не сирі details постачальника: рівно те, що
    # ляже в блоки характеристик експорту і що побачить валідатор та ШІ-аудит.
    # Досі ці три місця дивились на різні списки, і «Код запчастини» не бачило
    # жодне з них.
    return f, name_ua, imgs, chars, price


def repair_card(f, product, issues, use_ai=True):
    """ДРУГИЙ ПРОХІД ШІ: переписати текст так, щоб зауваження аудиту зникли.

    Повертає список полів, які реально змінились (порожній — нічого не робили).
    Технічних полів не торкається взагалі: merge_ai фізично вміє писати лише в
    10 текстових ключів, тому група, ціна, наявність, характеристики й фото
    лишаються такими, якими їх порахував код. Зауваження про них сюди навіть не
    доходять — ai_layer.repairable() відсіює все, крім тексту.

    Після правки картка ЗНОВУ проходить enforce_limits(): відповідь другого
    проходу — такий самий сирий текст від провайдера, як і першого, і поблажок
    їй не робиться."""
    if not use_ai or not repair_on() or not product:
        return []
    art = str(f.get("Код_товару") or "").strip()
    facts = card_facts(product, clean_details, _fitment)
    ai = repair_fields(facts, issues, current=f)
    if not ai:
        return []
    before = {k: f.get(k) for k in _REPAIRABLE}
    merge_ai(f, ai)
    enforce_limits(f, art)
    changed = [k for k in _REPAIRABLE if f.get(k) != before[k]]
    if changed:
        print(f"[ai] ✍ правка за зауваженнями: {', '.join(changed)}")
    return changed


_REPAIRABLE = ("Назва_позиції", "Назва_позиції_укр", "Пошукові_запити",
               "Пошукові_запити_укр", "Опис", "Опис_укр", "HTML_заголовок",
               "HTML_заголовок_укр", "HTML_опис", "HTML_опис_укр")
