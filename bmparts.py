# bmparts.py — клієнт BM Parts API v2 + збирач картки Prom за ПРАВИЛА_PROM.md
# Токен читається з env BMPARTS_TOKEN (я його не бачу). Auth: header "Authorization: <token>".
# Джерело специфікації: developer.bm.parts/api/v2 (product.html, prices.html, lists.html, search_products.html).
import os
import re
import json

API = "https://api.bm.parts"
CDN = "https://cdn.bm.parts"
UA_CURRENCY = "A358000C2947F7AE11E23F5617780B16"  # ГРН (з доків prices.html)
UA = "VisimicsBot/1.0 (+prom autopilot)"          # обов'язковий User-Agent

CTA = ("Не впевнені, чи підійде саме на ваше авто? Ми підберемо за вас — "
       "напишіть марку, модель, рік і VIN-код.")


# ---------- HTTP-клієнт ----------
class BMParts:
    def __init__(self, token=None):
        self.token = token or os.environ.get("BMPARTS_TOKEN", "")
        import requests
        self.s = requests.Session()
        self.s.headers.update({"Authorization": self.token, "User-Agent": UA,
                               "Accept": "application/json"})

    def search_uuid(self, article):
        """Артикул -> UUID через GET /search/products (endpoint /product/{uuid} приймає ЛИШЕ uuid)."""
        r = self.s.get(f"{API}/search/products",
                       params={"q": article, "search_mode": "strict"}, timeout=40)
        r.raise_for_status()
        products = r.json().get("products") or {}
        norm = lambda s: re.sub(r"\s+", "", str(s or "")).lower()
        target = norm(article)
        if isinstance(products, dict):          # obj-режим: ключ = uuid
            for uuid, p in products.items():
                if norm(p.get("article")) == target:
                    return uuid
            return next(iter(products), None)   # запасний перший
        if isinstance(products, list):          # arr-режим: uuid у полі
            for p in products:
                if norm(p.get("article")) == target:
                    return p.get("uuid")
            return products[0].get("uuid") if products else None
        return None

    def get_product(self, code, by_code=True):
        """Артикул -> пошук UUID -> GET /product/{uuid} (назва, details, oe, analogs, cars, images)."""
        uuid = self.search_uuid(code) if by_code else code
        if not uuid:
            return None
        params = {"output_field": "all", "oe": "full", "warehouses": "all"}
        r = self.s.get(f"{API}/product/{uuid}", params=params, timeout=40)
        if r.status_code in (404, 422):
            return None
        r.raise_for_status()
        return r.json().get("product", r.json())

    def prom_price_csv(self, brand_name, warehouses):
        """POST /prices/prom/{brand_name} — прайс одразу у форматі імпорту Prom.ua."""
        body = {"currency": UA_CURRENCY, "warehouses": warehouses}
        r = self.s.post(f"{API}/prices/prom/{brand_name}", json=body, timeout=120)
        r.raise_for_status()
        return r.text

    def photos_csv(self, brands=None):
        """POST /lists/photos_link — CSV «ІД, артикул, бренд, посилання на фото»."""
        body = {"brands": brands} if brands else {}
        r = self.s.post(f"{API}/lists/photos_link", json=body, timeout=120)
        r.raise_for_status()
        return r.text


# ---------- Збирач картки (чисті функції, без мережі) ----------
def parse_details(details):
    """details {"Наружный диаметр [мм]": "76,00", ...} -> [(назва, одиниця, значення)]."""
    out = []
    for k, v in (details or {}).items():
        m = re.search(r"\[([^\]]+)\]\s*$", k)
        unit = m.group(1).strip() if m else ""
        name = re.sub(r"\s*\[[^\]]+\]\s*$", "", k).strip()
        val = str(v).replace(",", ".") if re.match(r"^[\d,\.]+$", str(v)) else str(v)
        out.append((name, unit, val))
    return out


