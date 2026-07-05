"""Збагачення фото + характеристиками. Пріоритет: (1) API постачальника (фото),
(2) веб-пошук по OEM (спеки/фото) — часткове покриття. Тут — інтерфейс + заглушка."""
def enrich(item):
    # item отримує images:list, specs:list((name,unit,value))
    # ПРОД: спершу supplier API image_urls; далі веб-пошук по артикулу.
    item.setdefault("images", [])
    item.setdefault("specs", [])
    return item
