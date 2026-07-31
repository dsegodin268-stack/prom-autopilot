# -*- coding: utf-8 -*-
"""Кілька джерел і марок за один прогін + режим «картка з нуля».

Що тут захищається:
  1) Раніше пульт віддавав РІВНО одне джерело і РІВНО одну марку, тому за
     прогін підтягувався тільки BM Parts і тільки BMW. Тепер у клітинці —
     список через кому, і розбір цього списку мусить бути передбачуваним:
     невідома назва не має тихо «з'їдати» решту.
  2) «Усі джерела» розгортається в реальний перелік, а не лишається рядком:
     інакше збірка кандидатів шукала б джерело з такою назвою і не знайшла б.
  3) Старий пульт власника не має ламатись: підпис «Джерело» (однина) і
     значення «Так» у рядку «Картка з нуля» мусять читатись, причому «Так»
     мапиться в НАЙБЕЗПЕЧНІШИЙ режим — у чернетку, а не одразу в Export.
"""
import pytest

import adding.panel as panel
from common.config import SRC_ALL, SRC_BMPARTS, SRC_BMW, SRC_PORSCHE, SUPPLIER_BOOKS


# ------------------------------------------------------------ розбір списків
def test_split_list_separators():
    # Власник пише як зручно: кома, крапка з комою, скісна, перенос рядка.
    assert panel.split_list("BMW, MINI") == ["BMW", "MINI"]
    assert panel.split_list("BMW; MINI/Porsche\nAudi") == ["BMW", "MINI", "Porsche", "Audi"]
    assert panel.split_list("") == []
    assert panel.split_list(None) == []


def test_parse_sources_multi():
    got = panel.parse_sources(f"{SRC_BMPARTS}, {SRC_BMW}")
    assert got == [SRC_BMPARTS, SRC_BMW]


def test_parse_sources_all_expands():
    # «Усі джерела» -> реальний перелік, інакше collect() шукав би джерело
    # з такою назвою і не знайшов би жодного.
    got = panel.parse_sources(SRC_ALL)
    assert got == [SRC_BMPARTS] + list(SUPPLIER_BOOKS)
    assert SRC_ALL not in got


def test_parse_sources_unknown_skipped_not_fatal(capsys):
    # Одруківка не має тихо звужувати прогін: відоме беремо, про невідоме кажемо.
    got = panel.parse_sources(f"BM Prts, {SRC_PORSCHE}")
    assert got == [SRC_PORSCHE]
    assert "BM Prts" in capsys.readouterr().out


def test_parse_sources_empty_falls_back():
    assert panel.parse_sources("") == [SRC_BMPARTS]
    assert panel.parse_sources("хтозна що") == [SRC_BMPARTS]


def test_parse_sources_dedup():
    got = panel.parse_sources(f"{SRC_BMPARTS}, {SRC_BMPARTS}, {SRC_BMW}")
    assert got == [SRC_BMPARTS, SRC_BMW]


def test_parse_brands():
    assert panel.parse_brands("BMW, MINI") == ["BMW", "MINI"]
    assert panel.parse_brands("bmw, BMW") == ["bmw"]        # дубль без урахування регістру
    assert panel.parse_brands("") == ["BMW"]
    assert panel.parse_brands("", default="Porsche") == ["Porsche"]


# ------------------------------------------- сумісність зі старим форматом st
def test_sources_of_old_state():
    # st зі старого коду: одне поле "source" замість списку.
    assert panel.sources_of({"source": SRC_BMW}) == [SRC_BMW]
    assert panel.brands_of({"brand": "MINI"}) == ["MINI"]


def test_sources_of_prefers_list():
    st = {"sources": [SRC_BMPARTS, SRC_BMW], "source": SRC_BMPARTS}
    assert panel.sources_of(st) == [SRC_BMPARTS, SRC_BMW]


# ------------------------------------------------------------ картка з нуля
def test_scratch_modes():
    assert panel.SCRATCH_MODE[panel.keyf(panel.SCRATCH_OFF)] == "off"
    assert panel.SCRATCH_MODE[panel.keyf(panel.SCRATCH_STAGING)] == "staging"
    assert panel.SCRATCH_MODE[panel.keyf(panel.SCRATCH_EXPORT)] == "export"


