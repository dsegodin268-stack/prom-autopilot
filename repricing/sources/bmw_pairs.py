# -*- coding: utf-8 -*-
"""Джерело 4: подвоєні BMW-номери (через дефіс) — пара реальних артикулів,
обидва вже є в BMW-аркушах (best). Без зовнішніх запитів."""
from common.normalize import num, _nkey, _expand_code
from repricing.sources.base import keep_best


def pull_pairs_from_best(codes, best, instock):
    """Для кодів без постачальника: (1) номер до тире як BMW-артикул (пара -> ×2);
    (1б) весь код як артикул; (2) пара половинок = сума собівартостей."""
    bnk = {}
    for k, v in best.items():
        bnk.setdefault(_nkey(k), v)

    def _add(code, cost, av, qty, brand):
        keep_best(best, str(code).strip().upper(),
                  {"name": "", "cost": cost, "qty": int(qty) if av else 0,
                   "presence": "available" if av else "order", "brand": brand}, instock)

    n_whole = n_pair = n_avail = 0
    unmatched = []
    for code in codes:
        first = str(code).split("-")[0].strip()
        f = bnk.get(_nkey(first)) if first else None
        if f is not None and num(f.get("cost")) > 0:
            is_pair = ("-" in str(code))
            av = (f.get("presence") == "available" and num(f.get("qty")) > 0)
            _add(code, num(f.get("cost")) * (2 if is_pair else 1), av, num(f.get("qty")),
                 "BMW-пара(×2)" if is_pair else "BMW")
            n_whole += 1
            if av:
                n_avail += 1
            continue
        w = bnk.get(_nkey(code))
        if w is not None and num(w.get("cost")) > 0:
            av = (w.get("presence") == "available" and num(w.get("qty")) > 0)
            _add(code, num(w.get("cost")), av, num(w.get("qty")), "BMW")
            n_whole += 1
            if av:
                n_avail += 1
            continue
        parts = _expand_code(code)
        if len(parts) >= 2:
            rec = [bnk.get(_nkey(p)) for p in parts]
            if all(x is not None for x in rec):
                cost = sum(num(x.get("cost")) for x in rec)
                if cost > 0:
                    av = all(x.get("presence") == "available" and num(x.get("qty")) > 0 for x in rec)
                    qty = min(int(num(x.get("qty"))) for x in rec) if av else 0
                    _add(code, cost, av, qty, "BMW-пара")
                    n_pair += 1
                    if av:
                        n_avail += 1
                    continue
        if len(unmatched) < 12:
            unmatched.append(code)
    print(f"[pairs] BMW з аркушів: ціле={n_whole}, пари={n_pair} (у наявності: {n_avail})")
    for code in unmatched:
        halves = [_nkey(h) for h in _expand_code(code)]
        print("[diag2]", code, "->", " | ".join(h + ("=IN" if h in bnk else "=NO") for h in halves))
