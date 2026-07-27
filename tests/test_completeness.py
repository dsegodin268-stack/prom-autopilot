# -*- coding: utf-8 -*-
# Рівні повноти й маршрутизація. Головні правила власника, які тут закріплені:
#   • картка без фото НІКОЛИ не потрапляє в Export (Prom її відхилить);
#   • рівень 2 (є фото, бракує дрібниць) завжди їде в Staging на перевірку;
#   • поки картку BM Parts не завантажено, OEM і сумісність не рахуються
#     браком — їх просто ще не запитували.
from adding.completeness import LEVEL_NAME, level, missing, route
from adding.sources import candidate


def _full():
    """Повна картка. Тип деталі навмисно такий, що map_group() його ВПІЗНАЄ:
    з 27.07 непізнана група теж рахується браком, тому «повна» позиція мусить
    мати групу, яка реально мапиться в номер Prom."""
    c = candidate("BM Parts", "34116792217", "Диск гальмівний передній", 2400)
    c.update(photos=["https://cdn.bm.parts/a.jpg"],
             chars=[("Виробник", "", "BMW"), ("Вісь", "", "передня"), ("Діаметр", "мм", "330")],
             oem=["34116792217"], fitment=["BMW 3 F30"], group_hint="Гальмівні диски",
             matched_bm=True, card_loaded=True)
    return c


def test_full_card_is_level_1():
    c = _full()
    assert missing(c) == []
    assert level(c) == 1


def test_no_photo_is_level_3():
    c = _full()
    c["photos"] = []
    assert level(c) == 3
    assert "фото" in missing(c)


def test_group_that_does_not_map_is_counted_as_missing():
    """Головне правило власника: позиція мусить одразу знаходитись у каталозі.
    Масляного фільтра нема в сіді GROUPS -> номер групи Prom невідомий ->
    у бойову таблицю така картка не їде, чекає ручного вибору групи.
    Вигадати ID не можна: неіснуючий номер ламає імпорт усього файлу."""
    c = _full()
    c.update(article="11427953129", name_src="Фільтр масляний", group_hint="Фільтри")
    assert "група" in missing(c)
    assert level(c) == 2
    assert route(c, "export")[0] == "staging"


def test_supplier_category_text_alone_is_not_a_group():
    # group_hint непорожній, але це назва категорії В ПОСТАЧАЛЬНИКА.
    c = _full()
    c.update(name_src="Датчик невідомий", group_hint="Електрика")
    assert "група" in missing(c)


def test_photo_but_thin_is_level_2():
    c = _full()
    c["chars"] = [("Виробник", "", "BMW")]
    assert level(c) == 2
    assert "характеристики" in missing(c)


def test_oem_not_counted_before_card_loaded():
    # Bulk-фід BM Parts не віддає OEM і сумісність. Якби вони одразу рахувались
    # браком, КОЖНА позиція фіду виглядала б неповною і їхала б у Staging.
    c = _full()
    c.update(oem=[], fitment=[], card_loaded=False)
    assert "OEM" not in missing(c)
    assert level(c) == 1


def test_oem_counted_after_card_loaded():
    c = _full()
    c.update(oem=[], fitment=[], card_loaded=True)
    assert "OEM" in missing(c) and "сумісність" in missing(c)
    assert level(c) == 2


def test_price_book_item_without_bm_match_needs_oem():
    # Позиція з прайсу, якої нема в довіднику: OEM/сумісність нізвідки взяти.
    c = candidate("BMW прайс (Баварія)", "51117303107", "Решітка", 900)
    assert "OEM" in missing(c) and "сумісність" in missing(c)
    assert level(c) == 3          # фото теж нема


def test_route_level_1_to_export_when_panel_says_export():
    dest, status = route(_full(), "export")
    assert dest == "export" and status == "готово"


def test_route_level_1_to_staging_when_panel_says_staging():
    dest, _status = route(_full(), "staging")
    assert dest == "staging"


def test_route_level_2_always_staging_even_if_panel_says_export():
    c = _full()
    c["chars"] = []
    dest, status = route(c, "export")
    assert dest == "staging" and "перевірку" in status


def test_status_says_it_in_ukrainian_not_in_column_headers():
    """Статус читає власник щодня, тому він мусить бути реченням, а не списком
    заголовків. У колонці «Чого бракує» назви стоять у називному («фото,
    характеристики, група») — там це перелік. Але в статусі вони йдуть ПІСЛЯ
    слова «нема», і виходило «нема фото, характеристики, група»."""
    c = _full()
    c.update(chars=[], name_src="Датчик невідомий", group_hint="Електрика")
    _dest, status = route(c, "export")
    assert "нема характеристик, групи" in status
    assert "нема характеристики" not in status and "нема група" not in status


def test_route_level_3_always_staging_waiting_for_photo():
    c = _full()
    c["photos"] = []
    dest, status = route(c, "export")
    assert dest == "staging" and status == "чекає фото"


def test_level_names_cover_all_levels():
    assert set(LEVEL_NAME) == {1, 2, 3}
