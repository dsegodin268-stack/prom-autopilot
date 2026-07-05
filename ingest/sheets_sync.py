"""Google Sheet — людський шар override поверх авто-значень.
Движок пише АВТО-колонки й додає нові товари; людина редагує РУЧНІ колонки.
Фінал = ручне, якщо заповнене, інакше авто. Ручне ніколи не затирається.
Колонки: Артикул | Назва_авто | Назва_ручна | Ціна_авто | Ціна_ручна | Собівартість |
         Наявність | Категорія | Маржа | Статус | Нотатка
Статус: '' або 'публікувати' → у фід; 'сховати'/'stop' → не у фід; 'новий' → на модерацію.
"""
import os, json
AUTO=["Назва_авто","Ціна_авто","Собівартість","Наявність","Категорія","Маржа"]
def _client(gcfg):
    key=os.environ.get(gcfg.get("sa_key_env","GCP_SA_KEY"))
    if not key: return None
    import gspread
    info=json.loads(key) if key.strip().startswith("{") else None
    return gspread.service_account_from_dict(info) if info else gspread.service_account(filename=key)
def sync(items, gcfg):
    """Повертає items з полями name/price=ФІНАЛ + publish. Апсертить таблицю."""
    gc=None
    try: gc=_client(gcfg)
    except Exception as e: print("[sheets] помилка клієнта:",e)
    if not gc:
        print("[sheets] немає доступу — фінал = авто (ручний шар неактивний)")
        for it in items: it["publish"]=True
        return items
    sh=gc.open_by_key(gcfg["sheet_id"]); ws=sh.worksheet(gcfg.get("worksheet","catalog"))
    rows=ws.get_all_records()
    man={str(r.get("Артикул")): r for r in rows}
    hdr=["Артикул","Назва_авто","Назва_ручна","Ціна_авто","Ціна_ручна","Собівартість","Наявність","Категорія","Маржа","Статус","Нотатка"]
    if not rows: ws.update([hdr])
    new_rows=[]
    for it in items:
        r=man.get(it["article"],{})
        mp=r.get("Ціна_ручна"); mn=r.get("Назва_ручна"); st=str(r.get("Статус","")).strip().lower()
        it["price"]=int(mp) if str(mp).strip() not in ("","None","0") else it["price"]
        it["name"]=mn if str(mn).strip() else it["name"]
        it["publish"]= st not in ("сховати","stop","hide","приховати")
        if it["article"] not in man:  # новий товар → рядок на модерацію
            new_rows.append([it["article"],it["name"],"",it["price"],"",it["cost"],it["availability"],it["category"],it["margin"],"новий",""])
    if new_rows: ws.append_rows(new_rows, value_input_option="RAW")
    print(f"[sheets] прочитано {len(rows)} рядків, додано нових {len(new_rows)}")
    return items
