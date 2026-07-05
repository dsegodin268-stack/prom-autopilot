import yaml, os, sys
from engine.catalog import categorize, make_title
from engine.pricing import price_item, margin_after_commission
from suppliers.excel import parse_excel

def load_supplier(name, s, base):
    t=s.get("type")
    if t=="file":
        return parse_excel(os.path.join(base,s["path"]) if not os.path.isabs(s["path"]) else s["path"],
                           s.get("columns",{"article":0,"name":1,"qty":2,"cost":3}), s.get("brand",""), sheets=s.get("sheets"))
    if t=="email":
        from ingest.email_fetch import fetch_supplier_attachments; return fetch_supplier_attachments(name,s,base)
    if t=="api":
        from suppliers.bmparts_api import fetch_bmparts; return fetch_bmparts(s)
    return []

def run(cfgpath):
    cfg=yaml.safe_load(open(cfgpath,encoding="utf-8")); shop=cfg["shop"]; markup=cfg["markup"]; comm=shop.get("commission",0.08)
    base=os.path.dirname(os.path.abspath(cfgpath)); best={}
    for name,s in cfg["suppliers"].items():
        raw=load_supplier(name,s,base); print(f"[{name}] {len(raw)} позицій")
        for it in raw:
            a=it["article"]
            if a in best and it["cost"]>=best[a]["cost"]: continue
            best[a]=it
    items=[]
    for a,it in best.items():
        cat=categorize(it["name"]); price,mk=price_item(it["cost"],cat,markup)
        items.append({"article":a,"name":make_title(it["name"],it["brand"],a,cat),"price":price,
                      "availability":it["availability"],"brand":(it["brand"] if it["brand"]!="multi" else "Авто"),
                      "category":cat,"cost":it["cost"],"markup":mk,
                      "margin":margin_after_commission(price,it["cost"],comm),"description":""})
    gs=cfg.get("google_sheet")
    if gs and gs.get("sheet_id","").strip() and gs.get("sheet_id")!="PUT_SHEET_ID":
        from ingest.sheets_sync import sync; items=sync(items, gs)
    else:
        for it in items: it["publish"]=True
    items=[i for i in items if i.get("publish",True)]
    from output.prom_yml import build_yml
    yml=build_yml(shop, items); outp=os.path.join(base,cfg["output"]["yml_path"])
    os.makedirs(os.path.dirname(outp),exist_ok=True); open(outp,"w",encoding="utf-8").write(yml)
    print(f"\n[OK] YML-фід: {outp} | офферів: {len(items)} | розмір: {os.path.getsize(outp)//1024} КБ")
    from collections import Counter
    print("категорії:",dict(Counter(i['category'] for i in items)))
    return items

if __name__=="__main__":
    run(sys.argv[1] if len(sys.argv)>1 else "config.yaml")
