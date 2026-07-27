# -*- coding: utf-8 -*-
"""Сходи ШІ-провайдерів. Мережі тут нема — підмінюється _post.

Головне, що тут захищається: назви моделей у провайдерів змінюються, і рядок,
вірний сьогодні, через місяць віддає 404. Якщо на це не реагувати, сходинка
стає мертвою мовчки: ключ є, добовий ліміт є, а запити не йдуть. Тому провайдер
має перебрати кандидатів і запам'ятати робочу назву.

І окремо — межа, яку не можна перейти: помилки ЛІМІТУ (429/402/403) не мають
ковтатись підбором моделі, бо це не «нема моделі», а «зачекай».
"""
import urllib.error

import pytest

import adding.ai_layer as ai


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    """Кожен тест — з чистими лічильниками і без жодного справжнього ключа."""
    for d in (ai._used, ai._model_ok, ai._cooldown, ai._last_call, ai._memo):
        d.clear()
    for k in list(ai.PROVIDERS):
        monkeypatch.delenv(ai.PROVIDERS[k][1], raising=False)
    for k in ("AI_MODEL", "AI_PROVIDERS", "AI_TOKEN", "ANTHROPIC_API_KEY",
              "AI_API_URL", "CF_ACCOUNT_ID"):
        monkeypatch.delenv(k, raising=False)
    for p in ai.PROVIDERS:
        monkeypatch.delenv("AI_MODEL_" + p.upper(), raising=False)
    monkeypatch.setattr(ai, "_throttle", lambda prov, pause: None)   # без сну в тестах
    yield


def _http(code, body=b"{}"):
    return urllib.error.HTTPError("http://x", code, "err", {}, None) if body is None else \
        urllib.error.HTTPError("http://x", code, "err", {}, __import__("io").BytesIO(body))


def _reply(text='{"ok":1}'):
    return {"choices": [{"message": {"content": text}}]}


# ------------------------------------------------------------ таблиця сходів
def test_every_provider_has_candidate_list_not_bare_string():
    # Гола строка знову зробила б сходинку крихкою до перейменування моделі.
    for name, (_url, _env, models, _pause, _cap) in ai.PROVIDERS.items():
        assert isinstance(models, tuple), f"{name}: моделі мають бути кортежем"
        assert models, f"{name}: порожній список кандидатів"


def test_ladder_order_covers_all_providers_and_ends_with_anthropic():
    assert set(ai.ORDER) - {"anthropic"} == set(ai.PROVIDERS)
    assert ai.ORDER[-1] == "anthropic", "платний Anthropic мусить бути ОСТАННІМ"


def test_ladder_skips_providers_without_key(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "x")
    assert ai._ladder() == ["groq"]


def test_ladder_respects_explicit_order(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "x")
    monkeypatch.setenv("GEMINI_API_KEY", "y")
    monkeypatch.setenv("AI_PROVIDERS", "groq,gemma")
    assert ai._ladder() == ["groq", "gemma"]


def test_no_keys_means_no_ladder_and_no_call():
    assert ai._ladder() == []
    assert ai._ai_call("sys", "{}") is None


# ------------------------------------------- адреса з параметром (Cloudflare)
def test_cloudflare_is_skipped_without_account_id(monkeypatch):
    """Ключа мало: без ID акаунта адреса неповна, і кожен запит був би 404.
    Краще не пускати сходинку взагалі, ніж витрачати на неї спробу."""
    monkeypatch.setenv("CF_API_TOKEN", "x")
    assert "cloudflare" not in ai._ladder()


def test_cloudflare_joins_ladder_with_account_id(monkeypatch):
    monkeypatch.setenv("CF_API_TOKEN", "x")
    monkeypatch.setenv("CF_ACCOUNT_ID", "acc123")
    assert ai._ladder() == ["cloudflare"]


def test_account_id_is_substituted_into_url(monkeypatch):
    monkeypatch.setenv("CF_ACCOUNT_ID", "acc123")
    url = ai._url_for("cloudflare")
    assert "{acct}" not in url and "/accounts/acc123/" in url


def test_plain_providers_have_no_placeholder_in_url():
    # Підстановка стосується лише Cloudflare; решта адрес мусить бути готовою.
    for name, (url, *_rest) in ai.PROVIDERS.items():
        if name != "cloudflare":
            assert "{" not in url, f"{name}: у адресі лишився параметр"


def test_github_url_override_still_works(monkeypatch):
    monkeypatch.setenv("AI_API_URL", "https://example.test/v1/chat/completions")
    assert ai._url_for("github") == "https://example.test/v1/chat/completions"
    assert ai._url_for("groq") == ai.PROVIDERS["groq"][0]


