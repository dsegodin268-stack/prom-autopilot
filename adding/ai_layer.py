# -*- coding: utf-8 -*-
"""AI-шар: підсилення 10 текстових полів картки (і ТІЛЬКИ їх).
Провайдер за назвою моделі: claude-* + ANTHROPIC_API_KEY -> Anthropic (платно);
інакше GH_MODELS_TOKEN -> GitHub Models (безкоштовно). Без ключів -> None (штатно)."""
import json
import os
import re

from common.bmparts_client import oem_and_replacements

PROM_AI_SYSTEM = (
    "Ти професійний копірайтер маркетплейсу Prom.ua, спеціалізація автозапчастини. "
    "Отримуєш факти товару з BM Parts (назва, OEM, аналоги, характеристики, сумісність, категорія). "
    "Поверни СТРОГО JSON з ключами: name_ru,name_ua (<=110 символів, без дефіса, без CAPS/емодзі, формат "
    "'<Тип> <бренд> <модель роки> <OEM>'); keywords_ru,keywords_ua (масив 30-40 реальних пошукових запитів: "
    "синоніми типу, моделі/кузови/роки, OEM зі спейсами і без, без слів 'купити/оптом/регіон'); "
    "desc_ru,desc_ua (HTML: тип+сумісність+OEM+аналоги+характеристики+CTA, без контактів/посилань/скриптів); "
    "meta_title_ru,meta_title_ua,meta_desc_ru,meta_desc_ua. Використовуй ЛИШЕ надані факти, не вигадуй специфікацій.")


def _ai_call(system, user_json):
    import urllib.request
    model = (os.environ.get("AI_MODEL", "").strip() or "openai/gpt-4.1")
    ant = os.environ.get("ANTHROPIC_API_KEY")
    tok = os.environ.get("GH_MODELS_TOKEN") or os.environ.get("AI_TOKEN")

    def _anthropic(m):
        body = json.dumps({"model": m, "max_tokens": 2000, "system": system,
                           "messages": [{"role": "user", "content": user_json}]}).encode("utf-8")
        req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body,
                                     headers={"x-api-key": ant, "anthropic-version": "2023-06-01",
                                              "content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            d = json.loads(r.read().decode("utf-8"))
        return "".join(b.get("text", "") for b in d.get("content", []) if b.get("type") == "text")

    def _github(m):
        url = os.environ.get("AI_API_URL", "https://models.github.ai/inference/chat/completions")
        body = json.dumps({"model": m, "temperature": 0.3,
                           "messages": [{"role": "system", "content": system},
                                        {"role": "user", "content": user_json}]}).encode("utf-8")
        req = urllib.request.Request(url, data=body,
                                     headers={"Authorization": "Bearer " + tok,
                                              "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode("utf-8"))["choices"][0]["message"]["content"]

    is_claude = model.lower().startswith("claude")
    if is_claude and ant:
        return _anthropic(model)
    if tok:
        return _github(model if not is_claude else "openai/gpt-4.1")
    if ant:
        return _anthropic(model if is_claude else "claude-opus-4-8")
    return None


def ai_enrich(product, clean_details_fn, fitment_fn):
    """Факти -> JSON з 10 полями або None. Помилка/ліміт/нема ключа -> None."""
    oem, repl = oem_and_replacements(product)
    facts = {"article": product.get("article"), "brand": product.get("brand"),
             "name": product.get("name"), "nodes": product.get("nodes"),
             "oem": oem[:10], "analogs": repl[:10],
             "details": [{"name": n, "unit": u, "value": v} for (n, u, v) in clean_details_fn(product)],
             "fitment": fitment_fn(product, product.get("name") or "")}
    try:
        txt = _ai_call(PROM_AI_SYSTEM, json.dumps(facts, ensure_ascii=False))
        if not txt:
            return None
        mt = re.search(r"\{.*\}", txt, re.S)
        return json.loads(mt.group(0)) if mt else None
    except Exception as e:
        print(f"[ai] пропуск ({str(e)[:100]})")
        return None


def merge_ai(f, ai):
    """Перезаписує РІВНО 10 текстових полів; технічні поля AI не чіпає."""
    def g(*ks):
        for k in ks:
            v = ai.get(k)
            if v:
                return v
        return None

    def joinkw(v):
        return ", ".join(v) if isinstance(v, list) else str(v)

    mp = {"Назва_позиції": g("name_ru"), "Назва_позиції_укр": g("name_ua"),
          "Пошукові_запити": joinkw(g("keywords_ru")) if g("keywords_ru") else None,
          "Пошукові_запити_укр": joinkw(g("keywords_ua")) if g("keywords_ua") else None,
          "Опис": g("desc_ru"), "Опис_укр": g("desc_ua"),
          "HTML_заголовок": g("meta_title_ru"), "HTML_заголовок_укр": g("meta_title_ua"),
          "HTML_опис": g("meta_desc_ru"), "HTML_опис_укр": g("meta_desc_ua")}
    for k, v in mp.items():
        if v:
            v = str(v)
            if k.startswith("Назва"):
                v = v[:110]
            f[k] = v
