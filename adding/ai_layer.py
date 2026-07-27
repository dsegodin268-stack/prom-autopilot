# -*- coding: utf-8 -*-
"""AI-шар: підсилення 10 текстових полів картки (і ТІЛЬКИ їх).

2026-07-26 — СХОДИ ПРОВАЙДЕРІВ, звірені з cheahjs/free-llm-api-resources
(зчитано 26.07.2026: README.md + таблиці лімітів по кожному провайдеру).

Раніше був один канал: GitHub Models (GH_MODELS_TOKEN). У Copilot Free це
~50 запитів/ДОБУ на «high»-моделі -> повний каталог 3913 позицій = ~78 днів.
Тепер провайдери шикуються в сходи й перемикаються на наступний при 429/5xx —
так само, як водоспад джерел ціни в репрайсері.

Усі безкоштовні канали, крім Anthropic, сумісні з OpenAI chat/completions,
тож це одна функція + таблиця ендпойнтів.

СУМАРНА БЕЗКОШТОВНА ЄМНІСТЬ (за звіреними лімітами, ~2500 токенів на запит):
    gemini flash-lite   500/добу      groq gpt-oss-120b   1000/добу
    gemma-3-27b       ~8600/добу      cerebras gpt-oss     ~400/добу
    mistral            ~1000/добу     nvidia              ~1000/добу
    scaleway           ~400 разово    cloudflare          ~200/добу
    openrouter           50/добу      cohere               ~33/добу
    github               50/добу
-> увесь каталог 3913 позицій проходить за ОДНУ добу безкоштовно.

Порядок задає AI_PROVIDERS (через кому). За замовчуванням — ORDER нижче:
спершу найкраща якість, далі найбільша ємність, платний Anthropic — останній.
Без жодного ключа -> None (штатно: картка лишається детермінованою).
"""
import json
import os
import re
import time
import urllib.error
import urllib.request

from common.bmparts_client import clean_name, oem_and_replacements

# ---------------------------------------------------------------- промпти
_COMMON_RULES = (
    "Поверни СТРОГО JSON з ключами: name_ru,name_ua,keywords_ru,keywords_ua,"
    "desc_ru,desc_ua,meta_title_ru,meta_title_ua,meta_desc_ru,meta_desc_ua.\n"
    "НАЗВА (<=110 символів): формат '<Тип деталі> <Марка> <кузови через пробіл> "
    "<двигуни> <OEM суцільно>'. Тип деталі — ПЕРШИМ словом (у видачі Prom видно ~70 символів). "
    "Каталожні номери пишуться ЛИШЕ СУЦІЛЬНО, без пробілів і без дефісів: 11427953129, "
    "а НЕ '11 42 7 953 129' і не '11427-953-129'. Роки випуску в назву НЕ пишемо — "
    "вони йдуть у характеристики. Без CAPS, без емодзі, без слів 'купити/оптом/недорого'.\n"
    "КЛЮЧОВІ СЛОВА (масив 25-40 фраз): кожен елемент — ЦІЛИЙ пошуковий запит, який людина "
    "вводить у пошук Prom, бо Prom шукає збіг УСЕРЕДИНІ однієї фрази, а не по всьому списку. "
    "Правильно: 'масляний фільтр BMW F30', 'фільтр масла бмв ф30 2.0'. Неправильно: "
    "'фільтр', 'BMW', 'F30' окремими елементами. Обов'язково додай: OEM суцільно; "
    "тип+марка; тип+марка+кузов для КОЖНОГО кузова; російські й українські синоніми типу; "
    "розмовні написання марки ('бмв', 'порше'). БЕЗ міст і регіонів.\n"
    "ОПИС (HTML): тип -> сумісність -> OEM -> аналоги -> характеристики -> CTA. "
    "Без контактів, посилань, скриптів.\n"
    "ЗАБОРОНЕНО вигадувати номери деталей, кузови, двигуни й роки: у тексті можуть бути "
    "тільки ті, що є у вхідних фактах. Якщо факту немає — не згадуй його взагалі."
)

PROM_AI_SYSTEM = (
    "Ти професійний копірайтер маркетплейсу Prom.ua, спеціалізація автозапчастини. "
    "Отримуєш ПОВНІ факти товару з BM Parts (назва, OEM, аналоги, характеристики, сумісність, "
    "категорія). Твоє завдання — переписати їх під пошук Prom і Google.\n" + _COMMON_RULES)

