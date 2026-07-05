import xml.sax.saxutils as su, datetime
def build_yml(shop, items):
    """items: list of dict(article,name,price,availability,categoryId,brand,description)"""
    cats={}
    def cid(brand, category):
        key=(brand,category)
        if key not in cats: cats[key]=len(cats)+1
        return cats[key]
    for it in items: it["_cid"]=cid(it["brand"], it["category"])
    now=datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    L=['<?xml version="1.0" encoding="UTF-8"?>',
       f'<yml_catalog date="{now}">',' <shop>',
       f'  <name>{su.escape(shop["name"])}</name>',
       f'  <company>{su.escape(shop["name"])}</company>',
       f'  <url>{shop["url"]}</url>',
       '  <currencies><currency id="UAH" rate="1"/></currencies>','  <categories>']
    # категорії: бренд як батько, категорія як дитина
    brand_ids={}; bid=1000
    for (brand,category),c in cats.items():
        if brand not in brand_ids: brand_ids[brand]=bid; bid+=1
    for brand,b in brand_ids.items():
        L.append(f'   <category id="{b}">{su.escape(brand)}</category>')
    for (brand,category),c in cats.items():
        L.append(f'   <category id="{c}" parentId="{brand_ids[brand]}">{su.escape(brand+" — "+category)}</category>')
    L.append('  </categories>'); L.append('  <offers>')
    for it in items:
        avail = "true" if "наявн" in str(it["availability"]).lower() else "false"
        L+= [f'   <offer id="{su.escape(str(it["article"]))}" available="{avail}">',
             f'    <name>{su.escape(str(it["name"]))}</name>',
             f'    <price>{it["price"]}</price>','    <currencyId>UAH</currencyId>',
             f'    <categoryId>{it["_cid"]}</categoryId>',
             f'    <vendorCode>{su.escape(str(it["article"]))}</vendorCode>',
             f'    <description>{su.escape(str(it.get("description","")))}</description>',
             '   </offer>']
    L+= ['  </offers>',' </shop>','</yml_catalog>']
    return "\n".join(L)
