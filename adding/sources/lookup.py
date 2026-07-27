# -*- coding: utf-8 -*-
"""Довідник контенту: артикул будь-якого постачальника -> картка BM Parts.

ГОЛОВНА ІДЕЯ МОДУЛЯ. BMParts.get_product() шукає за артикулом, а не за нашим
договором постачання. Отже позицію з прайсу «Баварії» чи Porsche можна знайти
в каталозі BM Parts і безкоштовно взяти звідти фото, характеристики, OEM-номери
і сумісність — навіть якщо купувати ми будемо не в BM Parts.

ЗАЛІЗНЕ ПРАВИЛО: ціна, валюта, наявність і кількість беруться виключно від
постачальника, у якого купуємо. Довідник BM Parts дає лише контент.
Нижче цього правила дотримано буквально: bm_lookup() пише тільки в поля
photos / chars / oem / fitment / group_hint / bm_product і не має жодного
присвоєння в cost, qty, presence, days.

ЩЕ ОДНЕ ПРАВИЛО — «тільки оригінал». search_uuid() при неточному збігу віддає
ПЕРШИЙ‑ліпший результат пошуку. Якщо це проковтнути, на картку оригінальної
деталі BMW потраплять фото аналога. Тому кожне влучання перевіряється
_verify(): або артикул збігся символ‑у‑символ, або знайдена позиція — це той
самий бренд і наш артикул є в її списку OEM."""
import re

from common.bmparts_client import cdn_url, fitment_lines, oem_and_replacements
from common.normalize import _expand_code, _nkey
from adding.sources import key


def _codes_to_try(article):
    """Артикул -> варіанти запиту. Дефісні коди прайсу («51117303107-108») —
    це ДВА повних номери, тому пробуємо і склеєний, і кожен окремо."""
    raw = str(article or "").strip()
    out = []
    for c in [raw] + list(_expand_code(raw)) + [re.split(r"[-–—]", raw)[0]]:
        c = str(c).strip()
        if c and c not in out:
            out.append(c)
    return out


def _verify(product, article, brand=""):
    """Чи справді ця картка BM Parts про НАШУ деталь (див. «тільки оригінал»)."""
    want = key(article)
    if not want:
        return False
    if _nkey(product.get("article")) == want:
        return True
    pb = str(product.get("brand") or "").strip().lower()
    if brand and pb and pb == str(brand).strip().lower():
        oem, _ = oem_and_replacements(product)
        if any(_nkey(o) == want for o in oem):
            return True
    return False


def bm_lookup(bm, c, cache=None):
    """Заповнює контент кандидата з каталогу BM Parts. Повертає True, якщо влучили.

    Ціну/наявність/кількість НЕ чіпає — вони належать постачальнику з c['source'].
    """
    from adding.card_builder import clean_details  # тут, щоб не тягти ai_layer у фід

    art = c.get("article")
    ck = key(art)
    if cache is not None and ck in cache:
        prod = cache[ck]
    else:
        prod = None
        for code in _codes_to_try(art):
            try:
                p = bm.get_product(code)
            except Exception as e:
                print(f"[lookup] {art}: BM Parts помилка {str(e)[:70]}")
                break
            if p and _verify(p, art, c.get("brand")):
                prod = p
                break
            if p:
                print(f"[lookup] {art}: знайдено «{p.get('article')}» "
                      f"({p.get('brand')}) — не наша деталь, відкидаю")
        if cache is not None:
            cache[ck] = prod

    c["card_loaded"] = True
    if not prod:
        c["matched_bm"] = False
        return False

    prod.setdefault("article", art)
    oem, repl = oem_and_replacements(prod)
    photos = [cdn_url(p) for p in (prod.get("images") or [])]
    chars = clean_details(prod)
    fit = fitment_lines(prod)

    if photos and not c.get("photos"):
        c["photos"] = photos
    if chars and len(chars) > len(c.get("chars") or []):
        c["chars"] = chars
    if oem:
        c["oem"] = oem
    if repl:
        c["replacements"] = repl
    if fit:
        c["fitment"] = fit
    if not c.get("group_hint"):
        c["group_hint"] = prod.get("nodes") or ""
    if not (c.get("name_src") or "").strip():
        c["name_src"] = prod.get("name") or ""
    c["bm_name"] = prod.get("name") or ""
    c["bm_product"] = prod          # щоб enrich не робив другий запит
    c["matched_bm"] = True
    return True


def bm_lookup_many(bm, cands, limit=0, cache=None):
    """Довідник для пачки кандидатів. Дорого (≈2.5 с на запит через тротлінг),
    тому викликається лише для того, що людина реально збирається додавати."""
    cache = {} if cache is None else cache
    hit = 0
    todo = cands[:limit] if limit else cands
    for i, c in enumerate(todo, 1):
        if c.get("card_loaded"):
            continue
        if bm_lookup(bm, c, cache):
            hit += 1
        if i % 25 == 0:
            print(f"[lookup] {i}/{len(todo)}, знайдено {hit}")
    print(f"[lookup] довідник BM Parts: {hit}/{len(todo)} позицій отримали контент")
    return hit
