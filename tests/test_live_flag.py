# -*- coding: utf-8 -*-
"""LIVE тепер дефолтно ПИШЕ (тиха DRY-RUN через невиставлену vars.LIVE неможлива),
а «Звіт_Ціни» формується ПАРАЛЕЛЬНО з Export і прив'язаний до нього."""
import importlib
import inspect

import pytest

import common.config as cfg
import repricing.run as run


def _live(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("LIVE", raising=False)
    else:
        monkeypatch.setenv("LIVE", value)
    return importlib.reload(cfg).LIVE


def test_unset_writes(monkeypatch):
    # Немає змінної взагалі -> ПИШЕ.
    assert _live(monkeypatch, None) is True


def test_empty_writes(monkeypatch):
    # vars.LIVE не виставлена у GitHub -> у воркфлоу прилітає "" -> ПИШЕ.
    assert _live(monkeypatch, "") is True


def test_one_writes(monkeypatch):
    assert _live(monkeypatch, "1") is True


def test_explicit_zero_is_dry_run(monkeypatch):
    # DRY-RUN лише за явним нулем.
    assert _live(monkeypatch, "0") is False
    assert _live(monkeypatch, " 0 ") is False
    assert _live(monkeypatch, "false") is False
    assert _live(monkeypatch, "no") is False


def test_config_module_restored():
    # Не лишаємо перезавантажений модуль у чужому стані для інших тестів.
    importlib.reload(cfg)


# ---------- звіт ----------

@pytest.fixture
def spy(monkeypatch):
    calls = []
    monkeypatch.setattr(run, "write_report", lambda *a, **k: calls.append(a))
    return calls


def _call():
    run._report(None, {}, {}, {}, {}, {}, {}, {}, "tag")


def test_report_written_by_default(spy, monkeypatch):
    # LIVE + жодних прапорців -> звіт пишеться (нічого вмикати не треба).
    monkeypatch.delenv("REPORT", raising=False)
    monkeypatch.setattr(run, "LIVE", True)
    _call()
    assert len(spy) == 1


def test_report_skipped_in_dry_run(spy, monkeypatch):
    # Export не писався -> звіт теж НЕ пишемо (щоб не розходилися).
    monkeypatch.delenv("REPORT", raising=False)
    monkeypatch.setattr(run, "LIVE", False)
    _call()
    assert spy == []


def test_report_can_be_disabled(spy, monkeypatch):
    monkeypatch.setenv("REPORT", "0")
    monkeypatch.setattr(run, "LIVE", True)
    _call()
    assert spy == []


def test_report_failure_does_not_break_run(monkeypatch):
    # Впав звіт — прогін живий, Export уже записано.
    def boom(*a, **k):
        raise RuntimeError("quota")
    monkeypatch.delenv("REPORT", raising=False)
    monkeypatch.setattr(run, "LIVE", True)
    monkeypatch.setattr(run, "write_report", boom)
    _call()  # не має кинути виняток


def test_report_runs_parallel_with_export_not_at_the_end():
    # Звіт має писатися ОДРАЗУ після основного запису в Export,
    # тобто ДО повільної крос-перевірки autonova.
    src = inspect.getsource(run.main)
    first_report = src.index("_report(")
    recheck = src.index("recheck_autonova_faster(")
    assert first_report < recheck, "звіт має формуватися паралельно з Export, а не в кінці"
    assert src.count("_report(") >= 2, "після крос-перевірки звіт має оновлюватись ще раз"
