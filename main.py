#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""VISIMICS AUTOPILOT — репрайсер каталогу Prom (єдиний файл).
Джерела: BMW+Porsche (Google Sheets) + AutoNova (пошта). Ціна = тарифна націнка.
Матч із Prom по артикулу (поле sku), пуш по ВНУТРІШНЬОМУ id через /products/edit.
DRY-RUN за замовчуванням (LIVE!=1)."""
import os, json, time, io, math, imaplib, email, datetime, urllib.request, urllib.error

ID_BMW="1KXaDLqBsOAtX0MxUoX39jpia9boISxl1xUxPihhU77I"
ID_PORSCHE="1oVSVg1cBxGj-DA66c5_FoAtp6zOthdnF_xTY_ugez2g"
ID_HUB="1pesHiOHDq2Y4FYQECakfhIJlq08bg5_Pkm9e2YEDoic"
AUTONOVA_FROM="1c@autonovad.ua"
API_BASE="https://my.prom.ua/api/v1"
PROM_EDIT=API_BASE+"/products/edit"          # редагування по ВНУТРІШНЬОМУ id
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
def keep_best(best, art, item, instock):
    k=str(art).strip().upper()
    if not k: return
    if item.get("presence")=="available" and num(item.get("qty"))>0:   # пріоритет "в наявності"
        instock[k]=max(instock.get(k,0), int(num(item.get("qty"))))
    if k not in best or item["cost"]<best[k]["cost"]:
        item["article"]=k; best[k]=item
def _norm(x): return "".join(str(x).lower().split())
def gclient():
    key=os.environ.get("GCP_SA_KEY")
    if not key: return None
    import gspread
    return gspread.service_account_from_dict(json.loads(key)) if key.strip().startswith("{") else None

def read_all_tabs(gc, sid, brand, best, instock, force=None):
    try: ss=gc.open_by_key(sid)
    except Exception as e: print(f"[sheet] {brand}: OPEN FAIL {str(e)[:80] or 'нема доступу'}"); return
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
            if len(r)<3: continue
            art=(r[0] or "").strip()
            if not art: continue
            cost=num(r[3]) if len(r)>=4 else 0
            if cost>0: qty=num(r[2])
            else: cost=num(r[2]); qty=0
            if cost<=0: continue
            keep_best(best, art, {"name":r[1],"cost":cost,"qty":qty,"presence":presence,"brand":brand}, instock); n+=1
        print(f"[sheet] {brand}/{title}: {n} поз. ({presence})")

def pull_autonova(best, instock):
    user=os.environ.get("MAIL_USER"); pw=os.environ.get("MAIL_PASS")
    if not user or not pw: print("[autonova] нема MAIL_USER/PASS — пропуск"); return
    try:
        import openpyxl
        M=imaplib.IMAP4_SSL("imap.gmail.com"); M.login(user,pw); M.select("INBOX")
        since=(datetime.date.today()-datetime.timedelta(days=14)).strftime("%d-%b-%Y")
        _,data=M.search(None, f'(FROM "{AUTONOVA_FROM}" SINCE {since})'); ids=data[0].split()
        if not ids: print("[autonova] листів нема за 14 днів"); M.logout(); return
        for numid in reversed(ids):
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
                        keep_best(best,r[2],{"name":str(r[1] or ""),"cost":cost,"qty":qty,"presence":"available","brand":"Авто"}, instock); n+=1
                    wb.close(); done=True; print(f"[autonova] {n} поз.")
            if done: break
        M.logout()
    except Exception as e: print(f"[autonova] {str(e)[:120]}")

def _open_xlsx_tolerant(data):
    """Відкриває xlsx; якщо 1С-файл без xl/sharedStrings.xml — додає порожній і пробує ще раз."""
    import openpyxl, zipfile
    try:
        return openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:
        zin=zipfile.ZipFile(io.BytesIO(data)); buf=io.BytesIO()
        zout=zipfile.ZipFile(buf,"w",zipfile.ZIP_DEFLATED)
        for it in zin.namelist(): zout.writestr(it, zin.read(it))
        if "xl/sharedStrings.xml" not in zin.namelist():
            zout.writestr("xl/sharedStrings.xml",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="0" uniqueCount="0"/>')
        zout.close(); zin.close()
        return openpyxl.load_workbook(io.BytesIO(buf.getvalue()), read_only=True, data_only=True)

def pull_autonova_drive(folder_id, best, instock):
    """Читає найсвіжіший прайс Autonova з Drive-теки (її наповнює Apps Script)
    через сервіс-акаунт. Без IMAP/пароля. Підтримує zip-архів і xlsx."""
    folder_id=(folder_id or "").strip()
    if "/folders/" in folder_id:                  # приймаємо і повний URL теки, не лише ID
        folder_id=folder_id.split("/folders/")[1].split("?")[0].split("#")[0].split("/")[0]
    key=os.environ.get("GCP_SA_KEY")
    if not key: print("[autonova] нема GCP_SA_KEY — пропуск Drive"); return
    try:
        import openpyxl
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build
        creds=Credentials.from_service_account_info(json.loads(key),
              scopes=["https://www.googleapis.com/auth/drive.readonly"])
        svc=build("drive","v3",credentials=creds,cache_discovery=False)
        q="'%s' in parents and trashed=false and name contains 'autonova_latest'"%folder_id
        files=svc.files().list(q=q,fields="files(id,name,modifiedTime,size)",
              orderBy="modifiedTime desc",pageSize=5,
              supportsAllDrives=True,includeItemsFromAllDrives=True).execute().get("files",[])
        if not files: print("[autonova] у Drive-теці файлів нема"); return
        fn=files[0]["name"].lower()
        data=svc.files().get_media(fileId=files[0]["id"]).execute()
        if fn.endswith(".zip"):                       # прайс приходить архівом → розпакувати
            import zipfile
            zf=zipfile.ZipFile(io.BytesIO(data))
            inner=[m for m in zf.namelist() if m.lower().endswith((".xlsx",".xls"))]
            if not inner: print("[autonova] у zip нема xlsx"); return
            data=zf.read(inner[0])
        elif fn.endswith(".rar"):
            print("[autonova] .rar не підтримується — треба zip"); return
        wb=_open_xlsx_tolerant(data)
        sh=wb["TDSheet"] if "TDSheet" in wb.sheetnames else wb[wb.sheetnames[0]]; n=0
        for r in sh.iter_rows(values_only=True):
            if not r or len(r)<=24 or r[2] is None: continue
            cost=num(r[24])
            if cost<=0: continue
            qty=sum(num(r[c]) for c in range(5,23) if c<len(r))
            if qty<=0: continue
            keep_best(best,r[2],{"name":str(r[1] or ""),"cost":cost,"qty":qty,
                     "presence":"available","brand":"Авто"}, instock); n+=1
        wb.close(); print(f"[autonova] Drive '{files[0]['name']}': {n} поз.")
    except Exception as e:
        print(f"[autonova] Drive {str(e)[:140]}")

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

def _prom_get(token, url):
    req=urllib.request.Request(url, headers={"Authorization":"Bearer "+token})
    with urllib.request.urlopen(req, timeout=60) as r: return json.loads(r.read().decode())

def prom_group_ids(token):
    """Усі id груп товарів на Prom (+ None = базовий список без групи)."""
    ids=[None]; last=None
    for _ in range(300):
        url=API_BASE+"/groups/list?limit=100"+(f"&last_id={last}" if last else "")
        try: data=_prom_get(token,url)
        except Exception as e: print("[prom-groups]", str(e)[:100]); break
        gs=data.get("groups", data) if isinstance(data,dict) else data
        if not gs: break
        for grp in gs:
            gid=grp.get("id")
            if gid is not None: ids.append(gid); last=gid
        if len(gs)<100: break
        time.sleep(0.15)
    return ids

def prom_id_map(token):
    """Мапа артикул(sku|external_id, UPPER) -> внутрішній id. Обхід усіх груп."""
    m={}; gids=prom_group_ids(token); print(f"[prom] груп знайдено: {len(gids)-1}")
    for gid in gids:
        last=None
        for _ in range(600):
            url=API_BASE+"/products/list?limit=100"+(f"&group_id={gid}" if gid is not None else "")+(f"&last_id={last}" if last else "")
            try: data=_prom_get(token,url)
            except urllib.error.HTTPError as e: print("[prom-list] HTTP",e.code,e.read().decode()[:120]); break
            except Exception as e: print("[prom-list]", str(e)[:100]); break
            prods=data.get("products", data) if isinstance(data,dict) else data
            if not prods: break
            for p in prods:
                pid=p.get("id")
                if pid is None: continue
                for key in (p.get("sku"), p.get("external_id")):
                    k=str(key or "").strip().upper()
                    if k: m[k]=pid
                last=pid
            if len(prods)<100: break
            time.sleep(0.1)
    return m

def push_prom(payload):
    token=os.environ.get("PROM_API_KEY")
    if not token or not LIVE:
        print(f"[prom] DRY-RUN: {len(payload)} товарів НЕ надіслано (LIVE={LIVE}, token={'є' if token else 'нема'})")
        print("[prom] приклад:", json.dumps(payload[:3], ensure_ascii=False)); return
    ok=err=0
    for i in range(0,len(payload),100):
        chunk=payload[i:i+100]
        req=urllib.request.Request(PROM_EDIT,data=json.dumps(chunk).encode(),
            headers={"Authorization":"Bearer "+token,"Content-Type":"application/json"},method="POST")
        try:
            with urllib.request.urlopen(req,timeout=60) as rr: json.loads(rr.read().decode()); ok+=len(chunk)
        except urllib.error.HTTPError as e: err+=1; print("[prom] HTTP",e.code,e.read().decode()[:150])
        except Exception as e: err+=1; print("[prom]",str(e)[:120])
        time.sleep(1)
    print(f"[prom] надіслано ~{ok}, помилок-батчів {err}")

def main():
    gc=gclient(); best={}; instock={}
    if gc:
        read_all_tabs(gc,ID_BMW,"BMW",best,instock)
        read_all_tabs(gc,ID_PORSCHE,"Porsche",best,instock,force="available")
    else: print("[gsheet] нема GCP_SA_KEY — таблиці пропущені")
    folder=os.environ.get("AUTONOVA_FOLDER_ID")
    if folder: pull_autonova_drive(folder,best,instock)   # шлях Drive (без пароля)
    else: pull_autonova(best,instock)                     # запасний шлях: пошта IMAP
    overrides=load_map(gc,"overrides") if gc else {}
    comps=load_map(gc,"competitors") if gc else {}
    items=[]
    for art,it in best.items():
        price=overrides.get(art) or price_with_competitor(it["cost"],comps.get(art))
        aq=instock.get(art,0)                      # пріоритет "в наявності"
        items.append({"article":art,"price":float(price),
                      "presence":"available" if aq>0 else "order","qty":aq})
    print(f"[main] прораховано: {len(items)} товарів")
    token=os.environ.get("PROM_API_KEY")
    only=os.environ.get("LIVE_ONLY"); lim=os.environ.get("LIVE_LIMIT")
    if only:
        keep=set(a.strip().upper() for a in only.split(",") if a.strip())
        items=[p for p in items if p["article"] in keep]
        print(f"[main] LIVE_ONLY канарка: {len(items)} артикулів")
    payload=[]
    if token and os.environ.get("SKIP_PROM_FILTER")!="1":
        idmap=prom_id_map(token)
        if idmap:
            for it in items:
                pid=idmap.get(it["article"])
                if pid is not None:
                    payload.append({"id":int(pid),"price":it["price"],"presence":it["presence"],
                                    "quantity_in_stock":it["qty"],"status":"on_display"})
            print(f"[main] on-Prom: {len(idmap)} товарів на Prom -> збіглось {len(payload)} (з {len(items)})")
        else:
            print("[main] on-Prom мапа порожня/недоступна — пуш скасовано (безпека)")
    else:
        print("[main] нема токена / SKIP — без мапи id пуш неможливий")
    if lim:
        try: payload=payload[:int(lim)]; print(f"[main] LIVE_LIMIT: {len(payload)}")
        except: pass
    print(f"[main] до пушу: {len(payload)}")
    push_prom(payload)

if __name__=="__main__": main()