PROM_AI_SYSTEM_THIN = (
    "Ти професійний копірайтер маркетплейсу Prom.ua, спеціалізація автозапчастини. "
    "Отримуєш МІНІМАЛЬНІ факти з прайсу постачальника: артикул, сира назва (може бути "
    "скороченою, з помилками, транслітом) і бренд. Іншого немає.\n"
    "ТВОЄ ГОЛОВНЕ ОБМЕЖЕННЯ: ти НЕ ЗНАЄШ, на які саме кузови, двигуни й роки підходить "
    "ця деталь. НЕ ВИГАДУЙ їх. Розшифруй скорочення сирої назви ('кол.торм.пер.' -> "
    "'колодки гальмівні передні'), визнач тип деталі, постав бренд і артикул — і все. "
    "Поля keywords будуй лише з типу деталі, бренду та артикулу. Якщо в фактах немає "
    "жодного кузова — у назві й ключових словах не повинно бути жодного кузова.\n"
    + _COMMON_RULES)

# ------------------------------------------------------- таблиця провайдерів
# name -> (URL, env-ключ, КОРТЕЖ моделей-кандидатів, мін. пауза сек, ліміт запитів/добу)
# Звірено 26.07.2026 з cheahjs/free-llm-api-resources. Паузи розраховані так,
# щоб не впертись у tokens/minute при ~2500 токенах на запит (не лише в RPM).
#
# ЧОМУ КОРТЕЖ, А НЕ ОДНА МОДЕЛЬ. Назви моделей у провайдерів змінюються швидше,
# ніж наш код: рядок, вірний сьогодні, через місяць віддає 404 «model not found».
# З однією назвою це означало б тихо втрачену сходинку — ключ є, ліміт є, а рунг
# мертвий. Тому пробуємо кандидатів по черзі й запам'ятовуємо ту, що відповіла
# (_model_ok). Коштує це одну зайву відповідь 404 РАЗ на прогін, зате сходи
# самі лікуються без правки коду. Примусово задати модель можна завжди:
# AI_MODEL_<ПРОВАЙДЕР>, напр. AI_MODEL_GEMMA=gemma-3-12b-it.
PROVIDERS = {
    # Google AI Studio. flash-lite: 500 запитів/добу, 15 rpm (у звичайного flash лише 20/добу).
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
               "GEMINI_API_KEY",
               ("gemini-3.1-flash-lite", "gemini-2.5-flash-lite", "gemini-2.5-flash"),
               4.2, 500),
    # Той самий ключ, інша модель: 14400 запитів/добу, 30 rpm, але 15000 tpm ->
    # реальна стеля ~6 запитів/хв. Це головний робочий кінь для повного каталогу.
    "gemma": ("https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
              "GEMINI_API_KEY",
              ("gemma-3-27b-it", "gemma-3-27b-instruct", "gemma-3-12b-it"),
              10.0, 8600),
    # Groq: на gpt-oss-120b 1000 запитів/добу і 8000 tpm -> ~3 запити/хв.
    "groq": ("https://api.groq.com/openai/v1/chat/completions",
             "GROQ_API_KEY",
             ("openai/gpt-oss-120b", "llama-3.3-70b-versatile", "llama-3.3-70b"),
             20.0, 1000),
    # Cerebras: 30 rpm / 60000 tpm, але стеля саме в ТОКЕНАХ — 1 млн/добу.
    # 1 000 000 / ~2500 токенів на картку = ~400 карток, це і є наш добовий ліміт.
    "cerebras": ("https://api.cerebras.ai/v1/chat/completions",
                 "CEREBRAS_API_KEY", ("gpt-oss-120b", "llama-3.1-8b"), 12.5, 400),
    # Mistral: 1 запит/сек, великий місячний ліміт токенів.
    "mistral": ("https://api.mistral.ai/v1/chat/completions",
                "MISTRAL_API_KEY", ("mistral-small-latest", "open-mistral-nemo"), 1.2, 0),
    # NVIDIA NIM: 40 rpm, добового ліміту не задекларовано.
    "nvidia": ("https://integrate.api.nvidia.com/v1/chat/completions",
               "NVIDIA_API_KEY",
               ("meta/llama-3.3-70b-instruct", "meta/llama-3.1-8b-instruct"), 1.6, 0),
    # Scaleway: 1 млн безкоштовних токенів РАЗОВО -> ~400 карток усього, не щодня.
    # Коли грант вичерпано, провайдер віддає 402 і сходи самі йдуть далі.
    "scaleway": ("https://api.scaleway.ai/v1/chat/completions",
                 "SCALEWAY_API_KEY",
                 ("llama-3.3-70b-instruct", "gpt-oss-120b",
                  "mistral-small-3.2-24b-instruct-2506"),
                 2.0, 400),
    # Cloudflare Workers AI: 10000 «нейронів»/добу. Нейрон — не запит: скільки їх
    # з'їдає картка, залежить від моделі, тож точної арифметики тут бути не може.
    # Ставимо свідомо занижені 200 і покладаємось на 402/429 — краще недобрати
    # безкоштовного, ніж довбити провайдера в стелю. URL містить ID акаунта, тому
    # ця сходинка вмикається лише разом із CF_ACCOUNT_ID (див. _url_for/_ladder).
    "cloudflare": ("https://api.cloudflare.com/client/v4/accounts/{acct}/ai/v1/chat/completions",
                   "CF_API_TOKEN",
                   ("@cf/meta/llama-3.3-70b-instruct-fp8-fast", "@cf/google/gemma-3-12b-it",
                    "@cf/mistralai/mistral-small-3.1-24b-instruct"),
                   3.0, 200),
    # OpenRouter: 20 rpm, 50 запитів/добу (1000/добу після поповнення на $10).
    "openrouter": ("https://openrouter.ai/api/v1/chat/completions",
                   "OPENROUTER_API_KEY",
                   ("google/gemma-3-27b-it:free", "meta-llama/llama-3.3-70b-instruct:free"),
                   3.2, 50),
    # Cohere: 20 rpm, 1000 запитів/МІСЯЦЬ -> ~33/добу. OpenAI-сумісний шлях /compatibility/v1.
    "cohere": ("https://api.cohere.ai/compatibility/v1/chat/completions",
               "COHERE_API_KEY", ("command-a-03-2025", "command-r-plus"), 3.2, 33),
    # GitHub Models: ліміт залежить від тарифу Copilot; у Free ~50/добу на high-моделях.
    "github": ("https://models.github.ai/inference/chat/completions",
               "GH_MODELS_TOKEN", ("openai/gpt-4.1", "openai/gpt-4o"), 6.5, 50),
}
ORDER = ["gemini", "gemma", "groq", "cerebras", "mistral", "nvidia",
         "scaleway", "cloudflare", "openrouter", "cohere", "github", "anthropic"]

