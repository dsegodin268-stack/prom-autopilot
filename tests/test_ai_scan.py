# -*- coding: utf-8 -*-
"""MODE=ai_scan — «примірка» позицій, і колонка «Фото вручну».

ai_scan мусить судити РІВНО так само, як бойовий enrich, і відрізнятись рівно
одним: нічого не дописувати ні в Export, ні в Staging_Prom. Тому тут
перевіряється не текст статусу, а сам факт: жодного append_rows.

Колонка «Фото вручну (посилання)» існує через те, що ШІ не вміє робити
фотографії, а Prom не пропускає позицію без жодного зображення. Для картки
з нуля це єдиний шлях дотягти її до Export.
"""
import pytest

import adding.run as run


# ------------------------------------------------------------- фото вручну
def test_manual_photos_separators():
    got = run.manual_photos("https://a.com/1.jpg, https://b.com/2.jpg\nhttps://c.com/3.jpg")
    assert got == ["https://a.com/1.jpg", "https://b.com/2.jpg", "https://c.com/3.jpg"]


def test_manual_photos_only_urls():
    # Усе, що не посилання, — не фото: у Prom поїде саме цей рядок.
    assert run.manual_photos("фото буде пізніше") == []
    assert run.manual_photos("дивись тут: https://a.com/1.jpg") == ["https://a.com/1.jpg"]


def test_manual_photos_dedup_and_empty():
    assert run.manual_photos("https://a.com/1.jpg https://a.com/1.jpg") == ["https://a.com/1.jpg"]
    assert run.manual_photos("") == []
    assert run.manual_photos(None) == []


def test_manual_photos_http_allowed():
    assert run.manual_photos("http://a.com/1.jpg") == ["http://a.com/1.jpg"]


# ------------------------------------------------------- сам режим примірки
HEAD = ["Джерело", "Артикул", "Назва (як у джерелі)", "Собівартість, ₴",
        "Наявність", "К-ть", "Взяти", "Статус", "Фото вручну (посилання)"]


class _Ws:
    def __init__(self, title, rows):
        self.title = title
        self._rows = rows
        self.appended = []
        self.batched = []

    def get_all_values(self):
        return self._rows

    def append_rows(self, rows, **kw):
        self.appended += list(rows)

    def batch_update(self, reqs, **kw):
        self.batched += list(reqs)

    def update(self, *a, **kw):
        pass


class _Sh:
    def __init__(self, tabs):
        self.tabs = tabs


def _wire(monkeypatch, take="ТАК"):
    review = _Ws("Огляд_Додавання", [
        HEAD,
        ["BM Parts", "11427953129", "Фільтр", "100", "+", "5", take, "", ""],
    ])
    export = _Ws("Export Products Sheet", [["Код_товару", "Назва_позиції"]])
    staging = _Ws("Staging_Prom", [["Код_товару", "Назва_позиції"]])
    tabs = {"огляд": review, "export": export, "staging": staging}

    def _find(sh, tab, **kw):
        t = str(tab).lower()
        if "огляд" in t:
            return review
        if "staging" in t:
            return staging
        return export

    monkeypatch.setattr(run, "find_ws", _find)
    monkeypatch.setattr(run, "_staging", lambda sh, head: staging)
    monkeypatch.setattr(run, "_bm", lambda: None, raising=False)
    import adding.review as rv
    monkeypatch.setattr(rv, "_bm", lambda: None)
    monkeypatch.setattr(run, "stock_map", lambda bm, br: {})
    monkeypatch.setattr(run, "providers_ready", lambda: [])
    monkeypatch.setattr(run, "write_status", lambda sh, text: None)
    monkeypatch.setattr(run, "bm_lookup", lambda *a, **k: False)
    return tabs


def _st(**kw):
    st = {"sources": ["BM Parts"], "brands": ["BMW"], "scratch": "off",
          "max": 0, "target": "export", "ai": "Без ШІ",
          "instock_only": False, "min_cost": 0,
          "source": "BM Parts", "brand": "BMW"}
    st.update(kw)
    return st


def test_scan_writes_nothing(monkeypatch):
    tabs = _wire(monkeypatch)
    run.do_enrich(_Sh(tabs), _st(), scan=True)
    assert tabs["export"].appended == []
    assert tabs["staging"].appended == []


def test_scan_still_marks_status(monkeypatch):
    tabs = _wire(monkeypatch)
    run.do_enrich(_Sh(tabs), _st(), scan=True)
    # Присуд мусить лягти в «Статус» — інакше примірка нічого не показує.
    assert tabs["огляд"].batched


def test_scan_status_says_future(monkeypatch, capsys):
    tabs = _wire(monkeypatch)
    run.do_enrich(_Sh(tabs), _st(), scan=True)
    out = capsys.readouterr().out
    assert "РЕЖИМ ПЕРЕВІРКИ" in out
    assert "Нічого не записано" in out


def test_scratch_off_skips_missing_bm(monkeypatch, capsys):
    tabs = _wire(monkeypatch)
    run.do_enrich(_Sh(tabs), _st(scratch="off"), scan=True)
    assert "не знайдено в BM Parts" in capsys.readouterr().out


def test_scratch_on_builds_from_nothing(monkeypatch, capsys):
    tabs = _wire(monkeypatch)
    run.do_enrich(_Sh(tabs), _st(scratch="staging"), scan=True)
    out = capsys.readouterr().out
    assert "збираю картку з нуля" in out
    assert "картка з нуля: увімкнено" in out


def test_scratch_staging_ceiling_is_staging(monkeypatch, capsys):
    # Режим «у чернетку» не має права пустити картку в Export навіть тоді,
    # коли пульт каже target=export.
    tabs = _wire(monkeypatch)
    run.do_enrich(_Sh(tabs), _st(scratch="staging", target="export"), scan=True)
    assert tabs["export"].appended == []
    assert "Staging_Prom" in capsys.readouterr().out


def test_no_take_no_work(monkeypatch, capsys):
    tabs = _wire(monkeypatch)
    run.do_enrich(_Sh(tabs), _st(), scan=True)
    tabs2 = _wire(monkeypatch, take="")
    run.do_enrich(_Sh(tabs2), _st(), scan=True)
    assert "постав галки" in capsys.readouterr().out
