# -*- coding: utf-8 -*-
# Група Prom — одне з полів, яких ШІ не має права торкатися (ПРАВИЛА §8), тому
# вона мусить рахуватись детерміновано і НЕ вигадуватись. Порожня група — це
# нормальний сигнал «докурувати вручну», а не привід підставити випадковий ID.
from adding.groups import map_group


def test_maps_by_name():
    gid, gname = map_group({"name": "Диск гальмівний передній BMW 3 F30"})
    assert gid and gname == "Тормозные диски"


def test_maps_by_nodes_string():
    gid, _ = map_group({"nodes": "Амортизатори", "name": "BMW 3 F30"})
    assert gid


def test_nodes_as_list_of_dicts_does_not_crash():
    # Живий BM Parts віддає nodes і списком словників — раніше тут був TypeError,
    # і картка тихо гинула в загальному except конвеєра.
    prod = {"nodes": [{"name": "Гальмівна система"}, {"name": "Гальмівні диски"}],
            "name": "Деталь"}
    gid, gname = map_group(prod)
    assert gname == "Тормозные диски"


def test_nodes_as_plain_list():
    assert map_group({"nodes": ["Свічки запалювання"], "name": ""})[0]


def test_unknown_type_returns_empty_not_guess():
    assert map_group({"nodes": "", "name": "Незрозуміла деталь XYZ"}) == ("", "")


# ------------------------------------------------------------------ фільтри ---
# Номери звірені 27.07 з вітриною власника visimics.com.ua (g<ID>-<slug>).
# Фільтри — найходовіший розхідник ТО, і доти вони всі зависали в Staging.
def test_oil_filter_has_its_own_group():
    assert map_group({"name": "Фільтр масляний BMW 3 F30"}) == ("138500033", "Масляные фильтры")
    assert map_group({"name": "Фильтр масляный BMW"})[0] == "138500033"


def test_air_filter_is_not_the_air_duct_group():
    """Раніше повітряний фільтр мапився на 154216457 «Система подачи воздуха» —
    а це група ПОВІТРОВОДІВ. Фільтр лягав не в свою полицю."""
    assert map_group({"name": "Фільтр повітряний BMW 3 F30"}) == ("138500035", "Воздушные фильтры")
    assert map_group({"name": "Фильтр воздушный BMW"})[0] == "138500035"


def test_air_duct_stays_in_air_intake_group():
    """«Воздуховод фильтра воздушного» містить і «фильтр», і «воздуш», тому
    правило про повітроводи мусить стояти В СПИСКУ ВИЩЕ за правила фільтрів."""
    gid, gname = map_group({"name": "Воздуховод фильтра воздушного BMW X3"})
    assert (gid, gname) == ("154216457", "Система подачи воздуха")


def test_fuel_cabin_and_transmission_filters():
    assert map_group({"name": "Фільтр паливний BMW"})[0] == "138540162"
    assert map_group({"name": "Фильтр топливный BMW"})[0] == "138540162"
    assert map_group({"name": "Фільтр салону вугільний BMW"})[0] == "138500081"
    assert map_group({"name": "Фільтр АКПП BMW"})[0] == "138500094"


def test_motor_oil_is_not_confused_with_oil_filter():
    """«масляний» містить «масл», але «масло» — ні, тому олива й масляний
    фільтр не перетягують одне одного."""
    assert map_group({"name": "Масло моторне BMW 5W-30"})[1] == "Масла моторные"
    assert map_group({"name": "Фільтр масляний BMW"})[1] == "Масляные фильтры"


def test_sentinel_type_really_does_not_map():
    """tests/fakes.py тримає позицію 2 як вартового «тип не впізнано». Якщо
    колись додати цей тип у GROUPS, впаде саме цей тест — і одразу зрозуміло,
    що треба переставити вартового на інший тип, а не «чинити» конвеєр."""
    from tests.fakes import FEED_ROWS

    row = FEED_ROWS[1]
    assert map_group({"name": row[1], "nodes": row[6]}) == ("", "")


def test_missing_fields_do_not_crash():
    assert map_group({}) == ("", "")
    assert map_group({"nodes": None, "name": None}) == ("", "")