_last_call = {}     # provider -> час останнього запиту
_model_ok = {}      # provider -> назва моделі, що реально відповіла цього прогону
_cooldown = {}      # provider -> до якого часу не чіпати (після 429/добового ліміту)
_used = {}          # provider -> скільки запитів зроблено за цей прогін
_memo = {}          # факти -> результат, щоб не платити двічі за той самий артикул


def _url_for(prov):
    """Адреса провайдера з підставленими змінними.

    Cloudflare — єдиний, у кого ID акаунта сидить у самому шляху, а не в заголовку.
    Робимо це підстановкою, а не окремою гілкою у виклику, щоб решта коду й далі
    бачила всіх провайдерів однаково. Порожній acct тут не страшний: _ladder такого
    провайдера в сходи взагалі не пустить."""
    url = PROVIDERS[prov][0]
    if "{acct}" in url:
        url = url.replace("{acct}", (os.environ.get("CF_ACCOUNT_ID") or "").strip())
    if prov == "github" and os.environ.get("AI_API_URL"):
        url = os.environ["AI_API_URL"]
    return url


def _ready(prov):
    """Чи має провайдер усе, що йому треба для запиту.

    Ключа мало, коли адреса параметризована: Cloudflare без CF_ACCOUNT_ID дасть
    404 на кожен запит, і це виглядатиме як «нема моделі», хоча насправді просто
    не заповнена адреса. Тому перевіряємо обидві умови ще на вході в сходи."""
    if prov == "anthropic":
        return bool(os.environ.get("ANTHROPIC_API_KEY"))
    if prov not in PROVIDERS:
        return False
    envk = PROVIDERS[prov][1]
    if not (os.environ.get(envk) or (prov == "github" and os.environ.get("AI_TOKEN"))):
        return False
    if "{acct}" in PROVIDERS[prov][0] and not (os.environ.get("CF_ACCOUNT_ID") or "").strip():
        return False
    return True


