import json, datetime, sys; sys.path.insert(0,".")
from suppliers.excel import parse_excel
from engine.catalog import categorize
from engine.pricing import price_item
UP="/sessions/friendly-trusting-johnson/mnt/uploads/"
raw=parse_excel(UP+"Прайс Баварии Моторс 03.04.26(п).xlsx",{"article":0,"name":1,"qty":2,"cost":3},"BMW")
for fn in ["VAG склад.xlsx","VAG аксесуари.xlsx"]:
    raw+=parse_excel(UP+fn,{"article":0,"name":1,"qty":2,"cost":3},"VW/Audi")
best={}
for it in raw:
    a=it["article"]
    if a in best and it["cost"]>=best[a]["cost"]: continue
    best[a]=it
items=[]
for a,it in best.items():
    c=categorize(it["name"]); pr,mk=price_item(it["cost"],c)
    items.append({"a":a,"n":str(it["name"])[:60],"c":c,"cost":round(it["cost"]),"p":pr,
                  "mk":round(mk,2),"av":("in" if "наявн" in it["availability"] else "ord")})
from collections import Counter
cat=Counter(i["c"] for i in items); av=Counter(i["av"] for i in items)
def band(mk):
    return "×1.1-1.2" if mk<1.2 else "×1.2-1.3" if mk<1.3 else "×1.3-1.45" if mk<1.45 else "×1.45-1.5" if mk<1.5 else "×1.5+"
bands=Counter(band(i["mk"]) for i in items)
data={"generated":datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
 "kpi":{"total":len(items),"instock":av["in"],"order":av["ord"],
        "avg_markup":round(sum(i["mk"] for i in items)/len(items),2),"categories":len(cat)},
 "by_category":[{"cat":k,"count":v} for k,v in cat.most_common()],
 "availability":[{"k":"В наявності","v":av["in"]},{"k":"Під замовлення","v":av["ord"]}],
 "markup_bands":[{"k":k,"v":bands[k]} for k in ["×1.1-1.2","×1.2-1.3","×1.3-1.45","×1.45-1.5","×1.5+"]],
 "items":sorted(items,key=lambda x:-x["p"])[:400]}
open("dashboard/dashboard_data.json","w",encoding="utf-8").write(json.dumps(data,ensure_ascii=False))
print("dashboard_data.json:",len(items),"товарів |",dict(cat))