def test_old_label_aliases():
    # Старий пульт: «Джерело» (однина) і «Марка (для BM Parts)».
    assert panel._BY_LABEL[panel.keyf("Джерело")] == "source"
    assert panel._BY_LABEL[panel.keyf("Марка (для BM Parts)")] == "brand"
    assert panel._BY_LABEL[panel.keyf("Джерела")] == "source"


class _FakeWs:
    def __init__(self, rows):
        self._rows = rows

    def get_all_values(self):
        return self._rows


def _panel_rows(pairs):
    return [["Параметр", "Значення", "Підказка"]] + [[a, b, ""] for a, b in pairs]


def _read(monkeypatch, rows):
    monkeypatch.setattr(panel, "find_ws", lambda sh, tab, **kw: _FakeWs(rows))
    monkeypatch.setenv("PANEL", "1")
    return panel.read_panel(object())


def test_read_panel_multi(monkeypatch):
    st = _read(monkeypatch, _panel_rows([
        ("Джерела", f"{SRC_BMPARTS}, {SRC_BMW}"),
        ("Марки (для BM Parts)", "BMW, MINI"),
        ("Картка з нуля (нема в BM Parts)", panel.SCRATCH_STAGING),
    ]))
    assert st["sources"] == [SRC_BMPARTS, SRC_BMW]
    assert st["brands"] == ["BMW", "MINI"]
    assert st["scratch"] == "staging"
    # Старий код читає st["source"]/st["brand"] — мусить лишитись робочим.
    assert st["source"] == SRC_BMPARTS and st["brand"] == "BMW"


def test_read_panel_old_layout(monkeypatch):
    # Пульт власника ще без рядка «Картка з нуля»: читання ЗА ПІДПИСОМ не має
    # зсунути значення на рядок (позиційне читання тут дало б brand="200").
    st = _read(monkeypatch, _panel_rows([
        ("Джерело", SRC_BMW),
        ("Марка (для BM Parts)", "MINI"),
        ("Скільки позицій за раз", "200"),
    ]))
    assert st["sources"] == [SRC_BMW]
    assert st["brands"] == ["MINI"]
    assert st["max"] == 200
    assert st["scratch"] == "off"          # рядка нема -> вимкнено


def test_read_panel_old_yes_is_safest(monkeypatch):
    # Старе значення «Так» -> у чернетку, НЕ одразу в живу таблицю.
    st = _read(monkeypatch, _panel_rows([("Картка з нуля (нема в BM Parts)", "Так")]))
    assert st["scratch"] == "staging"


def test_read_panel_scratch_export(monkeypatch):
    st = _read(monkeypatch, _panel_rows([
        ("Картка з нуля (нема в BM Parts)", panel.SCRATCH_EXPORT)]))
    assert st["scratch"] == "export"


def test_panel_off_uses_env(monkeypatch):
    monkeypatch.setenv("PANEL", "0")
    monkeypatch.setenv("SOURCE", f"{SRC_BMPARTS}, {SRC_PORSCHE}")
    monkeypatch.setenv("BRAND", "BMW, MINI")
    monkeypatch.setenv("SCRATCH", panel.SCRATCH_STAGING)
    st = panel.read_panel(object())
    assert st["sources"] == [SRC_BMPARTS, SRC_PORSCHE]
    assert st["brands"] == ["BMW", "MINI"]
    assert st["scratch"] == "staging"


def test_env_scratch_default_off(monkeypatch):
    monkeypatch.setenv("PANEL", "0")
    monkeypatch.delenv("SCRATCH", raising=False)
    assert panel.read_panel(object())["scratch"] == "off"


def test_source_row_validation_not_strict():
    # Випадайка джерел/марок — ПІДКАЗКА: інакше Google не дав би зберегти
    # «BM Parts, BMW прайс (Баварія)» одним рядком.
    class _W:
        id = 1
    reqs = panel._validation_reqs(_W())
    strict = {}
    for i, (k, _l, _d, _h, opts) in enumerate(panel.ROWS):
        if not opts:
            continue
        for r in reqs:
            if r["setDataValidation"]["range"]["startRowIndex"] == i + 1:
                strict[k] = r["setDataValidation"]["rule"]["strict"]
    assert strict["source"] is False
    assert "brand" not in strict      # у марок випадайки нема взагалі
    assert strict["target"] is True
    assert strict["scratch"] is True
