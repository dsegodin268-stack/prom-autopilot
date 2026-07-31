# -*- coding: utf-8 -*-
"""Джерело 5: живий веб-API AutoNova (catalogue-api.autonovad.ua) під дилерською кукі.
Потрібен секрет AUTONOVA_COOKIE (сесійна кукі дилера). Захист: перед прогоном
контрольний запит — якщо кукі віддає гостьову ціну, НІЧОГО не пишемо.
AUTONOVA_PROXY (опц.) — обхід блокування IP GitHub-раннерів.
Статичний кеш autonova_web_cache.csv ВИДАЛЕНО 2026-07-24: 322 ціни, зібрані
разово і ніколи не перевірялися — джерелом тепер є лише живий API.

ПРАВИЛО «ТІЛЬКИ ОРИГІНАЛ» (власник, 24.07): ціна/наявність береться ВИКЛЮЧНО з
пропозицій на оригінальний (запитаний) номер. Аналоги та крос-номери відкидаються;
якщо оригіналу нема в наявності — лишаємо «під замовлення» з ціною/терміном
оригіналу, аналог НЕ підставляємо. Діагностика структури — env AUTONOVA_DEBUG=N.

ПРИСКОРЕННЯ (31.07): запити йдуть у кілька потоків (AUTONOVA_WORKERS, типово 6)
під спільним обмежувачем темпу (AUTONOVA_MIN_INTERVAL, типово 0.12 c) і з пам'яттю,
під якою маркою код знайшовся (ДЕ шукати). Що НЕ змінилось: перелік марок, перелік
позицій, правило «тільки оригінал», пріоритет прайсу BMW. Ціна/наявність/термін
НІКОЛИ не кешуються — щоразу свіжі. Рішення і запис у таблицю лишаються
послідовними, у тому ж порядку, що й раніше."""
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from common.normalize import num, _nkey, _expand_code
from repricing.sources.base import keep_best

AUTONOVA_API = "https://catalogue-api.autonovad.ua/api/products"
AUTONOVA_REF = ("A1678992200", 56, 6000)  # (код, brandId, поріг грн) — реф. дилерської ціни
AUTONOVA_PROXY = os.environ.get("AUTONOVA_PROXY")  # напр. http://user:pass@ua-host:port

# --- темп запитів і паралель (прискорення нічного прогону, 31.07) ---
# Запити йдуть у кілька потоків, але спільний обмежувач тримає СУМАРНИЙ темп.
# Виграш — з перекриття очікування мережі, а не з ударнішого навантаження.
_RATE_LOCK = threading.Lock()
_RATE_NEXT = [0.0]


def _autonova_interval():
    """Мінімальний проміжок між запитами (сумарно з усіх потоків), сек."""
    try:
        v = float(os.environ.get("AUTONOVA_MIN_INTERVAL") or 0.12)
    except Exception:
        v = 0.12
    return v if v > 0 else 0.0


def _autonova_workers():
    """Скільки кодів питаємо одночасно. Менше = обережніше до autonova."""
    try:
        n = int(float(os.environ.get("AUTONOVA_WORKERS") or 6))
    except Exception:
        n = 6
    return max(1, min(16, n))


def _rate_gate():
    """Пропускає не більше одного запиту на _autonova_interval() секунд —
    спільно для ВСІХ потоків. Замінює колишній time.sleep(0.12) після кожного
    запиту: темп той самий, але потоки чекають мережу паралельно."""
    iv = _autonova_interval()
    if iv <= 0:
        return
    with _RATE_LOCK:
        now = time.monotonic()
        wait = _RATE_NEXT[0] - now
        if wait < 0.0:
            wait = 0.0
        _RATE_NEXT[0] = now + wait + iv
    if wait > 0:
        time.sleep(wait)


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
        _rate_gate()
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


# --- розпізнавання ОРИГІНАЛ vs АНАЛОГ у відповіді autonova ---
_ART_KEYS = ("article", "articleNr", "articleNumber", "number", "code", "sku",
             "oem", "partNumber", "part_number", "articleCode", "articul", "brandCode")
_BRAND_KEYS = ("brand", "producer", "manufacturer", "tradeMark", "trademark",
               "brandName", "producerName")