def _ladder():
    """Сходи провайдерів: явний AI_PROVIDERS або всі, для яких є ключ."""
    raw = (os.environ.get("AI_PROVIDERS") or "").strip()
    names = [p.strip().lower() for p in raw.split(",") if p.strip()] if raw else ORDER
    return [p for p in names if _ready(p)]


def _models_for(prov):
    """Список моделей-кандидатів для провайдера, у порядку спроби.

    AI_MODEL_<PROV> перебиває все (і тоді список рівно з однієї моделі — власник
    сказав явно, підбирати за нього не треба). Далі загальний AI_MODEL (лише для
    github/anthropic, щоб не підсунути чужу назву решті). Далі — кандидати з
    таблиці, з тією, що вже спрацювала цього прогону, попереду."""
    m = (os.environ.get("AI_MODEL_" + prov.upper()) or "").strip()
    if m:
        return [m]
    m = (os.environ.get("AI_MODEL") or "").strip()
    if prov == "anthropic":
        return [m if m.lower().startswith("claude") else "claude-sonnet-4-5"]
    if m and prov == "github":
        return [m]
    cands = PROVIDERS[prov][2]
    cands = [cands] if isinstance(cands, str) else list(cands)
    ok = _model_ok.get(prov)
    if ok in cands:
        cands.remove(ok)
        cands.insert(0, ok)
    return cands


def _model_for(prov):
    """Перша (найкраща) модель провайдера — для логів і зворотної сумісності."""
    return _models_for(prov)[0]


def _model_missing(e):
    """Чи це «такої моделі нема», а не «ліміт» і не «ключ поганий».

    404 і 400 провайдери віддають саме на невідому назву моделі. Відрізнити це
    від 429/402/403 критично: там треба чекати, а тут — просто взяти іншу назву."""
    if e.code not in (400, 404):
        return False
    try:
        body = e.read().decode("utf-8", "replace").lower()
    except Exception:
        return e.code == 404
    return "model" in body or e.code == 404


def _quota_left(prov):
    """False, якщо вибрано задекларований добовий ліміт провайдера."""
    cap = PROVIDERS.get(prov, (None, None, None, None, 0))[4]
    return True if not cap else _used.get(prov, 0) < cap


def _throttle(prov, pause):
    dt = time.time() - _last_call.get(prov, 0.0)
    if dt < pause:
        time.sleep(pause - dt)
    _last_call[prov] = time.time()


def _post(url, body, headers, timeout=120):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _anthropic(system, user_json):
    d = _post("https://api.anthropic.com/v1/messages",
              {"model": _model_for("anthropic"), "max_tokens": 4000, "system": system,
               "messages": [{"role": "user", "content": user_json}]},
              {"x-api-key": os.environ["ANTHROPIC_API_KEY"],
               "anthropic-version": "2023-06-01", "content-type": "application/json"})
    return "".join(b.get("text", "") for b in d.get("content", []) if b.get("type") == "text")


def _openai_compat(prov, system, user_json):
    """Пробує моделі-кандидати по черзі; «нема такої моделі» -> наступна назва.

    Помилки ліміту (429/402/403) НЕ ковтаємо — вони мають дійти до _ai_call,
    щоб той поставив провайдера в cooldown і пішов на наступну сходинку."""
    _u, envk, _m, pause, _cap = PROVIDERS[prov]
    key = os.environ.get(envk) or os.environ.get("AI_TOKEN", "")
    url = _url_for(prov)
    models = _models_for(prov)
    last = None
    for i, model in enumerate(models):
        _throttle(prov, pause)
        try:
            d = _post(url, {"model": model, "temperature": 0.3,
                            "response_format": {"type": "json_object"},
                            "messages": [{"role": "system", "content": system},
                                         {"role": "user", "content": user_json}]},
                      {"Authorization": "Bearer " + key, "Content-Type": "application/json"})
        except urllib.error.HTTPError as e:
            if _model_missing(e) and i + 1 < len(models):
                print(f"[ai] {prov}: моделі «{model}» нема ({e.code}) — пробую «{models[i + 1]}»")
                last = e
                continue
            raise
        if _model_ok.get(prov) != model:
            _model_ok[prov] = model          # запам'ятали робочу назву на весь прогін
            print(f"[ai] {prov}: працює модель «{model}»")
        return d["choices"][0]["message"]["content"]
    raise last if last else RuntimeError(f"{prov}: не лишилось моделей-кандидатів")


