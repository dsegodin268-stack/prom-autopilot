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
    """Вибір пропозиції по ОДНОМУ номеру. Пріоритет — НАЙМЕНШИЙ термін постачання
    (bestPrice/bestDelivery у API брехливі — рахуємо самі)."""
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
    best = pick_offer(cand)
    if not best:
        return None
    available = best["days"] <= 1 and best["qty"] > 0  # є сьогодні / на складі
    return {"cost": best["price"], "qty": int(best["qty"]) if available else 0,
            "presence": "available" if available else "order", "days": best["days"]}


def pick_offer(cand):
    """ПРАВИЛО (власник, 24.07): з-поміж пропозицій обирає з НАЙМЕНШИМ терміном
    постачання; серед однаково швидких — найдешевшу. Ціна береться САМЕ з цієї
    пропозиції, бо доставку реально виконуватимемо через найшвидшого постачальника
    (дешева-але-повільна пропозиція нас не рятує). cand: [{price,qty,days,own}]."""
    if not cand:
        return None
    return min(cand, key=lambda c: (c["days"], c["price"]))


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


def _all_brands():
    return [int(x) for x in (os.environ.get("AUTONOVA_BRANDS") or "1,72,56,59,81,16").split(",") if x.strip()]


def _av_parts(c):
    """Розбиває код на реальні номери autonova (пробіли прибрані, '+'/'-' -> окремі)."""
    raw = []
    for seg in str(c).split("+"):
        raw += _expand_code(seg)
    out = []
    for p in raw:
        p = re.sub(r"\s+", "", str(p)).strip()
        if p and len(p) >= 5 and p not in out:
            out.append(p)
    return out


def _resolve_autonova(code, cookie, all_brands):
    """Резолвить ОДИН код на autonova (перебір brandId, пари, ревізії) ->
    item {name,cost,qty,days,presence,brand} або None. Дефіс/'+' = пара:
    собівартість=сума, наявна лише якщо ОБИДВІ є, термін=найдовший з половин."""
    sp = _av_parts(code)
    cand_whole = _nkey(code)
    if not sp and cand_whole:
        sp = [cand_whole]
    if not sp:
        return None
    guess = _autonova_brand_for(code)
    order = ([guess] + [b for b in all_brands if b != guess]) if guess else all_brands
    res = None
    for bid in order:
        if len(sp) >= 2:
            acc = [_autonova_code_best(p, bid, cookie) for p in sp]
            for _ in sp:
                time.sleep(0.12)
            if all(acc):
                res = acc
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
        return None
    cost = sum(r["cost"] for r in res)
    available = all(r["presence"] == "available" for r in res)
    qty = min(int(r["qty"]) for r in res) if available else 0
    days = max(int(r.get("days") or 0) for r in res)  # пара: обидві половини мають приїхати -> найдовший термін
    return {"name": "", "cost": cost, "qty": qty, "days": days,
            "presence": "available" if available else "order", "brand": "Авто-web"}


def pull_autonova_web(codes, best, instock, cookie):
    """Для кодів БЕЗ постачальника — ціна/наявність з catalogue-api."""
    if not cookie:
        print("[autonova-web] нема AUTONOVA_COOKIE — пропуск")
        return
    if not autonova_web_authorized(cookie):
        return
    limit = int(num(os.environ.get("AUTONOVA_WEB_LIMIT") or 0))  # 0 = всі
    all_brands = _all_brands()
    n_ok = n_avail = 0
    seen = 0
    for code in codes:
        if limit and seen >= limit:
            break
        seen += 1
        item = _resolve_autonova(code, cookie, all_brands)
        if not item:
            continue
        keep_best(best, str(code).strip().upper(), item, instock)
        n_ok += 1
        if item["presence"] == "available":
            n_avail += 1
    print(f"[autonova-web] додано {n_ok} кодів (у наявності: {n_avail}) з {seen} перевірених")


def recheck_autonova_faster(codes, best, instock, cookie):
    """КРОС-ПЕРЕВІРКА (власник, 24.07): позиції, що ВЖЕ мають постачальника з прайсів
    (BMW/Porsche/Drive/BMParts), але стоять «під замовлення», перевіряємо на autonova.
    Якщо autonova має код ШВИДШЕ (менший термін, зокрема в наявності) — замінюємо
    позицію на autonova (ціна+наявність+термін). «Найшвидший постачальник виграє»
    вже МІЖ джерелами. Ліміт AUTONOVA_RECHECK_LIMIT (0 = усі)."""
    if not cookie:
        print("[recheck] нема AUTONOVA_COOKIE — крос-перевірку пропущено")
        return
    if not autonova_web_authorized(cookie):
        return
    limit = int(num(os.environ.get("AUTONOVA_RECHECK_LIMIT") or 0))  # 0 = усі
    all_brands = _all_brands()
    n_check = n_up = n_avail = 0
    for code in codes:
        if limit and n_check >= limit:
            break
        n_check += 1
        k = str(code).strip().upper()
        cur = best.get(k)
        if not cur:
            continue
        cur_days = int(num(cur.get("days"))) if cur.get("days") is not None else 15
        item = _resolve_autonova(code, cookie, all_brands)
        if not item:
            continue
        new_days = int(item.get("days") or 0)
        if new_days < cur_days:  # autonova швидша -> ціну/наявність/термін беремо з autonova
            item["article"] = k
            best[k] = item
            if item["presence"] == "available" and item["qty"] > 0:
                instock[k] = int(item["qty"])
                n_avail += 1
            else:
                instock.pop(k, None)
            n_up += 1
    print(f"[recheck] autonova крос-перевірка: {n_check} перевірено, {n_up} прискорено (у наявності: {n_avail})")
