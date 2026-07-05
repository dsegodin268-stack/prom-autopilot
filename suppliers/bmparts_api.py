"""Клієнт API BM Parts. Поетапне завантаження (спершу наявність + історія).
Ендпоінт узгоджено раніше: POST /prices/prom/{brand}. Реальні поля — з доків BM Parts."""
import os, urllib.request, json
from engine.catalog import norm
def fetch_bmparts(scfg, stage="in_stock"):
    token=os.environ.get(scfg.get("token_env","BMPARTS_TOKEN"))
    if not token:
        print("[bmparts] немає токена — пропуск (стане активним у проді)"); return []
    # ЗАГЛУШКА мережевого виклику — підставити реальний ендпоінт/поля з доків BM Parts:
    # req=urllib.request.Request(scfg["api_base"]+"/prices/prom/BMW",
    #     data=json.dumps({"stage":stage}).encode(), headers={"Authorization":"Bearer "+token})
    # rows=json.loads(urllib.request.urlopen(req).read())
    # return [{"article":norm(r["article"]),"name":r["name"],"qty":r["stock"],"cost":r["price"],
    #          "availability":"в наявності" if r["stock"]>0 else "під замовлення","brand":"BMW"} for r in rows]
    print("[bmparts] API-клієнт готовий; чекає токен + фінальні поля з доків"); return []