def _retry_after(e, default):
    """429 буває хвилинний (tokens/minute) і добовий. Retry-After каже, який саме."""
    try:
        v = e.headers.get("Retry-After") or e.headers.get("retry-after")
        if v:
            return max(5.0, min(float(v), 86400.0))
    except Exception:
        pass
    return default


def _ai_call(system, user_json):
    """Йде сходами: 429/ліміт -> провайдер у cooldown, беремо наступного."""
    ladder = _ladder()
    if not ladder:
        return None
    for prov in ladder:
        if _cooldown.get(prov, 0) > time.time() or not _quota_left(prov):
            continue
        try:
            if prov == "anthropic":
                txt = _anthropic(system, user_json)
            else:
                txt = _openai_compat(prov, system, user_json)
            _used[prov] = _used.get(prov, 0) + 1
            return txt
        except urllib.error.HTTPError as e:
            if e.code in (429, 402, 403):
                pause = _retry_after(e, float(os.environ.get("AI_COOLDOWN", "900")))
                _cooldown[prov] = time.time() + pause
                print(f"[ai] {prov}: ліміт {e.code}, пауза {int(pause)}с — беру наступного")
            else:
                print(f"[ai] {prov}: HTTP {e.code} — наступний провайдер")
        except Exception as e:
            print(f"[ai] {prov}: {str(e)[:90]} — наступний провайдер")
    return None


def usage_report():
    """Скільки запитів на якому провайдері й якою моделлю — у лог наприкінці прогону.

    Модель тут не для краси: якщо провайдер перейменував модель, у звіті буде
    видно, що спрацював запасний кандидат, — сигнал оновити таблицю PROVIDERS."""
    if not _used:
        return "ШІ не викликався"
    parts = []
    for p, n in sorted(_used.items(), key=lambda x: -x[1]):
        m = _model_ok.get(p)
        parts.append(f"{p}:{n}" + (f" ({m})" if m else ""))
    return ", ".join(parts)


# ---------------- захист від вигаданих номерів / кузовів / років ----------------
_NUM = re.compile(r"\b[0-9A-Za-z][0-9A-Za-z.\-/ ]{5,}[0-9A-Za-z]\b")
_BODY = re.compile(r"\b[EFGIU]\d{2,3}\b")            # кузови BMW: E90, F30, G20, U06
_YEAR = re.compile(r"\b(19[5-9]\d|20[0-4]\d)\b")     # роки випуску


def _norm(s):
    if isinstance(s, dict):
        s = s.get("value") or s.get("number") or s.get("article") or ""
    return re.sub(r"[^0-9a-z]", "", str(s or "").lower())


def _facts_blob(facts):
    """Увесь текст фактів одним нормалізованим рядком — для перевірки кузовів і років."""
    return re.sub(r"[^0-9a-zа-яіїєґ]", "", json.dumps(facts, ensure_ascii=False).lower())


def numbers_ok(ai, facts):
    """True, якщо в назвах і мета-полях нема жодного номера, кузова чи року,
    якого не було у фактах. Опис не чіпаємо (там номери йдуть у зв'язному тексті),
    але назва — обличчя картки і головне джерело збігу в пошуку Prom."""
    allowed = {_norm(facts.get("article"))}
    for k in ("oem", "analogs"):
        for v in facts.get(k) or []:
            allowed.add(_norm(v))
    allowed.discard("")
    blob = _facts_blob(facts)
    bad = []
    for k in ("name_ru", "name_ua", "meta_title_ru", "meta_title_ua"):
        txt = str(ai.get(k) or "")
        if allowed:
            for cand in _NUM.findall(txt):
                c = _norm(cand)
                if len(c) < 6 or not any(ch.isdigit() for ch in c):
                    continue
                if not any(c in a or a in c for a in allowed):
                    bad.append(f"{k}:{cand.strip()}")
        for cand in _BODY.findall(txt) + _YEAR.findall(txt):
            if _norm(cand) not in blob:
                bad.append(f"{k}:{cand}")
    if bad:
        print(f"[ai] ⛔ вигадано у назві ({'; '.join(sorted(set(bad))[:3])}) — картку не беру")
        return False
    return True


