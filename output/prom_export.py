"""Вивід у ТОЧНИЙ формат експорту/імпорту Prom (138 колонок). Індексна адресація,
бо назви колонок характеристик повторюються."""
import json, os, re, openpyxl
from engine.content import seo_fields, characteristics
_COLS=json.load(open(os.path.join(os.path.dirname(__file__),"prom_columns.json"),encoding="utf-8"))
_first={}
for i,c in enumerate(_COLS):
    _first.setdefault(c,i)
_TRIP=[i for i,c in enumerate(_COLS) if c=="Назва_Характеристики"]
def _clean(s): return re.sub(r'\s+',' ',str(s)).strip()
def _avail(a): return "+" if "наявн" in str(a).lower() else "-"
def item_to_row(it, group_id=""):
    row=[""]*len(_COLS)
    def S(col,val): row[_first[col]]=val
    nm=_clean(it["name"]); brand=it.get("brand","") if it.get("brand") not in ("multi","Авто") else ""
    seo=seo_fields(nm, brand, it["article"], it.get("category",""))
    S("Код_товару",it["article"]); S("Назва_позиції",seo["name_ua"]); S("Назва_позиції_укр",seo["name_ua"])
    S("Пошукові_запити_укр",seo["queries_ua"]); S("Опис_укр",seo["desc_ua"])
    S("HTML_заголовок_укр",seo["meta_title"]); S("HTML_опис_укр",seo["meta_desc"])
    S("Тип_товару","r"); S("Ціна",it["price"]); S("Валюта","UAH"); S("Одиниця_виміру","шт.")
    S("Наявність",_avail(it.get("availability"))); S("Кількість",it.get("qty") or "")
    S("Назва_групи",f'{brand} — {it.get("category","")}'.strip(" —"))
    if group_id: S("Номер_групи",group_id)
    if brand: S("Виробник",brand)
    if it.get("images"): S("Посилання_зображення",";".join(it["images"]))
    chs=characteristics(nm, brand, it.get("category",""))
    for k,(cn,un,val) in enumerate(chs):
        if k>=len(_TRIP): break
        b=_TRIP[k]; row[b]=cn; row[b+1]=un; row[b+2]=val
    return row
def save_xlsx(items, path, group_map=None):
    wb=openpyxl.Workbook(); ws=wb.active; ws.title="Export Products Sheet"; ws.append(_COLS)
    for it in items:
        gid=(group_map or {}).get(f'{it.get("brand","")} — {it.get("category","")}',"")
        ws.append(item_to_row(it, gid))
    wb.save(path); return len(items)
