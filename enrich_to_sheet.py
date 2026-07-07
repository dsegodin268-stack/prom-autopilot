# enrich_to_sheet.py — повне збагачення позиції з BM Parts у гейт підтвердження.
# Пише 2 вкладки: «Staging_Prom» (повний рядок Prom-формату) + «Звіт» (5 кол. огляду з чекбоксом).
# Prom читає ТІЛЬКИ «Export Products Sheet». Копіює туди Apps Script — лише після Підтвердити=TRUE.
# БЕЗ API Prom. Env: GCP_SA_KEY (Editor), BMPARTS (токен), WRITE_ARTICLE (артикул).
import os
import json
import math
import html
import re
import datetime
import unicodedata

ID_HUB = "1pesHiOHDq2Y4FYQECakfhIJlq08bg5_Pkm9e2YEDoic"
PRODUCTS_TAB = os.environ.get("PRODUCTS_TAB", "Export Products Sheet")
STAGING_TAB = os.environ.get("STAGING_TAB", "Staging_Prom")
REVIEW_TAB = os.environ.get("REVIEW_TAB", "Звіт")

UA2RU = {
    "gal": "tor",  # placeholder key removed below
}
UA2RU = {
    "гальмівні": "тормозные",
    "гальмівний": "тормозной",
    "гальмівна": "тормозная",
    "колодки": "колодки",
    "диск": "диск", "диски": "диски",
    "передні": "передние",
    "передній": "передний",
    "задні": "задние", "задній": "задний",
    "фільтр": "фильтр",
    "масляний": "масляный",
    "повітряний": "воздушный",
    "салону": "салона",
    "амортизатор": "амортизатор",
    "підшипник": "подшипник",
    "ремінь": "ремень",
    "насос": "насос", "радіатор": "радиатор",
    "гумові": "резиновые",
    "килимки": "коврики", "килимок": "коврик",
    "комплект": "комплект",
    "система": "система",
}


def ua2ru(t):
    def repl(m):
        w = m.group(0)
        r = UA2RU.get(w.lower())
        if not r:
            return w
        return r.capitalize() if w[:1].isupper() else r
    return re.sub(r"[Ѐ-ӿ']+", repl, t or "")


def num(x):
    try:
        return float(str(x).replace(",", ".").replace("\xa0", "").replace(" ", ""))
    except Exception:
        return 0.0


def final_price(cost):
    c = num(cost)
    if c <= 0:
        return ""
    k = 1.5 if c < 3000 else 1.45 if c < 5000 else 1.3 if c < 10000 else 1.2 if c < 30000 else 1.1
    return int(math.ceil(c * k))


def esc(s):
    return html.escape(str(s or ""))


def gclient():
    import gspread
    return gspread.service_account_from_dict(json.loads(os.environ["GCP_SA_KEY"]))


def col_idx(header, *names):
    low = [str(h).strip().lower() for h in header]
    for n in names:
        for i, h in enumerate(low):
            if h == n.lower():
                return i
    for n in names:
        for i, h in enumerate(low):
            if n.lower() in h:
                return i
    return -1


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


def _fitment(product, name):
    from bmparts import fitment_lines
    fit = fitment_lines(product)
    if fit:
        return fit
    toks = _car_tokens(name)
    if not toks:
        return []
    brand = toks[0]
    models = [t for t in toks[1:] if re.match(r"^[A-Za-z]+\d", t)][:5]
    return [f"{brand} {m}" for m in models] or [brand]


