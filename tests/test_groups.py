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


def test_missing_fields_do_not_crash():
    assert map_group({}) == ("", "")
    assert map_group({"nodes": None, "name": None}) == ("", "")
