"""Генерація SEO-полів і характеристик у формат Prom (українською)."""
BRAND_COUNTRY={"BMW":"Німеччина","Audi":"Німеччина","VW/Audi":"Німеччина","Mercedes":"Німеччина","Porsche":"Німеччина","MINI":"Великобританія"}
def seo_fields(name, brand, article, category, model=""):
    b = "" if brand in ("multi","Авто","") else brand
    title_ua = f"{name} {b} — оригінал, артикул {article}".replace("  "," ").strip()[:120]
    q=[f"{category} {b}", f"{b} {category} купити", f"оригінал {b} {category}",
       f"{category} {b} ціна", f"{b} {article}"]
    queries_ua = ", ".join(x for x in q if x.strip())[:255]
    meta_title = f"{category} {b} — купити оригінал, артикул {article} | Visimics"[:70]
    meta_desc = f"Оригінал {b} {category} (арт. {article}). Наявність, швидка доставка по Україні, гарантія. Купуйте у Visimics."[:160]
    desc = (f"<p>Оригінальний(а) {name} {b} — артикул виробника <strong>{article}</strong>. "
            f"Точна відповідність, фірмова якість. Доставка по Україні, повернення протягом 14 днів. "
            f"Не впевнені щодо сумісності — підкажемо за VIN.</p>")
    return {"name_ua":title_ua,"queries_ua":queries_ua,"meta_title":meta_title,
            "meta_desc":meta_desc,"desc_ua":desc}
def characteristics(name, brand, category):
    s=name.lower(); ch=[("Стан","","Новий")]
    if brand not in ("multi","Авто",""): ch.append(("Виробник","",brand))
    c=BRAND_COUNTRY.get(brand);
    if c: ch.append(("Країна-виробник","",c))
    if category=="Килимки":
        mat="Гума" if ("гум" in s or "резин" in s) else ("Велюр" if "велюр" in s else "")
        if mat: ch.append(("Матеріал","",mat))
        ch.append(("Тип","","Килимки в салон/багажник"))
    if category=="Хімія": ch.append(("Тип","","Автохімія"))
    if category=="Підсвітка": ch.append(("Тип","","Освітлення"))
    return ch