_ORIG_FLAGS = ("isoriginal", "original", "isoem", "oem", "isgenuine", "genuine")
_ANALOG_FLAGS = ("isanalog", "analog", "isreplacement", "replacement", "iscross",
                 "cross", "issubstitute", "substitute")
# скільки лукапів повністю залогувати (структура відповіді) — env AUTONOVA_DEBUG (0=вимк)
_dbg_left = [int(num(os.environ.get("AUTONOVA_DEBUG") or 0))]


def _field(dct, keys):
    """Перше непорожнє значення за списком ключів (регістронезалежно) як рядок."""
    if not isinstance(dct, dict):
        return ""
    low = {str(k).lower(): v for k, v in dct.items()}
    for k in keys:
        v = low.get(k.lower())
        if isinstance(v, dict):
            v = v.get("name") or v.get("title") or v.get("value") or v.get("code")
        if v not in (None, "", 0, "0"):
            return str(v)
    return ""


def _flag(dct, keys):
    """True, якщо будь-який із прапорців стоїть (bool/1/true/yes)."""
    if not isinstance(dct, dict):
        return False
    low = {str(k).lower(): v for k, v in dct.items()}
    for k in keys:
        v = low.get(k)
        if v is True:
            return True
        if isinstance(v, (int, float)) and v == 1:
            return True
        if isinstance(v, str) and v.strip().lower() in ("1", "true", "yes", "original", "оригінал"):
            return True
    return False


def _is_original_offer(o, req, prod_art):
    """Чи пропозиція стосується САМЕ оригінального номера (req = _nkey коду).
    Пріоритет: явні прапорці -> артикул пропозиції -> артикул продукту ->
    (жодних ознак) вважаємо оригіналом (ендпоінт і так по точному номеру)."""
    art = _nkey(_field(o, _ART_KEYS))
    if _flag(o, _ANALOG_FLAGS) and not _flag(o, _ORIG_FLAGS):
        return bool(art) and art == req     # позначено як аналог -> тільки якщо номер збігається
    if _flag(o, _ORIG_FLAGS):
        return True
    if art:
        return art == req
    if prod_art:
        return prod_art == req
    return True


def _autonova_code_best(code, brand_id, cookie):
    """ТІЛЬКИ ОРИГІНАЛ (власник, 24.07): по ОДНОМУ номеру беремо лише пропозиції на
    САМЕ цей (оригінальний) номер; аналоги/крос-номери відкидаємо повністю.
      • оригінал у наявності -> «available» з його ціною;
      • оригінал є, але не в наявності -> «order» з ціною/терміном оригіналу;
      • оригіналу на autonova нема (лише аналоги / нічого) -> None (НЕ підміняємо аналогом).
    Серед пропозицій оригіналу: найменший термін, потім найдешевша."""
    d = _autonova_fetch(f"{code}_{brand_id}", cookie)
    if not d:
        return None
    req = _nkey(code)
    prod_art = _nkey(_field(d, _ART_KEYS))
    orig, analog, dump = [], [], []
    for grp in ("offers", "supplierOffers", "branchOffers", "consignmentOffers"):
        for o in (d.get(grp) or []):
            p = num((o.get("price") or {}).get("current"))
            if p <= 0:
                continue
            row = {"price": p, "qty": num(o.get("quantity")),
                   "days": num((o.get("delivery") or {}).get("days")),
                   "own": (grp == "offers")}
            is_orig = _is_original_offer(o, req, prod_art)
            (orig if is_orig else analog).append(row)
            if _dbg_left[0] > 0:
                dump.append((grp, _field(o, _ART_KEYS), _field(o, _BRAND_KEYS),
                             p, row["qty"], row["days"], is_orig))
    if _dbg_left[0] > 0:
        _dbg_left[0] -= 1
        print(f"[autonova-dbg] {code}_{brand_id} top-keys={sorted(d.keys())[:24]} "
              f"prod_art={prod_art!r} orig={len(orig)} analog={len(analog)}")
        for r in dump[:14]:
            print(f"[autonova-dbg]   grp={r[0]} art={r[1]!r} brand={r[2]!r} "
                  f"price={r[3]} qty={r[4]} days={r[5]} orig={r[6]}")
    if not orig:
        if analog:
            print(f"[autonova] {code}: на autonova лише аналоги ({len(analog)}), "
                  f"оригіналу нема -> пропускаю (тільки оригінал)")
        return None
    best = pick_offer(orig)
    if not best:
        return None
    available = best["days"] <= 1 and best["qty"] > 0  # є сьогодні / на складі
    return {"cost": best["price"], "qty": int(best["qty"]) if available else 0,
            "presence": "available" if available else "order", "days": best["days"]}