# ---------------------------------------------------------------- виклики
def enrich_facts(facts, thin=False):
    """Готові факти -> JSON з 10 полями або None.
    thin=True — профіль «інший постачальник»: тільки артикул+назва+бренд,
    ШІ забороняється домальовувати сумісність."""
    # НІКОЛИ не додавати сюди ціну/собівартість/дилерські умови — це йде до третьої сторони.
    payload = json.dumps(facts, ensure_ascii=False, sort_keys=True)
    key = ("thin:" if thin else "full:") + payload
    if key in _memo:
        return _memo[key]
    try:
        txt = _ai_call(PROM_AI_SYSTEM_THIN if thin else PROM_AI_SYSTEM, payload)
        if not txt:
            return None
        mt = re.search(r"\{.*\}", txt, re.S)
        ai = json.loads(mt.group(0)) if mt else None
        if ai and not numbers_ok(ai, facts):
            return None
        _memo[key] = ai
        return ai
    except Exception as e:
        print(f"[ai] пропуск ({str(e)[:100]})")
        return None


def ai_enrich(product, clean_details_fn, fitment_fn, thin=False):
    """Факти BM Parts -> JSON з 10 полями або None."""
    oem, repl = oem_and_replacements(product)
    facts = {"article": product.get("article"), "brand": product.get("brand"),
             "name": product.get("name"), "nodes": product.get("nodes"),
             "oem": oem[:10], "analogs": repl[:10],
             "details": [{"name": n, "unit": u, "value": v} for (n, u, v) in clean_details_fn(product)],
             "fitment": fitment_fn(product, product.get("name") or "")}
    return enrich_facts(facts, thin=thin)


def merge_ai(f, ai):
    """Перезаписує РІВНО 10 текстових полів; технічні поля AI не чіпає."""
    def g(*ks):
        for k in ks:
            v = ai.get(k)
            if v:
                return v
        return None

    def joinkw(v):
        return ", ".join(str(x) for x in v) if isinstance(v, list) else str(v)

    mp = {"Назва_позиції": g("name_ru"), "Назва_позиції_укр": g("name_ua"),
          "Пошукові_запити": joinkw(g("keywords_ru")) if g("keywords_ru") else None,
          "Пошукові_запити_укр": joinkw(g("keywords_ua")) if g("keywords_ua") else None,
          "Опис": g("desc_ru"), "Опис_укр": g("desc_ua"),
          "HTML_заголовок": g("meta_title_ru"), "HTML_заголовок_укр": g("meta_title_ua"),
          "HTML_опис": g("meta_desc_ru"), "HTML_опис_укр": g("meta_desc_ua")}
    for k, v in mp.items():
        if v:
            v = str(v)
            # clean_name прибирає дефіси/подвійні пробіли і ріже до 110 —
            # раніше не викликався, і назва з дефісом доходила до Export.
            f[k] = clean_name(v) if k.startswith("Назва") else v


