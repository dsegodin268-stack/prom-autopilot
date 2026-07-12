#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""enrich_add.py — ПАКЕТНЕ додавання позицій з BM Parts у гейт підтвердження.
Джерело артикулів: обраний постачальник (BMW=таблиця дилера). Беремо N нових (яких ще нема в Export),
для кожного тягнемо картку з BM Parts (get_product) і будуємо ПОВНИЙ Prom-рядок (138 колонок).
Пишемо у «Staging_Prom» (повний рядок) + картку огляду в «Звіт додавання позицій» з чекбоксом.
Env: GCP_SA_KEY, BMPARTS_TOKEN, SUPPLIER, COUNT, ARTICLE(опц. тест)."""
import os, json, math, html, re, datetime, time

ID_HUB = "1pesHiOHDq2Y4FYQECakfhIJlq08bg5_Pkm9e2YEDoic"
PRODUCTS_TAB = os.environ.get("PRODUCTS_TAB", "Export Products Sheet")
STAGING_TAB  = os.environ.get("STAGING_TAB", "Staging_Prom")
REVIEW_TAB   = os.environ.get("REVIEW_TAB", "Звіт додавання позицій")

SUPPLIERS = {
    "BMW":     "1KXaDLqBsOAtX0MxUoX39jpia9boISxl1xUxPihhU77I",
    "PORSCHE": "1oVSVg1cBxGj-DA66c5_FoAtp6zOthdnF_xTY_ugez2g",
}

UA2RU = {
    "гальмівні":"тормозные","гальмівний":"тормозной","гальмівна":"тормозная","колодки":"колодки",
    "диск":"диск","диски":"диски","передні":"передние","передній":"передний","передня":"передняя",
    "задні":"задние","задній":"задний","фільтр":"фильтр","масляний":"масляный","повітряний":"воздушный",
    "паливний":"топливный","салону":"салона","амортизатор":"амортизатор","підшипник":"подшипник",
    "ремінь":"ремень","насос":"насос","радіатор":"радиатор","свічка":"свеча","свічки":"свечи",
    "важіль":"рычаг","опора":"опора","пильник":"пыльник","комплект":"комплект","зчеплення":"сцепление",
    "гумові":"резиновые","килимки":"коврики","килимок":"коврик","система":"система",
}
def ua2ru(t):
    def repl(m):
        w=m.group(0); r=UA2RU.get(w.lower())
        if not r: return w
        return r.capitalize() if w[:1].isupper() else r
    return re.sub(r"[А-Яа-яІіЇїЄєҐґ']+", repl, t or "")

def num(x):
    try: return float(str(x).replace(",",".").replace("\xa0","").replace(" ",""))
    except Exception: return 0.0

def final_price(cost):
    c=num(cost)
    if c<=0: return ""
    k=1.5 if c<3000 else 1.45 if c<5000 else 1.3 if c<10000 else 1.2 if c<30000 else 1.1
    return int(math.ceil(c*k))

def esc(s): return html.escape(str(s or ""))

def gclient():
    import gspread
    return gspread.service_account_from_dict(json.loads(os.environ["GCP_SA_KEY"]))

def find_ws(ss, name):
    key=lambda s: re.sub(r"[^a-z0-9]", "", str(s).lower())
    want=key(name)
    for w in ss.worksheets():
        if key(w.title)==want: return w
    return None

def col_idx(header, *names):
    low=[str(h).strip().lower() for h in header]
    for n in names:
        for i,h in enumerate(low):
            if h==n.lower(): return i
    for n in names:
        for i,h in enumerate(low):
            if n.lower() in h: return i
    return -1

def _type_phrase(name):
    toks=[]
    for w in (name or "").split():
        if re.match(r"^[A-Za-z0-9]", w): break
        toks.append(w)
        if len(toks)>=3: break
    t=re.sub(r"[()]"," "," ".join(toks))
    return re.sub(r"\s+"," ",t).strip()

def _car_tokens(name): return re.findall(r"[A-Za-z][A-Za-z0-9]+", name or "")

def _fitment(product, name):
    from bmparts import fitment_lines
    fit=fitment_lines(product)
    if fit: return fit
    toks=_car_tokens(name)
    if not toks: return []
    brand=toks[0]; models=[t for t in toks[1:] if re.match(r"^[A-Za-z]+\d", t)][:5]
    return [f"{brand} {m}" for m in models] or [brand]

def html_desc(product, lang):
    from bmparts import oem_and_replacements, parse_details
    name=(product.get("name") or "").strip().rstrip(".")
    oem, repl=oem_and_replacements(product); details=parse_details(product.get("details"))
    if lang=="ru":
        nm=ua2ru(name)
        L={"q":"оригинальное качество для вашего авто","fit":"Прямая замена изношенного узла, возвращает штатную работу.",
           "oem":"Оригинальный (OEM) номер","rep":"Аналоги / замена","ch":"Характеристики",
           "ship":"Отправка ежедневно. Гарантия соответствия.",
           "cta":"Не уверены, подойдёт ли именно на ваше авто? <strong>Мы подберём за вас</strong> — напишите марку, модель, год и VIN-код."}
    else:
        nm=name
        L={"q":"оригінальна якість для вашого авто","fit":"Пряма заміна зношеного вузла, відновлює штатну роботу.",
           "oem":"Оригінальний (OEM) номер","rep":"Аналоги / замінники","ch":"Характеристики",
           "ship":"Відправка щодня. Гарантія відповідності.",
           "cta":"Не впевнені, чи підійде саме на ваше авто? <strong>Ми підберемо за вас</strong> — напишіть марку, модель, рік і VIN-код."}
    p=[]
    p.append(f"<p>\U0001F697 <strong>{esc(nm)}</strong> — {L['q']}.</p>")
    p.append(f"<p>✅ {L['fit']}</p>")
    fitc=_fitment(product, name)
    if fitc:
        lab="Подходит на" if lang=="ru" else "Підходить на"
        p.append(f"<p>\U0001F50E <strong>{lab}:</strong> {esc(', '.join(fitc))}.</p>")
    if oem: p.append(f"<p>\U0001F527 <strong>{L['oem']}:</strong> {esc(', '.join(oem))}.</p>")
    if repl: p.append(f"<p>\U0001F501 <strong>{L['rep']}:</strong> {esc(', '.join(repl[:12]))}.</p>")
    if details:
        lis="".join(f"<li>{esc(ua2ru(n) if lang=='ru' else n)}: {esc(v)}{(' '+esc(u)) if u else ''}</li>" for (n,u,v) in details[:8])
        p.append(f"<p>\U0001F4CB <strong>{L['ch']}:</strong></p><ul>{lis}</ul>")
    p.append(f"<p>\U0001F4E6 {L['ship']}</p>")
    p.append(f"<p>❓ {L['cta']}</p>")
    return "".join(p)

def gen_keywords(product, lang):
    from bmparts import oem_and_replacements
    name=product.get("name") or ""; brand=product.get("brand") or ""; art=product.get("article") or ""
    oem, repl=oem_and_replacements(product); typ=_type_phrase(name)
    typ_l=ua2ru(typ) if lang=="ru" else typ; cars=_car_tokens(name); kws=[]
    def add(*xs):
        for x in xs:
            x=re.sub(r"\s+"," ",str(x)).strip()
            if x and x.lower() not in [k.lower() for k in kws]: kws.append(x)
    add(typ_l)
    if typ_l and brand: add(f"{typ_l} {brand}")
    if brand: add(brand, f"{brand} {art}")
    carbrand=cars[0] if cars else ""; models=[c for c in cars if c.lower()!=carbrand.lower()][:4]
    if carbrand: add(carbrand)
    for m in models:
        add(f"{carbrand} {m}")
        if typ_l: add(f"{typ_l} {carbrand} {m}")
    if typ_l and carbrand: add(f"{typ_l} {carbrand}")
    for o in oem[:6]: add(o)
    for r in repl[:6]: add(r.split()[-1] if r else r)
    add(art)
    return kws[:30]

def meta_title(product, lang):
    name=product.get("name") or ""; art=product.get("article") or ""
    t=re.sub(r"\s+"," ",(ua2ru(name) if lang=="ru" else name)).strip()
    if art and art not in t: t=f"{t} {art}"
    return t[:70]

def meta_desc(product, lang):
    from bmparts import oem_and_replacements
    name=product.get("name") or ""; oem,_=oem_and_replacements(product)
    base=ua2ru(name) if lang=="ru" else name
    o=(f" OEM {oem[0]}." if oem else "")
    tail=" Оригинал и аналоги, отправка ежедневно." if lang=="ru" else " Оригінал і аналоги, відправка щодня."
    return (base+o+tail)[:160]

def build_fields(product):
    from bmparts import clean_name, cdn_url, parse_details
    art=str(product.get("article") or "").strip()
    name_ua=clean_name(product.get("name")); name_ru=clean_name(ua2ru(product.get("name") or ""))
    imgs=[cdn_url(p) for p in (product.get("images") or [])]
    details=parse_details(product.get("details")); price=final_price(product.get("price"))
    f={"Код_товару":art,"Ідентифікатор_товару":art,
       "Назва_позиції":name_ru or name_ua,"Назва_позиції_укр":name_ua,
       "Пошукові_запити":", ".join(gen_keywords(product,"ru")),"Пошукові_запити_укр":", ".join(gen_keywords(product,"ua")),
       "Опис":html_desc(product,"ru"),"Опис_укр":html_desc(product,"ua"),
       "HTML_заголовок":meta_title(product,"ru"),"HTML_заголовок_укр":meta_title(product,"ua"),
       "HTML_опис":meta_desc(product,"ru"),"HTML_опис_укр":meta_desc(product,"ua"),
       "Ціна":price,"Валюта":"UAH","Одиниця_виміру":"шт.","Наявність":"+",
       "Виробник":product.get("brand") or "","Посилання_зображення":", ".join(imgs)}
    return f, name_ua, imgs, details, price

def supplier_articles(gc, supplier):
    sid=SUPPLIERS.get(supplier.upper())
    if not sid: print(f"[src] невідомий постачальник {supplier}"); return []
    out=[]; seen=set()
    try: ss=gc.open_by_key(sid)
    except Exception as e: print(f"[src] {supplier}: нема доступу {str(e)[:60]}"); return []
    for ws in ss.worksheets():
        try: vals=ws.get_all_values()
        except Exception: continue
        for r in vals:
            a=(r[0] if r else "").strip()
            if not a or not re.search(r"\d", a) or len(a)<4: continue
            u=a.upper()
            if u not in seen: seen.add(u); out.append(a)
    print(f"[src] {supplier}: {len(out)} унікальних артикулів")
    return out

def bm_get_retry(bm, art, tries=4):
    """get_product із повтором на тимчасовий 403/429 (rate-limit BM Parts). Бекоф 3/8/15/30 c."""
    delays=[3,8,15,30]
    for i in range(tries):
        try:
            return bm.get_product(art)
        except Exception as e:
            msg=str(e)
            if ("403" in msg or "429" in msg) and i < tries-1:
                print(f"[bm-retry] {art}: {msg[:45]} - пауза {delays[i]}c"); time.sleep(delays[i]); continue
            print(f"[bm] {art}: {msg[:60]}"); return None
    return None

def main():
    from bmparts import BMParts
    from validator import validate_card, summarize
    supplier=(os.environ.get("SUPPLIER","BMW") or "BMW").strip().upper()
    count=int(num(os.environ.get("COUNT","1")) or 1)
    only=os.environ.get("ARTICLE","").strip()
    gc=gclient(); ss=gc.open_by_key(ID_HUB)
    src=find_ws(ss, PRODUCTS_TAB)
    if src is None:
        print(f"[fatal] нема вкладки {PRODUCTS_TAB}. Наявні: {[w.title for w in ss.worksheets()]}"); return
    header=src.row_values(1)
    C=col_idx(header,"Код_товару"); C = C if C>=0 else 0
    print(f"=== Export: {len(header)} колонок, ключ у кол.{C+1} ===")

    have=set(a.strip().upper() for a in src.col_values(C+1)[1:] if a.strip())
    stg=find_ws(ss, STAGING_TAB)
    if stg is None:
        stg=ss.add_worksheet(title=STAGING_TAB, rows=200, cols=max(len(header),26)); stg.update(values=[header], range_name="A1"); staged=set()
    else:
        if stg.row_values(1)!=header:
            stg.resize(rows=max(stg.row_count,200), cols=len(header)); stg.update(values=[header], range_name="A1")
        staged=set(a.strip().upper() for a in stg.col_values(1)[1:] if a.strip())

    if only:
        candidates=[only]; count=1; print(f"[mode] ТЕСТ на 1 артикулі: {only}")
    else:
        candidates=[a for a in supplier_articles(gc, supplier) if a.upper() not in have and a.upper() not in staged]
        print(f"[mode] авто: постачальник {supplier}, треба {count} нових")

    bm=BMParts()
    stg_rows=[]; review_rows=[]; today=datetime.date.today().isoformat()
    scanned=0; cap=max(count*40, 60)
    for art in candidates:
        if len(stg_rows)>=count: break
        if scanned>=cap and not only: print(f"[scan] ліміт скану {cap}"); break
        scanned+=1
        time.sleep(0.8)                                    # тротлінг проти rate-limit BM Parts
        prod=bm_get_retry(bm, art)
        if not prod: continue
        fields,name_ua,imgs,details,price=build_fields(prod)
        full=[""]*len(header)
        for k,v in fields.items():
            i=col_idx(header,k)
            if i>=0: full[i]=v
        card={"name":fields["Назва_позиції_укр"],"description":fields["Опис_укр"],"chars":details,
              "images":imgs,"price":price,"product_id":fields["Ідентифікатор_товару"],"group_id":None}
        vs=summarize(validate_card(card, is_part=True))
        stg_rows.append(full)
        review_rows.append([art, name_ua, price, "+", len(imgs), len(details), vs, supplier, "нова", today, False])
        print(f"[add] {art} — {name_ua[:40]} | ціна {price} | фото {len(imgs)} | {vs}")

    if not stg_rows:
        print("[done] нових позицій із карткою BM Parts не знайдено"); return

    stg.append_rows(stg_rows, value_input_option="RAW")
    print(f"[staging] додано {len(stg_rows)} рядків")

    rhead=["Артикул","Назва","Ціна","Наявність","Фото","Характеристик","Валідатор","Постачальник","Статус","Дата","Підтвердити"]
    rv=find_ws(ss, REVIEW_TAB)
    if rv is None:
        rv=ss.add_worksheet(title=REVIEW_TAB, rows=400, cols=len(rhead)); rv.update(values=[rhead], range_name="A1")
    elif rv.row_values(1)!=rhead:
        rv.update(values=[rhead], range_name="A1")
    start=len(rv.col_values(1))+1
    rv.append_rows(review_rows, value_input_option="USER_ENTERED")
    conf=col_idx(rhead,"Підтвердити")
    ss.batch_update({"requests":[{"setDataValidation":{"range":{"sheetId":rv.id,"startRowIndex":1,"startColumnIndex":conf,"endColumnIndex":conf+1},"rule":{"condition":{"type":"BOOLEAN"},"showCustomUi":True}}}]})
    print(f"[review] {REVIEW_TAB}: додано {len(review_rows)} карток (з рядка {start}), чекбокс кол.{conf+1}")
    print(">>> Постав галку Підтвердити -> Apps Script копіює рядок зі Staging_Prom у Export.")

def _write_log(text):
    try:
        gc=gclient(); ss=gc.open_by_key(ID_HUB)
        lg=find_ws(ss,"Лог_додавання")
        if lg is None: lg=ss.add_worksheet(title="Лог_додавання", rows=50, cols=2)
        import datetime as _d
        lg.update(values=[["останній прогін "+_d.datetime.utcnow().isoformat()], [text[-45000:]]], range_name="A1")
    except Exception as e:
        print("[log] запис у вкладку не вдався:", str(e)[:80])

if __name__=="__main__":
    import io as _io, contextlib as _c, traceback as _tb
    _buf=_io.StringIO()
    try:
        with _c.redirect_stdout(_buf): main()
    except Exception:
        _buf.write("\nTRACEBACK:\n"+_tb.format_exc())
    _out=_buf.getvalue()
    print(_out)
    _write_log(_out)
