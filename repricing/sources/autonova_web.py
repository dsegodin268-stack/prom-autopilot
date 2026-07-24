# -*- coding: utf-8 -*-
"""Джерело 5: живий веб-API AutoNova (catalogue-api.autonovad.ua) під дилерською кукі.
Потрібен секрет AUTONOVA_COOKIE (сесійна кукі дилера). Захист: перед прогоном
контрольний запит — якщо кукі віддає гостьову ціну, НІЧОГО не пишемо.
AUTONOVA_PROXY (опц.) — обхід блокування IP GitHub-раннерів.
Статичний кеш autonova_web_cache.csv ВИДАЛЕНО 2026-07-24: 322 ціни, зібрані
разово і ніколи не перевірялися — джерелом тепер є лише живий API."""
import json
import os
import re
import time
import urllib.error
import urllib.request

from common.normalize import num, _nkey, _expand_code
from repricing.sources.base import keep_best

AUTONOVA_API = "https://catalogue-api.autonovad.ua/api/products"
AUTONOVA_REF = ("A1678992200", 56, 6000)  # (код, brandId, поріг грн) — реф. дилерської ціни
AUTONOVA_PROXY = os.environ.get("AUTONOVA_PROXY")  # напр. http://user:pass@ua-host:port


def _autonova_opener():
    if AUTONOVA_PROXY:
        h = urllib.request.ProxyHandler({"http": AUTONOVA_PROXY, "https": AUTONOVA_PROXY})
        return urllib.request.build_opener(h)
    return urllib.request.build_opener()


def _autonova_diag(product_id, cookie):
    """Точна діагностика: 401/403 -> кукі; timeout/URLError -> блок IP раннера."""
    import socket
    url = f"{AUTONOVA_API}/{product_id}/extended-offers"
    print(f"[autonova-diag] proxy={'ТАК' if AUTONOVA_PROXY else 'ні'}; "
          f"cookie={'є' if cookie else 'НЕМА'} (довж {len(cookie or '')}); {url}")
    req = urllib.request.Request(url, headers={"Cookie": cookie or "",
                                               "Accept": "application/json",
                                               "User-Agent": "Mozilla/5.0 (visimics-autopilot)"})
    try:
        with _autonova_opener().open(req, timeout=8) as r:
            body = r.read(200).decode("utf-8", "replace")
            print(f"[autonova-diag] HTTP {getattr(r, 'status', 200)} OK; тіло[:100]={body[:100]!r}")
    except urllib.error.HTTPError as e:
        b = ""
        try:
            b = e.read(200).decode("utf-8", "replace")
        except Exception:
            pass
        verdict = ("КУКІ невалідна/протухла" if e.code in (401, 403) else
                   "редирект на гостя (кукі)" if e.code in (301, 302) else "інша HTTP-помилка")
        print(f"[autonova-diag] HTTPError {e.code} {e.reason} -> {verdict}; тіло[:100]={b[:100]!r}")
    except urllib.error.URLError as e:
        print(f"[autonova-diag] URLError {e.reason!r} -> БЛОК IP / мережа / DNS")
    except socket.timeout:
        print("[autonova-diag] TIMEOUT -> БЛОК IP / фаєрвол")
    except Exception as e:
        print(f"[autonova-diag] {type(e).__name__}: {str(e)[:120]}")


def _autonova_fetch(product_id, cookie):
    """GET .../{product_id}/extended-offers під дилерською кукі. JSON або None."""
    url = f"{AUTONOVA_API}/{product_id}/extended-offers"
    req = urllib.request.Request(url, headers={
        "Cookie": cookie,
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (visimics-autopilot)",
    })
    for attempt in range(3):  # 520 у origin буває транзієнтним
        try:
            with _autonova_opener().open(req, timeout=8) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (502, 503, 520, 522, 524) and attempt < 2:
                time.sleep(1.2)
                continue
            return None
        except Exception:
            if attempt < 2:
                time.sleep(1.0)
                continue
            return None
    return None


def _autonova_code_best(code, brand_id, cookie):
    """Мінімум по ВСІХ пропозиціях (bestPrice/bestDelivery у API брехливі)."""
    d = _autonova_fetch(f"{code}_{brand_id}", cookie)
    if not d:
        return None
    cand = []
    for grp in ("offers", "supplierOffers", "branchOffers", "consignmentOffers"):
        for o in (d.get(grp) or []):
            p = num((o.get("price") or {}).get("current"))
            if p <= 0:
                continue
            cand.append({
                "price": p,
                "qty": num(o.get("quantity")),
                "days": num((o.get("delivery") or {}).get("days")),
                "own": (o.get("category") == "offers"),
            })
    if not cand:
        return None
    own_stock = [c for c in cand if c["own"] and c["qty"] > 0 and c["days"] <= 1]
    if own_stock:
        b = min(own_stock, key=lambda c: c["price"])
        return {"cost": b["price"], "qty": int(b["qty"]), "presence": "available"}
    cheapest = min(cand, key=lambda c: c["price"])
    return {"cost": cheapest["price"], "qty": 0, "presence": "order"}