# ======================================================================== #
#                        АУДИТ ГОТОВОЇ КАРТКИ (ДОРАДЧИЙ)                   #
# ======================================================================== #
# 27.07. Власник поставив вимогу: «ШІ повинен усе перевіряти, за жорсткими
# правилами Prom та Google». Тут — ДРУГА половина цієї вимоги; перша (та, що
# реально вирішує) живе в коді:
#
#   card_builder.enforce_limits() — ШЛЮЗ. Рахує довжини, кількості, ріже
#       заборонені слова. Викликається ПІСЛЯ merge_ai(), тому жодна відповідь
#       ШІ не пролазить у бойову таблицю повз межі Prom.
#   validator.validate_*()        — ОЦІНКА. Пише в звіт, що саме не так.
#   audit_card() (нижче)          — ДРУГА ДУМКА. Бачить те, чого не порахуєш
#       формулою: «тип деталі не першим словом», «ключовики — це окремі слова,
#       а не запити», «опис не пояснює, куди ця деталь ставиться».
#
# ЧОМУ ШІ ТУТ НЕ МОЖЕ БУТИ СУДДЕЮ. Ключа може не бути взагалі (усі ключі
# опційні), добова квота може вичерпатись на середині каталогу, провайдер може
# лежати, а модель — вигадати зауваження на порожньому місці. Якби публікація
# залежала від відповіді ШІ, будь-яка з цих чотирьох подій зупиняла б додавання
# позицій. Тому audit_card() НІКОЛИ не змінює картку й НІКОЛИ не блокує запис:
# повертає зауваження, вони лягають у колонку «Статус» огляду, а рішення
# «Export чи Staging» як стояло на коді, так і стоїть.
AUDIT_SYSTEM = (
    "Ти прискіпливий редактор карток маркетплейсу Prom.ua, спеціалізація автозапчастини. "
    "Отримуєш ГОТОВУ картку і перевіряєш її за правилами Prom і Google. "
    "Ти НЕ переписуєш картку і НЕ повертаєш виправлених текстів — лише перелік зауважень.\n"
    "ЖОРСТКІ МЕЖІ (порушення = обов'язкове зауваження):\n"
    "1. Назва <=110 символів, ТИП ДЕТАЛІ першим словом, без дефісів, без ВЕЛИКИХ ЛІТЕР, "
    "без слів 'купити/оптом/недорого'. Каталожні номери — лише суцільно (11427953129).\n"
    "2. Мета-заголовок <=70 символів і містить каталожний номер.\n"
    "3. Мета-опис <=160 символів і містить каталожний номер.\n"
    "4. Пошукові запити: 15-40 штук, кожен — ЦІЛА фраза, яку людина вводить у пошук "
    "('масляний фільтр BMW F30'), а не окреме слово ('фільтр'). Без міст і областей, "
    "без дужок і сміття, без повторів.\n"
    "5. Опис: 400-800 корисних символів без урахування тегів; має бути блок сумісності "
    "('Підходить на …'), OEM/аналоги і заклик 'Ми підберемо за вас'. Без телефонів, "
    "посилань і месенджерів.\n"
    "6. Характеристики: щонайменше 3, значення реальні, одиниці виміру зі списку Prom.\n"
    "7. ГОЛОВНЕ ПРАВИЛО ВЛАСНИКА: позицію мусить знайти покупець — за повною назвою, "
    "АБО за каталожним номером, АБО просто за машиною, на яку вона підходить. "
    "Якщо цього не буде видно з назви й запитів — це зауваження.\n"
    "8. Нічого вигаданого: жодних номерів, кузовів, двигунів і років, яких немає у "
    "вхідних даних картки.\n"
    "Поверни СТРОГО JSON: {\"verdict\":\"ok\" або \"fix\", \"score\": ціле 0-100, "
    "\"issues\":[{\"field\":\"назва|мета|запити|опис|характеристики|пошук\","
    "\"why\":\"одне речення українською, конкретно\"}]}. "
    "Якщо порушень немає — verdict 'ok' і порожній issues. Максимум 6 зауважень, "
    "тільки найважливіші. Не хвали, не переказуй картку, не пиши вступів."
)

# Рівно ті поля картки, які їдуть на аудит. Це БІЛИЙ СПИСОК, а не «усе, крім».
# Причина та сама, що і в enrich_facts(): у словнику f лежать «Ціна», «Собівартість»
# і наявність, а це йде до третьої сторони. Білий список означає, що навіть якщо
# завтра в картку додадуть нове грошове поле, воно НЕ поїде назовні саме собою —
# щоб його відправити, треба свідомо дописати назву сюди.
_AUDIT_FIELDS = ("Назва_позиції", "Назва_позиції_укр",
                 "Пошукові_запити", "Пошукові_запити_укр",
                 "HTML_заголовок", "HTML_заголовок_укр",
                 "HTML_опис", "HTML_опис_укр",
                 "Опис", "Опис_укр")
_AUDIT_CUT = {"Опис_укр": 3000, "Опис": 800}   # рос. опис — дзеркало укр., шлемо шматок
_AUDIT_MAX_ISSUES = 6
_AUDIT_ISSUE_LEN = 120
_audit_memo = {}


def audit_on():
    """Чи вмикати аудит. AI_AUDIT=0 — вимкнути (аудит подвоює витрату квоти:
    один виклик на створення картки, другий на перевірку). За замовчуванням
    УВІМКНЕНО — власник просив, щоб ШІ перевіряв усе."""
    v = (os.environ.get("AI_AUDIT") or "1").strip().lower()
    return v not in ("0", "false", "off", "ні", "нi", "no", "без")


