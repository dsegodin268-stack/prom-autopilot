# -*- coding: utf-8 -*-
"""Перевірка ШІ (MODE=ai_check). Мережі нема — підмінюється ai_layer._post.

Що тут захищається:
  1) У пінгу НЕ МОЖЕ бути товарних чи комерційних даних. Це те саме правило,
     що й для ai_enrich: ціна/собівартість/дилерські умови до третьої сторони
     не їдуть ніколи. Тут воно перевіряється буквально — по тексту запиту.
  2) Діагноз мусить розрізняти «ключ поганий» і «ліміт». Сплутати їх дорого:
     у першому випадку власник іде міняти секрет, у другому — не робить нічого.
  3) Перевірка не має вигоряти на 404: назви моделей протухають, і перебір
     кандидатів тут потрібен так само, як у бойових сходах.
"""
import io
import urllib.error

import pytest

import adding.ai_check as chk
import adding.ai_layer as ai


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    for d in (ai._used, ai._model_ok, ai._cooldown, ai._last_call, ai._memo):
        d.clear()
    for k in list(ai.PROVIDERS):
        monkeypatch.delenv(ai.PROVIDERS[k][1], raising=False)
        monkeypatch.delenv("AI_MODEL_" + k.upper(), raising=False)
    for k in ("AI_MODEL", "AI_PROVIDERS", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(ai, "_throttle", lambda prov, pause: None)
    yield


def _http(code, body=b"{}"):
    return urllib.error.HTTPError("http://x", code, "err", {}, io.BytesIO(body))


def _reply(text="OK"):
    return {"choices": [{"message": {"content": text}}]}


# --------------------------------------------------- ГОЛОВНЕ: що йде в запиті
def test_ping_payload_has_no_commercial_data(monkeypatch):
    """У запиті — лише «напиши OK». Жодного артикулу, ціни, собівартості."""
    seen = {}

    def fake_post(url, body, headers, timeout=120):
        seen["body"] = body
        return _reply()

    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.setattr(ai, "_post", fake_post)
    chk.ping("groq")

    blob = str(seen["body"]).lower()
    for word in ("ціна", "price", "собівартіст", "cost", "дилер", "dealer",
                 "закупівл", "маржа", "націнк", "прайс", "артикул"):
        assert word not in blob, f"у пінг просочилось «{word}»"
    # і сам текст — рівно той, що задекларований у модулі
    msgs = seen["body"]["messages"]
    assert any(chk.PING_USER == m["content"] for m in msgs)
    assert seen["body"]["max_tokens"] <= 32, "пінг має бути крихітним"


def test_ping_does_not_ask_for_json_mode(monkeypatch):
    """response_format ламає частину провайдерів 400-ю — і перевірка ключа
    перетворилась би на перевірку підтримки JSON-режиму."""
    seen = {}
    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.setattr(ai, "_post",
                        lambda u, b, h, timeout=120: (seen.update(b=b), _reply())[1])
    chk.ping("groq")
    assert "response_format" not in seen["b"]


# ------------------------------------------------------------------ діагнози
def test_no_key_means_no_request(monkeypatch):
    called = []
    monkeypatch.setattr(ai, "_post", lambda *a, **k: called.append(1))
    r = chk.ping("groq")
    assert r["state"] == "no_key"
    assert not called, "без ключа провайдера не можна навіть чіпати"


def test_ok_reports_working_model(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "k")
    monkeypatch.setattr(ai, "_post", lambda *a, **k: _reply("OK"))
    r = chk.ping("nvidia")
    assert r["state"] == "ok"
    assert r["model"] == ai.PROVIDERS["nvidia"][2][0]
    assert r["answer"] == "OK"


def test_429_is_limit_not_bad_key(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.setattr(ai, "_post", lambda *a, **k: (_ for _ in ()).throw(_http(429)))
    assert chk.ping("groq")["state"] == "limit"


def test_402_is_limit(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "k")
    monkeypatch.setattr(ai, "_post", lambda *a, **k: (_ for _ in ()).throw(_http(402)))
    assert chk.ping("mistral")["state"] == "limit"


def test_403_is_denied_not_bad_key(monkeypatch):
    """Саме на цьому діагнозі 01.08.2026 злетіла сходинка cerebras: ключ живий,
    а провайдер закрив доступ на своєму боці. Стан лишається — він відрізняє
    «міняй секрет» від «тут кодом уже нічого не вдієш»."""
    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.setattr(ai, "_post", lambda *a, **k: (_ for _ in ()).throw(_http(403)))
    assert chk.ping("groq")["state"] == "denied"


def test_401_is_bad_key(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "zzz")
    monkeypatch.setattr(ai, "_post", lambda *a, **k: (_ for _ in ()).throw(_http(401)))
    assert chk.ping("groq")["state"] == "bad_key"


def test_google_400_api_key_not_valid_is_bad_key(monkeypatch):
    """Google на зіпсований ключ віддає 400 з текстом про ключ. Без розбору
    тіла це читалось би як «нема моделі» — і власник шукав би не ту проблему."""
    monkeypatch.setenv("GEMINI_API_KEY", "zzz")
    body = b'{"error":{"message":"API key not valid. Please pass a valid API key."}}'
    monkeypatch.setattr(ai, "_post", lambda *a, **k: (_ for _ in ()).throw(_http(400, body)))
    assert chk.ping("gemini")["state"] == "bad_key"


def test_404_model_advances_to_next_candidate(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    tried = []

    def fake_post(url, body, headers, timeout=120):
        tried.append(body["model"])
        if len(tried) == 1:
            raise _http(404, b'{"error":"no such model"}')
        return _reply("OK")

    monkeypatch.setattr(ai, "_post", fake_post)
    r = chk.ping("gemini")
    assert r["state"] == "ok"
    assert len(tried) == 2 and r["model"] == tried[1]


def test_all_models_404_is_no_model_not_bad_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(ai, "_post",
                        lambda *a, **k: (_ for _ in ()).throw(_http(404, b'{"e":"model"}')))
    r = chk.ping("gemini")
    assert r["state"] == "no_model", "ключ живий — винні назви моделей, не секрет"


def test_limit_does_not_burn_other_model_names(monkeypatch):
    """429 — це «зачекай», а не «спробуй іншу назву». Інакше один вичерпаний
    ключ дав би стільки ж 429, скільки в нього кандидатів."""
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    calls = []
    monkeypatch.setattr(ai, "_post",
                        lambda *a, **k: (calls.append(1), (_ for _ in ()).throw(_http(429)))[0])
    chk.ping("gemini")
    assert len(calls) == 1


def test_network_error_is_error_not_bad_key(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.setattr(ai, "_post",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("timed out")))
    assert chk.ping("groq")["state"] == "error"


def test_anthropic_uses_its_own_protocol(monkeypatch):
    seen = {}

    def fake_post(url, body, headers, timeout=120):
        seen["url"], seen["headers"] = url, headers
        return {"content": [{"type": "text", "text": "OK"}]}

    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setattr(ai, "_post", fake_post)
    r = chk.ping("anthropic")
    assert r["state"] == "ok"
    assert "anthropic.com" in seen["url"] and "x-api-key" in seen["headers"]


# ------------------------------------------------------------- повнота звіту
def test_check_all_covers_every_provider(monkeypatch):
    """Перевірка мусить пройти ВСІХ, кого знають сходи, — інакше новий
    провайдер додасться в ai_layer і тихо випаде з діагностики."""
    monkeypatch.setattr(ai, "_post", lambda *a, **k: _reply())
    res = chk.check_all()
    assert [r["prov"] for r in res] == ai.ORDER


def test_check_all_tests_providers_excluded_by_ai_providers(monkeypatch):
    """AI_PROVIDERS звужує бойові сходи, але не діагностику: власник має
    бачити, що ключ живий, навіть якщо сходинку зараз вимкнено."""
    monkeypatch.setenv("AI_PROVIDERS", "groq")
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(ai, "_post", lambda *a, **k: _reply())
    res = {r["prov"]: r for r in chk.check_all()}
    assert res["gemini"]["state"] == "ok"
    assert res["gemini"]["in_ladder"] is False
    assert res["groq"]["in_ladder"] is True


def test_summary_names_working_providers_and_fits_cell(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(ai, "_post", lambda *a, **k: _reply())
    s = chk.summary(chk.check_all())
    assert s.startswith("перевірка ШІ:")
    assert "gemini" in s and "без ключа" in s
    assert len(s) <= 400


def test_summary_shouts_when_nothing_works():
    res = [{"prov": p, "state": "no_key", "model": "", "detail": "", "answer": ""}
           for p in ai.ORDER]
    assert "не працює ЖОДЕН" in chk.summary(res)


def test_every_state_has_a_human_label():
    for st in set(chk.ALIVE) | {"no_key", "bad_key", "error"}:
        assert st in chk.LABEL and chk.LABEL[st].strip()


# --------------------------------------------------- підказка живими назвами
# Стан «жодна назва моделі не підійшла» без підказки — глухий кут: власник
# бачить, що сходинка мертва, але не знає, чим замінити протухлу назву. Тому
# на цьому стані ми питаємо у провайдера його ж список моделей.

class _FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_hint_takes_root_of_first_candidate():
    """Фільтр «свої моделі» будується з першого кандидата провайдера."""
    assert chk._hint("gemma") == "gemma"
    assert chk._hint("gemini") == "gemini"
    assert chk._hint("nvidia") == "llama"   # «meta/llama-3.3-70b-instruct»


def test_available_models_strips_prefix_and_filters(monkeypatch):
    """Google віддає «models/<назва>» — префікс зрізаємо, бо в запиті працює
    коротка форма. І лишаємо лише схожі назви, щоб не вивалити весь каталог."""
    payload = b'{"data":[{"id":"models/gemma-3-27b-it"},' \
              b'{"id":"models/gemini-3.1-flash-lite"},' \
              b'{"id":"models/gemma-3n-e4b-it"}]}'
    monkeypatch.setattr(chk.urllib.request, "urlopen",
                        lambda req, timeout=0: _FakeResp(payload))
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    assert chk._available_models("gemma") == ["gemma-3-27b-it", "gemma-3n-e4b-it"]


def test_available_models_never_breaks_the_check(monkeypatch):
    """Список — приємний бонус, а не умова роботи: якщо провайдер не дав його,
    перевірка мусить спокійно віддати порожньо, а не впасти."""
    def boom(req, timeout=0):
        raise urllib.error.HTTPError("http://x", 404, "no", {}, io.BytesIO(b""))
    monkeypatch.setattr(chk.urllib.request, "urlopen", boom)
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    assert chk._available_models("gemma") == []


def test_no_model_state_carries_the_offer(monkeypatch):
    """Наскрізь: усі кандидати дали 404 -> стан no_model і в ньому лежать
    справжні назви, які провайдер визнає."""
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(ai, "_post",
                        lambda *a, **k: (_ for _ in ()).throw(_http(404)))
    monkeypatch.setattr(chk, "_available_models", lambda prov, timeout=15:
                        ["gemma-3-27b-it"])
    r = chk.ping("gemma", timeout=1)
    assert r["state"] == "no_model"
    assert r["offer"] == ["gemma-3-27b-it"]