def html_desc(product, lang):
    from bmparts import oem_and_replacements, parse_details
    name = (product.get("name") or "").strip().rstrip(".")
    oem, repl = oem_and_replacements(product)
    details = parse_details(product.get("details"))
    if lang == "ru":
        nm = ua2ru(name)
        L = {"q": "оригинальное качество для вашего авто",
             "fit": "Прямая замена изношенного узла, возвращает штатную работу.",
             "oem": "Оригинальный (OEM) номер", "rep": "Аналоги / замена",
             "ch": "Характеристики",
             "ship": "Отправка ежедневно. Гарантия соответствия.",
             "cta": "Не уверены, подойдёт ли именно на ваше авто? <strong>Мы подберём за вас</strong> — напишите марку, модель, год и VIN-код.",
             "lab": "Подходит на"}
    else:
        nm = name
        L = {"q": "оригінальна якість для вашого авто",
             "fit": "Пряма заміна зношеного вузла, відновлює штатну роботу.",
             "oem": "Оригінальний (OEM) номер", "rep": "Аналоги / замінники",
             "ch": "Характеристики",
             "ship": "Відправка щодня. Гарантія відповідності.",
             "cta": "Не впевнені, чи підійде саме на ваше авто? <strong>Ми підберемо за вас</strong> — напишіть марку, модель, рік і VIN-код.",
             "lab": "Підходить на"}
    p = []
    p.append(f"<p>\U0001F697 <strong>{esc(nm)}</strong> — {L['q']}.</p>")
    p.append(f"<p>✅ {L['fit']}</p>")
    fitc = _fitment(product, name)
    if fitc:
        p.append(f"<p>\U0001F50E <strong>{L['lab']}:</strong> {esc(', '.join(fitc))}.</p>")
    if oem:
        p.append(f"<p>\U0001F527 <strong>{L['oem']}:</strong> {esc(', '.join(oem))}.</p>")
    if repl:
        p.append(f"<p>\U0001F501 <strong>{L['rep']}:</strong> {esc(', '.join(repl[:12]))}.</p>")
    if details:
        lis = "".join(
            f"<li>{esc(ua2ru(n) if lang == 'ru' else n)}: {esc(v)}{(' ' + esc(u)) if u else ''}</li>"
            for (n, u, v) in details[:8])
        p.append(f"<p>\U0001F4CB <strong>{L['ch']}:</strong></p><ul>{lis}</ul>")
    p.append(f"<p>\U0001F4E6 {L['ship']}</p>")
    p.append(f"<p>❓ {L['cta']}</p>")
    return "".join(p)


def gen_keywords(product, lang):
    from bmparts import oem_and_replacements
    name = product.get("name") or ""
    brand = product.get("brand") or ""
    art = product.get("article") or ""
    oem, repl = oem_and_replacements(product)
    typ = _type_phrase(name)
    typ_l = ua2ru(typ) if lang == "ru" else typ
    cars = _car_tokens(name)
    kws = []

    def add(*xs):
        for x in xs:
            x = re.sub(r"\s+", " ", str(x)).strip()
            if x and x.lower() not in [k.lower() for k in kws]:
                kws.append(x)

    add(typ_l)
    if typ_l and brand:
        add(f"{typ_l} {brand}")
    if brand:
        add(brand, f"{brand} {art}")
    carbrand = cars[0] if cars else ""
    models = [c for c in cars if c.lower() != carbrand.lower()][:4]
    if carbrand:
        add(carbrand)
    for m in models:
        add(f"{carbrand} {m}")
        if typ_l:
            add(f"{typ_l} {carbrand} {m}")
    if typ_l and carbrand:
        add(f"{typ_l} {carbrand}")
    for o in oem[:6]:
        add(o)
    for r in repl[:6]:
        add(r.split()[-1] if r else r)
    add(art)
    return kws[:30]


def meta_title(product, lang):
    name = product.get("name") or ""
    art = product.get("article") or ""
    t = re.sub(r"\s+", " ", (ua2ru(name) if lang == "ru" else name)).strip()
    if art and art not in t:
        t = f"{t} {art}"
    return t[:70]


def meta_desc(product, lang):
    from bmparts import oem_and_replacements
    name = product.get("name") or ""
    oem, _ = oem_and_replacements(product)
    base = ua2ru(name) if lang == "ru" else name
    o = (f" OEM {oem[0]}." if oem else "")
    tail = " Оригинал и аналоги." if lang == "ru" else " Оригінал і аналоги."
    return (base + o + tail)[:160]


def build_fields(product):
    from bmparts import clean_name, cdn_url, parse_details
    art = str(product.get("article") or "").strip()
    name_ua = clean_name(product.get("name"))
    name_ru = clean_name(ua2ru(product.get("name") or ""))
    imgs = [cdn_url(p) for p in (product.get("images") or [])]
    details = parse_details(product.get("details"))
    price = final_price(product.get("price"))
    f = {
        "Код_товару": art, "Ідентифікатор_товару": art,
        "Назва_позиції": name_ru or name_ua, "Назва_позиції_укр": name_ua,
        "Пошукові_запити": ", ".join(gen_keywords(product, "ru")),
        "Пошукові_запити_укр": ", ".join(gen_keywords(product, "ua")),
        "Опис": html_desc(product, "ru"), "Опис_укр": html_desc(product, "ua"),
        "HTML_заголовок": meta_title(product, "ru"), "HTML_заголовок_укр": meta_title(product, "ua"),
        "HTML_опис": meta_desc(product, "ru"), "HTML_опис_укр": meta_desc(product, "ua"),
        "Ціна": price, "Валюта": "UAH", "Одиниця_виміру": "шт.", "Наявність": "+",
        "Виробник": product.get("brand") or "",
        "Посилання_зображення": ", ".join(imgs),
    }
    return f, name_ua, imgs, details, price


