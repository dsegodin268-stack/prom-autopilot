# -*- coding: utf-8 -*-
"""Клієнт BM Parts API v2 + чисті функції розбору фактів товару.
Токен: env BMPARTS_TOKEN. Auth: header "Authorization: <token>".
Специфікація: developer.bm.parts/api/v2 (product.html, prices.html, lists.html)."""
import os
import re
import time

API = "https://api.bm.parts"
CDN = "https://cdn.bm.parts"
UA_CURRENCY = "A358000C2947F7AE11E23F5617780B16"  # ГРН (з доків prices.html)
UA = "VisimicsBot/1.0 (+prom autopilot)"

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
        self._last = 0.0
        self._min = float(os.environ.get("BM_MIN_INTERVAL", "2.5"))

    def _throttle(self):
        wait = self._min - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.time()

    def _check(self, r):
        if r.status_code >= 400:
            srv = r.headers.get("server", "")
            cf = r.headers.get("cf-ray", "")
            body = (r.text or "")[:400].replace("\n", " ")
            print(f"[bm-http] {r.status_code} {r.request.method} {r.url}")
            print(f"[bm-http] server={srv!r} cf-ray={cf!r} sent_auth_len={len(self.token)}")
            print(f"[bm-http] body={body!r}")
            r.raise_for_status()

    def search_uuid(self, article):
        """Артикул → UUID через GET /search/products."""
        self._throttle()
        r = self.s.get(f"{API}/search/products",
                       params={"q": article, "search_mode": "strict"}, timeout=40)
        self._check(r)
        products = r.json().get("products") or {}
        norm = lambda s: re.sub(r"\s+", "", str(s or "")).lower()
        target = norm(article)
        if isinstance(products, dict):
            for uuid, p in products.items():
                if norm(p.get("article")) == target:
                    return uuid
            return next(iter(products), None)
        if isinstance(products, list):
            for p in products:
                if norm(p.get("article")) == target:
                    return p.get("uuid")
            return products[0].get("uuid") if products else None
        return None

    def get_product(self, code, by_code=True):
        """Артикул → UUID → GET /product/{uuid} (назва, details, oe, analogs, cars, images)."""
        uuid = self.search_uuid(code) if by_code else code
        if not uuid:
            return None
        params = {"output_field": "all", "oe": "full", "warehouses": "all"}
        self._throttle()
        r = self.s.get(f"{API}/product/{uuid}", params=params, timeout=40)
        if r.status_code in (404, 422):
            return None
        self._check(r)
        return r.json().get("product", r.json())

    def warehouses(self):
        self._throttle()
        r = self.s.get(f"{API}/company/warehouses", timeout=40)
        self._check(r)
        return r.json().get("warehouses") or []

    def prom_price_csv(self, brand_name, warehouses):
        """POST /prices/prom/{brand_name} — прайс у форматі імпорту Prom.ua (по одній марці)."""
        body = {"currency": UA_CURRENCY, "warehouses": warehouses}
        self._throttle()
        r = self.s.post(f"{API}/prices/prom/{brand_name}", json=body, timeout=120)
        r.raise_for_status()
        return r.text

    def photos_csv(self, brands=None):
        body = {"brands": brands} if brands else {}
        self._throttle()
        r = self.s.post(f"{API}/lists/photos_link", json=body, timeout=120)
        r.raise_for_status()
        return r.text


# ---------- Чисті функції розбору фактів (без мережі) ----------
def parse_details(details):
    """details {"Наружный диаметр [мм]": "76,00", ...} → [(назва, одиниця, значення)]."""
    out = []
    for k, v in (details or {}).items():
        m = re.search(r"\[([^\]]+)\]\s*$", k)
        unit = m.group(1).strip() if m else ""
        name = re.sub(r"\s*\[[^\]]+\]\s*$", "", k).strip()
        val = str(v).replace(",", ".") if re.match(r"^[\d,\.]+$", str(v)) else str(v)
        out.append((name, unit, val))
    return out


def clean_name(name):
    """Назва для Prom: без «-», без подвійних пробілів, ≤110."""
    n = (name or "").replace("—", " ").replace("–", " ").replace("-", " ")
    n = re.sub(r"\s+", " ", n).strip()
    return n[:110].strip()


def cdn_url(path):
    """Відносний шлях -> повний URL CDN. Готове посилання лишає як є —
    інакше повторний виклик ліпив «cdn.bm.parts/https:/cdn.bm.parts/…»
    (а тепер картку може будувати і кандидат, у якого фото вже з URL)."""
    p = str(path).replace("\\", "/")
    if p.startswith("http://") or p.startswith("https://"):
        return p
    return f"{CDN}/{p.lstrip('/')}"


def oem_and_replacements(product):
    """(список OEM-номерів, список замінників) з oe[] + analogs{}."""
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
    """cars[] → рядки сумісності (структура гнучка — збираємо захищено)."""
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
    """Простий текстовий опис запчастини (для проби/валідатора)."""
    name = (product.get("name") or "").strip()
    oem, repl = oem_and_replacements(product)
    fit = fitment_lines(product)
    details = parse_details(product.get("details"))

    blocks = [name.rstrip(".") + "."]
    if fit:
        blocks.append("Підходить на: " + "; ".join(fit) + ".")
    if oem or repl:
        s = ""
        if oem:
            s += "Оригінальний (OEM) номер: " + ", ".join(oem) + ". "
        if repl:
            s += "Аналоги/замінники: " + ", ".join(repl[:15]) + "."
        blocks.append(s.strip())
    if details:
        blocks.append("Характеристики: " + "; ".join(
            f"{n} — {v}{(' ' + u) if u else ''}" for (n, u, v) in details[:8]) + ".")
    blocks.append(CTA)
    return "\n".join(blocks)


def assemble_card(product):
    """BM Parts product → картка для валідатора."""
    images = [cdn_url(p) for p in (product.get("images") or [])]
    return {
        "name": clean_name(product.get("name")),
        "name_source": product.get("name"),
        "description": build_parts_description(product),
        "chars": parse_details(product.get("details")),
        "images": images,
        "price": product.get("price"),
        "group_hint": product.get("nodes"),
        "product_id": product.get("article"),
        "group_id": None,
        "brand": product.get("brand"),
    }
