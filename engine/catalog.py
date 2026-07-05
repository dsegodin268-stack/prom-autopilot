import re
def norm(a): return re.sub(r'\s','',str(a)).upper()
def categorize(name):
    s=str(name).lower()
    if any(k in s for k in["килим","коврик","mat","підлог","всепогод","піддон"]): return "Килимки"
    if any(k in s for k in["motorrad","мото","кофр","шолом","шлем","куртк","рукавич","ланцюг","топкейс","телескоп"]): return "Мото"
    if any(k in s for k in["підсвіт","подсвет"," led","світлодіод","фара","ліхтар","проекц"]): return "Підсвітка"
    if any(k in s for k in["масло","олив","adbl","антифриз","спрей","очисн","рідин","присадк","паста","clean","care"]): return "Хімія"
    if any(k in s for k in["брелок","чохол","футляр","ключ","емблем","шильд","рамк","ковпач","освіжув","ароматиз","термо","кружк","чашк","парасол","зонт","бейсбол","кепк","вішалк","плічк","відкрив","флешк","значк","рюкзак","сумк","валіз","модель"]): return "Аксесуари"
    return "Запчастини"
def make_title(name, brand, article, category):
    base=str(name).strip().rstrip('.')
    b=brand if brand and brand!="multi" else ""
    t=f"{base} {b} — оригінал, артикул {article}".replace("  "," ").strip()
    return t[:120]