def _norm(t):
    return unicodedata.normalize("NFC", str(t or "")).strip().casefold()


def get_or_create(ss, title, rows, cols):
    """Знайти вкладку за NFC-нормалізованою назвою; інакше створити. Стійко до кешу/нормалізації/гонки."""
    want = _norm(title)

    def _pick(w):
        if w.title != title:
            try:
                w.update_title(title)
            except Exception:
                pass
        return w
    for w in ss.worksheets():
        if _norm(w.title) == want:
            return _pick(w)
    try:
        return ss.add_worksheet(title=title, rows=rows, cols=cols)
    except Exception:
        for w in ss.worksheets():
            if _norm(w.title) == want:
                return _pick(w)
        raise


def main():
    from bmparts import BMParts
    from validator import validate_card, summarize
    gc = gclient()
    ss = gc.open_by_key(ID_HUB)
    src = ss.worksheet(PRODUCTS_TAB)
    header = src.row_values(1)
    print(f"=== Export Products Sheet: {len(header)} cols ===")
    print("head12:", header[:12])
    art = os.environ.get("WRITE_ARTICLE", "").strip()
    if not art:
        print("no WRITE_ARTICLE"); return

    bm = BMParts()
    prod = bm.get_product(art)
    if not prod:
        print(f"BM Parts not found {art}"); return
    fields, name_ua, imgs, details, price = build_fields(prod)

    card = {"name": fields["Назва_позиції_укр"],
            "description": fields["Опис_укр"],
            "chars": details, "images": imgs, "price": price,
            "product_id": fields["Ідентифікатор_товару"], "group_id": None}
    flags = validate_card(card, is_part=True)
    vs = summarize(flags)
    print("VALIDATOR:", vs)
    print("matched:", [k for k in fields if col_idx(header, k) >= 0])
    print("no-column:", [k for k in fields if col_idx(header, k) < 0])

    full = [""] * len(header)
    for k, v in fields.items():
        i = col_idx(header, k)
        if i >= 0:
            full[i] = v

    stg = get_or_create(ss, STAGING_TAB, 200, max(len(header), 26))
    if stg.row_values(1) != header:
        stg.resize(rows=max(stg.row_count, 200), cols=len(header))
        stg.update(values=[header], range_name="A1")
    stg_arts = stg.col_values(1)
    if art in stg_arts:
        r = stg_arts.index(art) + 1
        stg.update(values=[full], range_name=f"A{r}")
        print(f"[staging] updated row {r}")
    else:
        stg.append_row(full, value_input_option="RAW")
        print("[staging] appended")

    rhead = ["Артикул", "Назва", "Статус", "Дата додавання", "Підтвердити"]
    rv = get_or_create(ss, REVIEW_TAB, 200, 6)
    if rv.row_values(1) != rhead:
        rv.update(values=[rhead], range_name="A1")
    today = datetime.date.today().isoformat()
    rv_arts = rv.col_values(1)
    review = [art, name_ua, "нова", today, False]
    if art in rv_arts:
        r = rv_arts.index(art) + 1
        rv.update(values=[review], range_name=f"A{r}")
        rrow = r
    else:
        rv.append_row(review, value_input_option="USER_ENTERED")
        rrow = len(rv_arts) + 1
    ss.batch_update({"requests": [{
        "setDataValidation": {
            "range": {"sheetId": rv.id, "startRowIndex": 1, "startColumnIndex": 4, "endColumnIndex": 5},
            "rule": {"condition": {"type": "BOOLEAN"}, "showCustomUi": True}
        }}]})
    print(f"OK: review row {rrow} for {art} ({name_ua}); Status='nova', checkbox off.")
    print(">>> Manager checks 'Pidtverdyty' -> Apps Script copies full row Staging_Prom -> Export Products Sheet.")


if __name__ == "__main__":
    main()