def pick_offer(cand):
    """Серед пропозицій ОРИГІНАЛУ (аналоги вже відсіяні у _autonova_code_best) обирає
    з НАЙМЕНШИМ терміном постачання; серед однаково швидких — найдешевшу. Оскільки
    наявна пропозиція має days<=1, вона автоматично випереджає «під замовлення».
    cand: [{price,qty,days,own}]."""
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


# --- пам'ять «під якою маркою шукати» (31.07) ---
# Кешується ТІЛЬКИ brandId, тобто ДЕ шукати. Ціна, наявність і термін
# НІКОЛИ не кешуються — вони щоразу тягнуться свіжими з autonova.
_BRAND_LOCK = threading.Lock()
_BRAND_MEMO = {}   # код (UPPER) -> brandId, під яким він знайшовся
_BRAND_HITS = {}   # brandId -> скільки разів влучив за цей прогін


def _memo_key(code):
    return str(code).strip().upper()


def _brand_reset():
    """Скидає пам'ять марок (для тестів і повторних прогонів у одному процесі)."""
    with _BRAND_LOCK:
        _BRAND_MEMO.clear()
        _BRAND_HITS.clear()


def _brand_hit(code, bid):
    with _BRAND_LOCK:
        _BRAND_MEMO[_memo_key(code)] = bid
        _BRAND_HITS[bid] = _BRAND_HITS.get(bid, 0) + 1


def _brand_order(code, all_brands):
    """Порядок перебору brandId для коду:
      1) марка, під якою цей код уже знайшовся раніше в цьому прогоні;
      2) підказка за форматом артикула (_autonova_brand_for);
      3) решта марок — найрезультативніші за цей прогін попереду.
    Результат перебору від порядку не залежить (перший, хто має ОРИГІНАЛ,
    виграє в будь-якому порядку) — змінюється лише кількість запитів."""
    with _BRAND_LOCK:
        memo = _BRAND_MEMO.get(_memo_key(code))
        hits = dict(_BRAND_HITS)
    head = []
    for b in (memo, _autonova_brand_for(code)):
        if b is not None and b not in head:
            head.append(b)
    rest = [b for b in all_brands if b not in head]
    rest.sort(key=lambda b: (-hits.get(b, 0), all_brands.index(b)))
    return head + rest


def _resolve_many(rows, cookie, all_brands, tag):
    """Резолвить пачку кодів у кілька потоків (AUTONOVA_WORKERS).
    rows — кортежі, де [0] = ключ (UPPER), [1] = код як у таблиці.
    Віддає (row, item|None) СТРОГО у вхідному порядку, тож подальший запис
    у таблицю лишається послідовним і в тому ж порядку, що й раніше.
    Виняток на одному коді не валить решту прогону."""
    workers = _autonova_workers()

    def one(row):
        try:
            return _resolve_autonova(row[1], cookie, all_brands)
        except Exception as e:
            print(f"[{tag}] {row[0]}: {type(e).__name__}: {str(e)[:80]}")
            return None

    if workers <= 1 or len(rows) <= 1:
        for row in rows:
            yield row, one(row)
        return
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for row, item in zip(rows, ex.map(one, rows)):
            yield row, item


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
    order = _brand_order(code, all_brands)
    res = None
    for bid in order:
        # пауз тут більше нема: темп тримає _rate_gate() всередині _autonova_fetch
        if len(sp) >= 2:
            acc = [_autonova_code_best(p, bid, cookie) for p in sp]
            if all(acc):
                res = acc
            elif acc and acc[0]:
                res = [acc[0]]
            if res:
                _brand_hit(code, bid)
                break
        else:
            r = _autonova_code_best(sp[0], bid, cookie)
            if r:
                res = [r]
                _brand_hit(code, bid)
                break
            if cand_whole and cand_whole != sp[0]:
                r2 = _autonova_code_best(cand_whole, bid, cookie)
                if r2:
                    res = [r2]
                    _brand_hit(code, bid)
                    break
            # base_rev-фолбек (зрізання кінцевої літери ревізії) ПРИБРАНО 24.07:
            # це ІНШИЙ номер (інша ревізія/деталь) -> порушує правило «тільки оригінал».
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
    todo, seen_k = [], set()
    for code in codes:
        if limit and len(todo) >= limit:
            break
        k = str(code).strip().upper()
        if k in seen_k:      # той самий код двічі — питати вдруге нема сенсу
            continue
        seen_k.add(k)
        todo.append((k, code))
    n_ok = n_avail = 0
    for (k, _code), item in _resolve_many(todo, cookie, all_brands, "autonova-web"):
        if not item:
            continue
        keep_best(best, k, item, instock)
        n_ok += 1
        if item["presence"] == "available":
            n_avail += 1
    print(f"[autonova-web] додано {n_ok} кодів (у наявності: {n_avail}) з {len(todo)} перевірених; "
          f"потоків {_autonova_workers()}")