# --------------------------------------------------- підбір назви моделі
def test_falls_through_to_next_model_name_on_404(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    tried = []

    def fake_post(url, body, headers, timeout=120):
        tried.append(body["model"])
        if len(tried) == 1:
            raise _http(404, b'{"error":{"message":"model not found"}}')
        return _reply()

    monkeypatch.setattr(ai, "_post", fake_post)
    assert ai._openai_compat("gemini", "sys", "{}") == '{"ok":1}'
    assert len(tried) == 2, "мала бути спроба другого кандидата"
    assert ai._model_ok["gemini"] == tried[1]


def test_working_model_is_remembered_and_tried_first(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    tried = []

    def fake_post(url, body, headers, timeout=120):
        tried.append(body["model"])
        if body["model"] == ai.PROVIDERS["gemini"][2][0]:
            raise _http(404, b'{"error":"no such model"}')
        return _reply()

    monkeypatch.setattr(ai, "_post", fake_post)
    ai._openai_compat("gemini", "sys", "{}")
    n_after_first = len(tried)
    ai._openai_compat("gemini", "sys", "{}")
    # Другий виклик не має повторювати мертвий перший кандидат.
    assert len(tried) == n_after_first + 1


def test_rate_limit_is_not_swallowed_by_model_fallback(monkeypatch):
    """429 — це «зачекай», а не «нема моделі». Він мусить долетіти до _ai_call,
    інакше провайдер не піде в cooldown і ми довбитимемо його даремно."""
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    calls = []

    def fake_post(url, body, headers, timeout=120):
        calls.append(body["model"])
        raise _http(429, b'{"error":"rate limit"}')

    monkeypatch.setattr(ai, "_post", fake_post)
    with pytest.raises(urllib.error.HTTPError) as e:
        ai._openai_compat("gemini", "sys", "{}")
    assert e.value.code == 429
    assert len(calls) == 1, "на ліміті не можна перебирати назви моделей"


def test_last_candidate_404_propagates(monkeypatch):
    monkeypatch.setenv("COHERE_API_KEY", "x")

    def fake_post(url, body, headers, timeout=120):
        raise _http(404, b'{"error":"model gone"}')

    monkeypatch.setattr(ai, "_post", fake_post)
    with pytest.raises(urllib.error.HTTPError):
        ai._openai_compat("cohere", "sys", "{}")


def test_explicit_model_override_disables_the_search(monkeypatch):
    # Якщо власник назвав модель явно — підбирати за нього нічого не треба.
    monkeypatch.setenv("AI_MODEL_GEMMA", "gemma-3-12b-it")
    assert ai._models_for("gemma") == ["gemma-3-12b-it"]


def test_general_ai_model_does_not_leak_to_other_providers(monkeypatch):
    """AI_MODEL історично налаштовував GitHub Models. Якщо ним підмінити модель
    у Groq чи Gemini — вони віддадуть 404 на кожен запит."""
    monkeypatch.setenv("AI_MODEL", "openai/gpt-4.1")
    assert ai._models_for("github") == ["openai/gpt-4.1"]
    assert "openai/gpt-4.1" not in ai._models_for("gemini")
    assert "openai/gpt-4.1" not in ai._models_for("groq")


def test_anthropic_model_is_always_a_claude(monkeypatch):
    monkeypatch.setenv("AI_MODEL", "openai/gpt-4.1")
    assert ai._models_for("anthropic")[0].startswith("claude")


# ------------------------------------------------------------ перемикання
def test_ai_call_moves_to_next_provider_on_limit(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "x")
    monkeypatch.setenv("COHERE_API_KEY", "y")
    monkeypatch.setenv("AI_PROVIDERS", "groq,cohere")
    seen = []

    def fake_compat(prov, system, user_json):
        seen.append(prov)
        if prov == "groq":
            raise _http(429, b'{"error":"rate limit"}')
        return '{"ok":1}'

    monkeypatch.setattr(ai, "_openai_compat", fake_compat)
    assert ai._ai_call("sys", "{}") == '{"ok":1}'
    assert seen == ["groq", "cohere"]
    assert ai._cooldown.get("groq", 0) > 0, "провайдер з лімітом мусить піти в паузу"
    assert ai._used.get("cohere") == 1


def test_daily_cap_stops_provider(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    monkeypatch.setenv("AI_PROVIDERS", "openrouter")
    ai._used["openrouter"] = ai.PROVIDERS["openrouter"][4]
    monkeypatch.setattr(ai, "_openai_compat",
                        lambda *a: pytest.fail("вибраний ліміт — виклику бути не мало"))
    assert ai._ai_call("sys", "{}") is None


def test_usage_report_names_the_model_that_worked():
    ai._used["gemma"] = 7
    ai._model_ok["gemma"] = "gemma-3-12b-it"
    assert "gemma:7" in ai.usage_report() and "gemma-3-12b-it" in ai.usage_report()


def test_usage_report_when_ai_never_ran():
    assert ai.usage_report() == "ШІ не викликався"
