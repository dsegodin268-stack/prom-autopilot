# -*- coding: utf-8 -*-
"""Джерело 4: добір по нормалізованому ключу з уже зібраних прайсів
(без зовнішніх запитів). Дві РІЗНІ речі, чесно розділені:

  * збіг ЦІЛОГО кода за ключем (без пробілів/рисок/слешів) — працює для
    будь-якого бренду; у «Джерело» йде СПРАВЖНІЙ донор + «(ключ)». Раніше
    все підписувалося «BMW», і звіт брехав (коврики Audi «з прайсу BMW»);

  * BMW-ПАРИ — подвоєні номери через дефіс (…107-108 = ліва+права деталь):
    ×2 по першій половині або сума половинок. Дозволено ЛИШЕ коли обидві
    половини — справжні BMW-номери (11 цифр), щоб чужий артикул з рискою
    (напр. 19-045771) ніколи не отримав подвоєну ціну."""
from common.normalize import num, _nkey, _expand_code
from repricing.sources.base import keep_best


def _bmw_pair_parts(code):
    """['51117303107','51117303108'] якщо код — справжня BMW-пара, інакше []."""
    if "-" not in str(code):
        return []
    parts = _expand_code(code)
    if len(parts) >= 2 and all(p.isdigit() and len(p) == 11 for p in parts):
        return parts
    return []


def pull_pairs_from_best(codes, best, instock):
    """Для кодів без постачальника: (1) цілий код за ключем (чесний донор);
    (2) BMW-пара: перша половина ×2 або сума половинок."""
    bnk = {}
    for k, v in best.items():
        bnk.setdefault(_nkey(k), v)

    def _add(code, cost, av, qty, brand, days=0):
        keep_best(best, str(code).strip().upper(),
                  {"name": "", "cost": cost, "qty": int(qty) if av else 0, "days": int(days or 0),
                   "presence": "available" if av else "order", "brand": brand}, instock)

    n_whole = n_pair = n_avail = 0
    unmatched = []
    for code in codes:
        w = bnk.get(_nkey(code))
        if w is not None and num(w.get("cost")) > 0:
            av = (w.get("presence") == "available" and num(w.get("qty")) > 0)
            _add(code, num(w.get("cost")), av, num(w.get("qty")),
                 f"{w.get('brand') or '?'} (ключ)", days=num(w.get("days")))
            n_whole += 1
            if av:
                n_avail += 1
            continue
        parts = _bmw_pair_parts(code)
        if parts:
            f = bnk.get(_nkey(parts[0]))
            if f is not None and num(f.get("cost")) > 0:
                av = (f.get("presence") == "available" and num(f.get("qty")) > 0)
                _add(code, num(f.get("cost")) * 2, av, num(f.get("qty")),
                     "BMW-пара(×2)", days=num(f.get("days")))
                n_pair += 1
                if av:
                    n_avail += 1
                continue
            rec = [bnk.get(_nkey(p)) for p in parts]
            if all(x is not None for x in rec):
                cost = sum(num(x.get("cost")) for x in rec)
                if cost > 0:
                    av = all(x.get("presence") == "available" and num(x.get("qty")) > 0 for x in rec)
                    qty = min(int(num(x.get("qty"))) for x in rec) if av else 0
                    days = max(int(num(x.get("days"))) for x in rec)  # обидві половини мають приїхати
                    _add(code, cost, av, qty, "BMW-пара", days=days)
                    n_pair += 1
                    if av:
                        n_avail += 1
                    continue
        if len(unmatched) < 12:
            unmatched.append(code)
    print(f"[pairs] добір за ключем: ціле={n_whole}, BMW-пари={n_pair} (у наявності: {n_avail})")
    for code in unmatched:
        halves = [_nkey(h) for h in _expand_code(code)]
        print("[diag2]", code, "->", " | ".join(h + ("=IN" if h in bnk else "=NO") for h in halves))