def recheck_autonova_faster(codes, best, instock, cookie, on_upgrade=None):
    """КРОС-ПЕРЕВІРКА (власник, 24.07): позиції, що ВЖЕ мають постачальника з прайсів
    (BMW/Porsche/Drive/BMParts), але стоять «під замовлення», перевіряємо на autonova.
    Якщо autonova має код ШВИДШЕ (менший термін, зокрема в наявності) — замінюємо
    позицію на autonova (ціна+наявність+термін). «Найшвидший постачальник виграє»
    вже МІЖ джерелами. Ліміт AUTONOVA_RECHECK_LIMIT (0 = усі).

    Повертає список кодів (UPPER), які були прискорені/оновлені. on_upgrade(k) —
    необов'язковий колбек одразу після кожного апгрейду (для інкрементального запису
    в Export, щоб проміжний прогрес зберігся, навіть якщо прогін уб'ють на середині)."""
    if not cookie:
        print("[recheck] нема AUTONOVA_COOKIE — крос-перевірку пропущено")
        return []
    if not autonova_web_authorized(cookie):
        return []
    limit = int(num(os.environ.get("AUTONOVA_RECHECK_LIMIT") or 0))  # 0 = усі
    all_brands = _all_brands()
    # 1) відбір — ТІ САМІ правила, що й раніше, до єдиного запиту в autonova
    todo, seen_k = [], set()
    for code in codes:
        if limit and len(todo) >= limit:
            break
        k = str(code).strip().upper()
        if k in seen_k:
            continue
        cur = best.get(k)
        if not cur:
            continue
        lock = cur.get("lock")
        if lock is not None and lock <= 1:
            # ПРІОРИТЕТ ПРАЙСУ BMW: «наяв»/«чекати 2-3д» — ціна BMW перша,
            # autonova навіть не питаємо (див. sources/base.py)
            continue
        seen_k.add(k)
        cur_days = int(num(cur.get("days"))) if cur.get("days") is not None else 15
        todo.append((k, code, lock, cur_days))
    # 2) запити — паралельно; 3) рішення і запис — послідовно, у вхідному порядку,
    #    в головному потоці (on_upgrade пише в таблицю так само по одному)
    upgraded = []
    n_check = len(todo)
    n_up = n_avail = 0
    for (k, _code, lock, cur_days), item in _resolve_many(todo, cookie, all_brands, "recheck"):
        if not item:
            continue
        new_days = int(item.get("days") or 0)
        # autonova швидша -> беремо autonova; але BMW-«під замовлення» (lock=2)
        # віддаємо лише ШВИДКОМУ autonova (термін ≤5 днів), інакше ціна BMW лишається
        if new_days < cur_days and (lock is None or new_days <= 5):
            item["article"] = k
            best[k] = item
            if item["presence"] == "available" and item["qty"] > 0:
                instock[k] = int(item["qty"])
                n_avail += 1
            else:
                instock.pop(k, None)
            n_up += 1
            upgraded.append(k)
            if on_upgrade:
                try:
                    on_upgrade(k)
                except Exception as e:
                    print(f"[recheck] запис {k} не вдався: {str(e)[:80]}")
    print(f"[recheck] autonova крос-перевірка: {n_check} перевірено, {n_up} прискорено "
          f"(у наявності: {n_avail}); потоків {_autonova_workers()}")
    return upgraded
