#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""VISIMICS AUTOPILOT — репрайсер каталогу Prom (єдиний самодостатній файл).
Джерела: BMW+Porsche (Google Sheets, service account) + AutoNova (пошта).
Ціна = тарифна націнка; ручні правки й конкуренти з хаб-листа; пуш у Prom API.
DRY-RUN за замовчуванням (LIVE!=1 => нічого не змінює, лише лог).

Секрети (GitHub Secrets/Variables):
  GCP_SA_KEY, MAIL_USER, MAIL_PASS, PROM_API_KEY, і змінна LIVE=1 для бойового пушу.
"""
import os, json, time, io, math, imaplib, email, datetime, urllib.request, urllib.error

ID_BMW="1KXaDLqBsOAtX0MxUoX39jpia9boISxl1xUxPihhU77I"
ID_PORSCHE="1oVSVg1cBxGj-DA66c5_FoAtp6zOthdnF_xTY_ugez2g"
ID_HUB="1pesHiOHDq2Y4FYQECakfhIJlq08bg5_Pkm9e2YEDoic"
AUTONOVA_FROM="1c@autonovad.ua"
PROM_API="https://my.prom.ua/api/v1/products/edit_by_external_id"
MARGIN_FLOOR=1.16
LIVE=os.environ.get("LIVE")=="1"

def num(x):
    try: return float(str(x).replace(",",".").replace("\xa0","").replace(" ",""))
    except: return 0.0

def final_price(cost):
    c=num(cost)
    if c<=0: return 0
    k=1.5 if c<3000 else 1.45 if c<5000 else 1.3 if c<10000 else 1.2 if c<30000 else 1.1
    return int(math.ceil(c*k))

def price_with_competitor(cost, comp):
    base=final_price(cost)
    if not comp or comp<=0: return base
    floor=int(math.ceil(num(cost)*MARGIN_FLOOR)); target=int(comp)-1
    return target if (target>=floor and target<base) else base

def keep_best(best, art, item):
    k=str(art).strip().upper()
    if not k: return
    if k not in best or item["cost"]<best[k]["cost"]:
        item["article"]=k; best[k]=item

def _norm(x): return "".join(str(x).lower().split())

def gclient():
    key=os.environ.get("GCP_SA_KEY")
    if not key: return None
    import gspread
    return gspread.service_account_from_dict(json.loads(key)) if key.strip().startswith("{") else None

def read_all_tabs(gc, sid, brand, best, force=None):
    try:
        ss=gc.open_by_key(sid)
    except Exception as e:
        print(f"[sheet] {brand}: OPEN FAIL {str(e)[:80] or 'нема доступу (розшар на сервіс-акаунт)'}"); return
    for ws in ss.worksheets():
        title=ws.title; nt=_norm(title)
        if force: presence=force
        elif "наяв" in nt: presence="available"
        elif any(k in nt for k in ["чека","2-3","2–3","23дн","замов","15дн","15днів","підзам"]): presence="order"
        else: presence="available"
        try: rows=ws.get_all_values()
        except Exception as e: print(f"[sheet] {brand}/{title}: READ FAIL {str(e)[:60]}"); continue
        n=0
        for r in rows:
            if len(r)<4: continue
            art=(r[0] or "").strip(); cost=num(r[3])
            if not art or cost<=0: continue
            keep_best(best, art, {"name":r[1],"cost":cost,"qty":num(r[2]),"presence":presence,"brand":brand}); n+=1
        print(f"[sheet] {brand}/{title}: {n} поз. ({presence})")

def pull_autonova(best):
    user=os.environ.get("MAIL_USER"); pw=os.environ.get("MAIL_PASS")
    if not user or not pw: print("[autonova] нема MAIL_USER/PASS — пропуск"); return
    try:
        import openpyxl
        M=imaplib.IMAP4_SSL("imap.gmail.com"); M.login(user,pw); M.select("INBOX")
        since=(datetime.date.today()-datetime.timedelta(days=14)).strftime("%d-%b-%Y")
        _,data=M.search(None, f'(FROM "{AUTONOVA_FROM}" SINCE {since})')
        for numid in reversed(data[0].split()):
            _,d=M.fetch(numid,"(RFC822)"); msg=email.message_from_bytes(d[0][1]); done=False
            for part in msg.walk():
                fn=part.get_filename() or ""
                if fn.lower().endswith((".xlsx",".xls")):
                    wb=openpyxl.load_workbook(io.BytesIO(part.get_payload(decode=True)),read_only=True,data_only=True)
                    sh=wb["TDSheet"] if "TDSheet" in wb.sheetnames else wb[wb.sheetnames[0]]; n=0
                    for r in sh.iter_rows(values_only=True):
                        if not r or len(r)<=24 or r[2] is None: continue
                        cost=num(r[24])
                        if cost<=0: continue
                        qty=sum(num(r[c]) for c in range(5,23) if c<len(r))
                        if qty<=0: continue
                        keep_best(best,r[2],{"name":str(r[1] or ""),"cost":cost,"qty":qty,"presence":"available","brand":"Авто"}); n+=1
                    wb.close(); done=True; print(f"[autonova] {n} поз.")
            if done: break
        M.logout()
    except Exception as e: print(f"[autonova] {str(e)[:100]}")

def load_map(gc, tab):
    m={}
    try:
        for r in gc.open_by_key(ID_HUB).worksheet(tab).get_all_values()[1:]:
            if len(r)<2: continue
            a=(r[0] or "").strip().upper(); p=num(r[1])
            if a and p>0: m[a]=p
    except Exception as e: print(f"[{tab}] {str(e)[:50]}")
    return m

def presence_val(av, qty):
    a=(av or "").lower()
    if "наяв" in a or av=="available": return "available"
    if "замов" in a or av=="order": return "order"
    return "available" if num(qty)>0 else "order"

def push_prom(payload):
    token=os.environ.get("PROM_API_KEY")
    if not token or not LIVE:
        print(f"[prom] DRY-RUN: {len(payload)} товарів НЕ надіслано (LIVE={LIVE}, token={'є' if token else 'нема'})")
        print("[prom] приклад:", json.dumps(payload[:3], ensure_ascii=False)); return
    ok=err=0
    for i in range(0,len(payload),100):
        chunk=payload[i:i+100]
        req=urllib.request.Request(PROM_API,data=json.dumps(chunk).encode(),
            headers={"Authorization":"Bearer "+token,"Content-Type":"application/json"},method="POST")
        try:
            with urllib.request.urlopen(req,timeout=60) as rr: json.loads(rr.read().decode()); ok+=len(chunk)
        except urllib.error.HTTPError as e: err+=1; print("[prom] HTTP",e.code,e.read().decode()[:150])
        except Exception as e: err+=1; print("[prom]",str(e)[:120])
        time.sleep(1)
    print(f"[prom] надіслано ~{ok}, помилок-батчів {err}")

def main():
    gc=gclient(); best={}
    if gc:
        read_all_tabs(gc,ID_BMW,"BMW",best)                 # вкладки за назвою (наяв/чекати/15днів)
        read_all_tabs(gc,ID_PORSCHE,"Porsche",best,force="available")  # усі вкладки = в наявності
    else:
        print("[gsheet] нема GCP_SA_KEY — таблиці постачальників пропущені")
    pull_autonova(best)
    overrides=load_map(gc,"overrides") if gc else {}
    comps=load_map(gc,"competitors") if gc else {}
    payload=[]
    for art,it in best.items():
        price=overrides.get(art) or price_with_competitor(it["cost"],comps.get(art))
        payload.append({"id":art,"price":float(price),"presence":presence_val(it["presence"],it["qty"]),
                        "quantity_in_stock":int(it["qty"]) if it["qty"] else 0,"status":"on_display"})
    print(f"[main] позицій до пушу: {len(payload)}")
    lim=os.environ.get("LIVE_LIMIT")
    if lim:
        try:
            payload=payload[:int(lim)]
            print(f"[main] LIVE_LIMIT={lim} — КАНАРКА: обмежено до {len(payload)} товарів")
        except: pass
    push_prom(payload)

if __name__=="__main__": main()