def autonova_web_authorized(cookie):
    """Кукі має давати ДИЛЕРСЬКУ ціну; гостьова -> нічого не пишемо."""
    code, bid, thr = AUTONOVA_REF
    d = _autonova_fetch(f"{code}_{bid}", cookie)
    if not d:
        print("[autonova-web] реф. запит не вдався — пропуск (кукі/мережа)")
        _autonova_diag(f"{code}_{bid}", cookie)
        return False
    ref = num((d.get("bestDelivery") or {}).get("price", {}).get("current"))
    if 0 < ref < thr:
        print(f"[autonova-web] авторизація OK (дилерська реф.ціна {ref:.0f} < {thr})")
        return True
    print(f"[autonova-web] УВАГА: кукі схоже протухла (реф.ціна {ref:.0f} ≥ {thr}, гостьова). "
          f"НІЧОГО не пишу з web. Онови AUTONOVA_COOKIE.")
    return False


def _autonova_brand_for(code):
    """brandId за форматом артикула: цифри->BMW(72); 'A'+цифри->Mercedes(56);
    WAP*/9-шасі->Porsche(81); решта алфанумерик (4H,8W,4M,G0,80A...)->VAG(1)."""
    c = str(code).strip().upper()
    if not c:
        return None
    if c.startswith("WAP") or (c[:1] == "9" and len(c) >= 8):
        return 81
    if c.isdigit():
        return 72
    if c[:1] == "A" and c[1:2].isdigit():
        return 56
    return 1


def pull_autonova_web(codes, best, instock, cookie):
    """Для кодів БЕЗ постачальника — ціна/наявність з catalogue-api.
    Дефіс = пара номерів: собівартість = сума, наявна лише якщо ОБИДВІ є."""
    if not cookie:
        print("[autonova-web] нема AUTONOVA_COOKIE — пропуск")
        return
    if not autonova_web_authorized(cookie):
        return
    limit = int(num(os.environ.get("AUTONOVA_WEB_LIMIT") or 0))  # 0 = всі
    ALL_BRANDS = [int(x) for x in (os.environ.get("AUTONOVA_BRANDS") or "1,72,56,59,81,16").split(",") if x.strip()]

    def _av_parts(c):
        raw = []
        for seg in str(c).split("+"):
            raw += _expand_code(seg)
        out = []
        for p in raw:
            p = re.sub(r"\s+", "", str(p)).strip()
            if p and len(p) >= 5 and p not in out:
                out.append(p)
        return out

    n_ok = n_pair = n_avail = 0
    seen = 0
    for code in codes:
        if limit and seen >= limit:
            break
        seen += 1
        sp = _av_parts(code)
        cand_whole = _nkey(code)
        if not sp and cand_whole:
            sp = [cand_whole]
        if not sp:
            continue
        guess = _autonova_brand_for(code)
        order = ([guess] + [b for b in ALL_BRANDS if b != guess]) if guess else ALL_BRANDS
        res = None
        is_pair = False
        for bid in order:
            if len(sp) >= 2:
                acc = [_autonova_code_best(p, bid, cookie) for p in sp]
                for _ in sp:
                    time.sleep(0.12)
                if all(acc):
                    res = acc
                    is_pair = True
                    break
                elif acc and acc[0]:
                    res = [acc[0]]
                    break
            else:
                r = _autonova_code_best(sp[0], bid, cookie)
                time.sleep(0.12)
                if r:
                    res = [r]
                    break
                if cand_whole and cand_whole != sp[0]:
                    r2 = _autonova_code_best(cand_whole, bid, cookie)
                    time.sleep(0.12)
                    if r2:
                        res = [r2]
                        break
                base_rev = re.sub(r"[A-Za-z]$", "", sp[0]) if sp else ""
                if base_rev and len(base_rev) >= 6 and base_rev != sp[0]:
                    r3 = _autonova_code_best(base_rev, bid, cookie)
                    time.sleep(0.12)
                    if r3:
                        res = [r3]
                        break
        if not res:
            continue
        cost = sum(r["cost"] for r in res)
        available = all(r["presence"] == "available" for r in res)
        qty = min(int(r["qty"]) for r in res) if available else 0
        keep_best(best, str(code).strip().upper(),
                  {"name": "", "cost": cost, "qty": qty,
                   "presence": "available" if available else "order", "brand": "Авто-web"}, instock)
        n_ok += 1
        if is_pair:
            n_pair += 1
        if available:
            n_avail += 1
    print(f"[autonova-web] додано {n_ok} кодів (пар: {n_pair}, у наявності: {n_avail}) з {seen} перевірених")