def clean_name(name):
    """Назва для поля Prom: без дефіса, без подвійних пробілів, <=110 (правила Prom)."""
    n = (name or "").replace("—", " ").replace("–", " ").replace("-", " ")
    n = re.sub(r"\s+", " ", n).strip()
    return n[:110].strip()


def cdn_url(path):
    p = str(path).replace("\\", "/").lstrip("/")
    return f"{CDN}/{p}"


def oem_and_replacements(product):
    """Повертає (список OEM-номерів, список замінників) з oe[] + analogs{}."""
    oe = product.get("oe") or []
    oem = [o.get("number") for o in oe if o.get("is_oem") and o.get("number")]
    other_oe = [f"{o.get('number')} ({o.get('brand')})" for o in oe
                if not o.get("is_oem") and o.get("number")]
    analogs = product.get("analogs") or {}
    repl = []
    for a in analogs.values():
        art, br = a.get("article"), a.get("brand")
        if art:
            repl.append(f"{br} {art}".strip())
    return oem, (other_oe + repl)


def fitment_lines(product):
    """cars[] -> рядки сумісності. Структура cars гнучка -> збираємо захищено."""
    cars = product.get("cars") or []
    out = []
    for c in cars:
        if isinstance(c, dict):
            parts = [str(c.get(k)) for k in ("brand", "model", "modification", "years", "name")
                     if c.get(k)]
            if parts:
                out.append(" ".join(parts))
        elif isinstance(c, str):
            out.append(c)
    return out


def build_parts_description(product):
    """Опис запчастини за розділом 3a ПРАВИЛА_PROM.md."""
    name = (product.get("name") or "").strip()
    oem, repl = oem_and_replacements(product)
    fit = fitment_lines(product)
    details = parse_details(product.get("details"))

    blocks = []
    blocks.append(name.rstrip(".") + ".")                      # 1. перший блок
    if fit:                                                    # 2. сумісність
        blocks.append("Підходить на: " + "; ".join(fit) + ".")
    if oem or repl:                                            # 3. OEM + замінники
        s = ""
        if oem:
            s += "Оригінальний (OEM) номер: " + ", ".join(oem) + ". "
        if repl:
            s += "Аналоги/замінники: " + ", ".join(repl[:15]) + "."
        blocks.append(s.strip())
    if details:                                               # 4. характеристики
        blocks.append("Характеристики: " + "; ".join(
            f"{n} — {v}{(' ' + u) if u else ''}" for (n, u, v) in details[:8]) + ".")
    blocks.append(CTA)                                        # 5. CTA (обов'язково)
    return "\n".join(blocks)


def assemble_card(product):
    """BM Parts product -> картка для валідатора/Prom."""
    images = [cdn_url(p) for p in (product.get("images") or [])]
    return {
        "name": clean_name(product.get("name")),
        "name_source": product.get("name"),          # оригінал (RU -> UA-переклад = крок ШІ)
        "description": build_parts_description(product),
        "chars": parse_details(product.get("details")),
        "images": images,
        "price": product.get("price"),
        "group_hint": product.get("nodes"),          # категорія BM Parts -> мапити на групу Prom
        "product_id": product.get("article"),
        "group_id": None,                             # ставиться на етапі мапінгу груп
        "brand": product.get("brand"),
    }


# ---------- Пробний прогін ----------
if __name__ == "__main__":
    import sys
    from validator import validate_card, summarize
    art = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("PROBE_ARTICLE", "")).strip()
    bm = BMParts()
    prod = bm.get_product(art)
    if not prod:
        print(f"[bmparts] артикул {art!r} не знайдено"); sys.exit(1)
    card = assemble_card(prod)
    print("=== КАРТКА ===")
    print("Назва:", card["name"])
    print("Фото:", len(card["images"]), "| Характеристик:", len(card["chars"]))
    print("--- Опис ---"); print(card["description"])
    print("=== ВАЛІДАТОР ===", summarize(validate_card(card, is_part=True)))
