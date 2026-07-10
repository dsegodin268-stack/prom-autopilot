#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""VISIMICS AUTOPILOT — репрайсер каталогу Prom (єдиний файл, БЕЗ Prom API).
Джерела собівартості: BMW+Porsche (Google Sheets) + AutoNova (Drive/пошта).
Каталог і публікація — ТІЛЬКИ через вкладку «Export Products Sheet» у хабі
(її тягне Prom за URL-фідом). Пише три поля: Ціна(8), Наявність(15), Кількість(16).
Захист: MIN_MARKUP_ABS, MAX_DROP_PCT, ANCHOR_FLOOR (якір 30.06).
Реальний запис у таблицю лише при LIVE=1 (інакше DRY-RUN: рахує + звіт, не пише)."""
import os, json, io, math, imaplib, email, datetime

ID_BMW="1KXaDLqBsOAtX0MxUoX39jpia9boISxl1xUxPihhU77I"
ID_PORSCHE="1oVSVg1cBxGj-DA66c5_FoAtp6zOthdnF_xTY_ugez2g"
ID_HUB="1pesHiOHDq2Y4FYQECakfhIJlq08bg5_Pkm9e2YEDoic"
AUTONOVA_FROM="1c@autonovad.ua"
EXPORT_TAB="Export Products Sheet"        # ЄДИНЕ джерело каталогу і місце публікації (Prom тягне звідси)
# колонки формату експорту Prom (0-based)
C_CODE=0; C_NAME=1; C_PRICE=8; C_AVAIL=15; C_QTY=16
MARGIN_FLOOR=1.16
LIVE=os.environ.get("LIVE")=="1"          # LIVE=1 -> реально писати в Export; інакше DRY-RUN

def num(x):
    try: return float(str(x).replace(",",".").replace("\xa0","").replace(" ",""))
    except: return 0.0
# --- Захисні параметри ціноутворення (env-налаштовувані, щоб не лізти в код) ---
MIN_MARKUP_ABS=num(os.environ.get("MIN_MARKUP_ABS") or 150)      # мін. абсолютна націнка (грн) для дешевих позицій
MAX_DROP_PCT=num(os.environ.get("MAX_DROP_PCT") or 25)/100.0     # зниження діючої ціни > цього % без конкурента -> УТРИМАТИ (не писати)
ANCHOR_FLOOR=num(os.environ.get("ANCHOR_FLOOR") or 60)/100.0     # не писати ціну нижче цього % від якоря 30.06 без конкурента -> УТРИМАТИ
def load_anchor(path=None):
    """Якір реальних цін до поломки (export 30.06): article(UPPER)->price. CSV: article,anchor_price."""
    path=path or os.environ.get("ANCHOR_CSV") or "anchor_prices.csv"; m={}
    try:
        import csv as _csv
        with open(path, encoding="utf-8") as f:
            rd=_csv.reader(f); next(rd, None)
            for row in rd:
                if len(row)>=2:
                    a=str(row[0]).strip().upper(); p=num(row[1])
                    if a and p>0: m[a]=p
        print(f"[anchor] завантажено {len(m)} якірних цін із {path}")
    except FileNotFoundError:
        print(f"[anchor] {path} нема — якірний захист вимкнено")
    except Exception as e:
        print("[anchor]", str(e)[:80])
    return m
def final_price(cost):
    c=num(cost)
    if c<=0: return 0
    k=1.5 if c<3000 else 1.45 if c<5000 else 1.3 if c<10000 else 1.2 if c<30000 else 1.1
    return int(math.ceil(max(c*k, c+MIN_MARKUP_ABS)))   # +абсолютний мінімум націнки для дешевих
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
        from python_calamine import CalamineWorkbook
        cw=CalamineWorkbook.from_filelike(io.BytesIO(data))
        names=cw.sheet_names
        sh=cw.get_sheet_by_name("TDSheet") if "TDSheet" in names else cw.get_sheet_by_index(0)
        rows=sh.to_python(skip_empty_area=False); n=0
        for r in rows:
            if len(r)<=24 or r[2] in (None,""): continue
            cost=num(r[24])
            if cost<=0: continue
            qty=sum(num(r[c]) for c in range(5,23) if c<len(r))
            if qty<=0: continue
            keep_best(best,r[2],{"name":str(r[1] or ""),"cost":cost,"qty":qty,
                     "presence":"available","brand":"Авто"}, instock); n+=1
        print(f"[autonova] Drive '{files[0]['name']}': {n} поз.")
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

def read_export(gc):
    """Каталог Prom із вкладки «Export Products Sheet» (те, що тягне Prom).
    Повертає (ws, vals[2D, з паддінгом], idx: код(UPPER)->індекс рядка)."""
    ss=gc.open_by_key(ID_HUB)
    import re as _re
    keyf=lambda s:_re.sub(r"[^a-z0-9]","",str(s).lower())   # лишити тільки літери/цифри: стійко до пробілів/nbsp/невидимих символів/пунктуації
    want=keyf(EXPORT_TAB)
    ws=None
    for w in ss.worksheets():
        if keyf(w.title)==want: ws=w; break
    if ws is None:
        titles=[w.title for w in ss.worksheets()]
        print(f"[fatal] вкладку «{EXPORT_TAB}» не знайдено у хабі. Наявні вкладки: {titles}")
        raise SystemExit(2)
    print(f"[export] вкладка знайдена: «{ws.title}»")
    vals=ws.get_all_values()
    width=max(C_QTY+1, max((len(r) for r in vals), default=0))
    for r in vals:                                     # вирівняти ширину, щоб безпечно писати по індексах
        if len(r)<width: r.extend([""]*(width-len(r)))
    idx={}
    for i,r in enumerate(vals):
        if i==0: continue                              # заголовок
        code=str(r[C_CODE]).strip().upper()
        if code: idx[code]=i
    return ws, vals, idx

def write_report(gc, catalog, best, instock, overrides, comps, guard_status=None, final_price_map=None):
    """Вкладка «Звіт_Ціни» — ЖУРНАЛ: по кожному товару каталогу — поточна ціна,
    нова ціна робота, зміна %, наявність, джерело, статус (утримано/оновлено/нема постачальника)."""
    guard_status=guard_status or {}; final_price_map=final_price_map or {}
    head=["Артикул","Назва (Prom)","Ціна Prom","Ціна нова","Зміна %","Наявність","Кількість","Джерело","Собівартість","Статус"]
    rows=[head]
    for art,info in catalog.items():
        b=best.get(art)
        if b:
            newp=final_price_map.get(art)
            if newp is None:
                newp=overrides.get(art) or price_with_competitor(b["cost"], comps.get(art))
            cur=num(info.get("price"))
            chg=("%+.0f%%"%(100*(num(newp)-cur)/cur)) if cur>0 else ""
            aq=instock.get(art,0)
            pres="в наявності" if aq>0 else "під замовлення"
            qty=aq if aq>0 else ""
            rows.append([art, info.get("name",""), info.get("price",""), newp, chg, pres, qty,
                         b.get("brand",""), b.get("cost",""), guard_status.get(art,"оновлено")])
        else:
            rows.append([art, info.get("name",""), info.get("price",""), "", "", "", "", "", "", "НЕМА ПОСТАЧАЛЬНИКА"])
    ss=gc.open_by_key(ID_HUB)
    RTAB="Звіт_Ціни"                                    # окрема вкладка звіту цін (не плутати з карткою «Звіт»)
    ws=None
    for w in ss.worksheets():                           # знайти наявну БЕЗ огляду на регістр (фікс «already exists»)
        if w.title.strip().casefold()==RTAB.casefold(): ws=w; break
    if ws is None:
        ws=ss.add_worksheet(title=RTAB, rows=max(len(rows)+5,100), cols=len(head))
    ws.resize(rows=max(len(rows)+5,10), cols=len(head))
    ws.clear()
    ws.update(values=rows, range_name="A1")
    print(f"[report] {RTAB}: {len(rows)-1} рядків записано")

def main():
    gc=gclient()
    if not gc:
        print("[fatal] нема GCP_SA_KEY — без доступу до Google-таблиць працювати нема з чим"); return
    best={}; instock={}
    read_all_tabs(gc,ID_BMW,"BMW",best,instock)
    read_all_tabs(gc,ID_PORSCHE,"Porsche",best,instock,force="available")
    folder=os.environ.get("AUTONOVA_FOLDER_ID")
    if folder: pull_autonova_drive(folder,best,instock)   # шлях Drive (без пароля)
    else: pull_autonova(best,instock)                     # запасний шлях: пошта IMAP
    print(f"[supply] собівартість зібрано: {len(best)} артикулів, у наявності {len(instock)}")
    overrides=load_map(gc,"overrides"); comps=load_map(gc,"competitors"); anchor=load_anchor()

    ws, vals, idx = read_export(gc)                       # каталог = та вкладка, яку тягне Prom
    print(f"[export] каталог «{EXPORT_TAB}»: {len(idx)} кодів")

    only=os.environ.get("LIVE_ONLY")
    keep=set(a.strip().upper() for a in only.split(",") if a.strip()) if only else None
    catalog={}; guard_status={}; final_price_map={}; held=[]; changed=0
    for code,i in idx.items():
        row=vals[i]; cur=num(row[C_PRICE])
        catalog[code]={"name":row[C_NAME],"price":row[C_PRICE]}
        it=best.get(code)
        if not it: continue                              # нема постачальника — не чіпаємо рядок
        if keep and code not in keep: continue           # канарка LIVE_ONLY
        comp=comps.get(code); anc=anchor.get(code)
        newp=overrides.get(code) or price_with_competitor(it["cost"], comp)
        # ЯКІРНИЙ ЗАХИСТ: нижче ANCHOR_FLOOR% від реальної ціни 30.06 без конкурента -> УТРИМАТИ ціну
        if anc and anc>0 and newp<anc*ANCHOR_FLOOR and not (comp and comp>0) and code not in overrides:
            held.append((code,anc,newp)); guard_status[code]="УТРИМАНО: <%.0f%% якоря30.06 (было %.0f)"%(ANCHOR_FLOOR*100,anc)
            final_price_map[code]=int(cur) if cur>0 else ""; newp=None
        # ЗАХИСТ ВІД ЗАНИЖЕННЯ: без конкурента/override не опускаємо діючу; сильне зниження -> УТРИМАТИ
        elif cur>0 and newp<cur and not (comp and comp>0) and code not in overrides:
            if newp < cur*(1-MAX_DROP_PCT):
                held.append((code,cur,newp)); guard_status[code]="УТРИМАНО: -%.0f%% без конкурента"%(100*(1-newp/cur))
                final_price_map[code]=int(cur); newp=None
            else:
                newp=cur; guard_status[code]="тримаю діючу (без конкурента)"
        # наявність(+/дні) + кількість (консервативно: "в наявності" лише коли постачальник реально має склад)
        aq=instock.get(code,0)
        if aq>0: row[C_AVAIL]="+"; row[C_QTY]=int(aq)
        else:    row[C_AVAIL]="15"; row[C_QTY]=""        # під замовлення 15 днів, кількість порожня
        if newp is not None:                             # ціну пишемо лише якщо не утримано
            row[C_PRICE]=int(newp)
            final_price_map[code]=int(newp); guard_status.setdefault(code,"оновлено")
        changed+=1
    print(f"[calc] зіставлено з постачальником: {changed}, утримано {len(held)}")

    if LIVE:
        n=len(vals)
        colI=[[vals[r][C_PRICE]] for r in range(1,n)]
        colP=[[vals[r][C_AVAIL]] for r in range(1,n)]
        colQ=[[vals[r][C_QTY]]   for r in range(1,n)]
        ws.update(values=colI, range_name=f"I2:I{n}", value_input_option="RAW")
        ws.update(values=colP, range_name=f"P2:P{n}", value_input_option="RAW")
        ws.update(values=colQ, range_name=f"Q2:Q{n}", value_input_option="RAW")
        print(f"[export] ЗАПИСАНО в «{EXPORT_TAB}»: {changed} рядків (ціна/наявність/кількість). Prom підтягне фідом.")
    else:
        print(f"[export] DRY-RUN (LIVE≠1): у «{EXPORT_TAB}» НЕ писав. Приклади порахованого:")
        shown=0
        for code,i in idx.items():
            if code in final_price_map and str(final_price_map[code])!="" and shown<8:
                print(f"   {code}: ціна={vals[i][C_PRICE]} наяв={vals[i][C_AVAIL]} к-ть={vals[i][C_QTY]}"); shown+=1

    try: write_report(gc, catalog, best, instock, overrides, comps, guard_status, final_price_map)
    except Exception as e: print("[report]", str(e)[:140])
    if held:
        print("[guard] УТРИМАНІ (сильне зниження без конкурента, ціну НЕ чіпав; перші 30):")
        for a,c,nw in held[:30]: print(f"[guard]   {a}: {c:.0f} -> {nw:.0f}")

if __name__=="__main__": main()