def _audit_payload(f, chars=None, images=None, article="", group=""):
    """Картка -> факти для аудиту. Без цін, без собівартості, без наявності."""
    card = {}
    for k in _AUDIT_FIELDS:
        v = str((f or {}).get(k) or "").strip()
        if not v:
            continue
        cut = _AUDIT_CUT.get(k)
        card[k] = v[:cut] if cut else v
    card["Артикул"] = str(article or (f or {}).get("Код_товару") or "")
    card["Група"] = str(group or (f or {}).get("Номер_групи") or "")
    card["Характеристики"] = [{"назва": n, "одиниця": u, "значення": v}
                              for (n, u, v) in (chars or [])]
    card["Фото"] = len([u for u in (images or []) if u])
    return card


def _clip(s, n=_AUDIT_ISSUE_LEN):
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s[:n]


def _norm_audit(raw):
    """Що б не повернула модель — привести до одного передбачуваного вигляду.

    Моделі різних провайдерів відповідають по-різному: хтось кладе список у
    'problems', хтось повертає рядки замість об'єктів, хтось пише verdict='FAIL'.
    Розбирати це на місці виклику не можна — тоді кожна нова сходинка провайдерів
    ламала б звіт. Тому нормалізація одна й тут."""
    if not isinstance(raw, dict):
        return None
    items = raw.get("issues") or raw.get("problems") or raw.get("зауваження") or []
    if isinstance(items, dict):
        items = list(items.values())
    if isinstance(items, str):
        items = [items]
    issues = []
    for it in items if isinstance(items, list) else []:
        if isinstance(it, dict):
            field = _clip(it.get("field") or it.get("поле") or "", 24)
            why = _clip(it.get("why") or it.get("чому") or it.get("issue") or it.get("message"))
            txt = f"{field}: {why}" if field and why else (why or field)
        else:
            txt = _clip(it)
        if txt:
            issues.append(txt)
    issues = issues[:_AUDIT_MAX_ISSUES]

    v = str(raw.get("verdict") or raw.get("вердикт") or "").strip().lower()
    ok = v in ("ok", "оk", "good", "pass", "так", "усе добре", "все добре")
    verdict = "ok" if (ok and not issues) else ("fix" if issues else "ok")

    try:
        score = int(float(raw.get("score", raw.get("оцінка", 0)) or 0))
    except Exception:
        score = 0
    score = max(0, min(100, score))
    return {"verdict": verdict, "score": score, "issues": issues}


def audit_card(f, chars=None, images=None, article="", group="", use_ai=True):
    """Друга думка ШІ про ГОТОВУ картку. Повертає dict або None.

    None — це НЕ помилка й не «картка погана». Це штатний стан: нема ключів,
    вимкнено AI_AUDIT, вичерпано квоту, провайдер не відповів або віддав не JSON.
    Викликач у такому разі просто нічого не дописує в статус і публікує картку
    так само, як публікував би без ШІ взагалі.

    Словник f НЕ змінюється — навмисно: аудит не має права правити картку, бо
    правки нікому було б перевірити. Він тільки називає проблему словами."""
    if not use_ai or not audit_on():
        return None
    facts = _audit_payload(f, chars=chars, images=images, article=article, group=group)
    payload = json.dumps(facts, ensure_ascii=False, sort_keys=True)
    if payload in _audit_memo:
        return _audit_memo[payload]
    try:
        txt = _ai_call(AUDIT_SYSTEM, payload)
        if not txt:
            return None
        mt = re.search(r"\{.*\}", txt, re.S)
        if not mt:
            return None
        res = _norm_audit(json.loads(mt.group(0)))
    except Exception as e:
        print(f"[ai] аудит пропущено ({str(e)[:100]})")
        return None
    if res is not None:
        _audit_memo[payload] = res
    return res


def audit_line(res):
    """Один короткий рядок для колонки «Статус» в «Огляд_Додавання».

    Префікс «ШІ:» тут обов'язковий: у тій самій клітинці вже стоїть вердикт
    валідатора, і власник має з першого погляду бачити, де порахував код (це
    факт), а де висловився ШІ (це думка, яку можна й проігнорувати)."""
    if not res:
        return ""
    if res["verdict"] == "ok" and not res["issues"]:
        return "ШІ: ок"
    return "ШІ: " + "; ".join(res["issues"][:3])
