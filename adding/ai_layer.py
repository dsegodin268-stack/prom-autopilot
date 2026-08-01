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
    gemma-4-31b       ~8600/добу      cerebras gpt-oss     ~400/добу
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
from adding import rules

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

# ------------------------------------------------------ КАРТКА З НУЛЯ (31.07)
# Окремий профіль для позицій, яких НЕМА в каталозі BM Parts: у прайсі
# постачальника є лише артикул, сира назва й ціна, а фото, характеристик,
# сумісності й категорії нема взагалі. Профіль THIN тут не годиться — він
# прямо забороняє знати сумісність, тобто картка назавжди лишалась би без
# «Сумісність з маркою/моделлю», а без них покупець не знайде її фасетним
# фільтром, і сенсу в такій позиції нема.
#
# Тому цей запит принципово ІНШИЙ за THIN і за повним:
#   • просимо не рекламний текст, а ТЕХНІЧНІ ФАКТИ (тип, категорія,
#     сумісність, характеристики) — маркетинг напише звичайний профіль потім,
#     уже маючи ці факти;
#   • назви характеристик — СТРОГО зі списку канону, інакше вони не потраплять
#     у блоки експорту й зникнуть мовчки;
#   • «не знаю» — це ПРАВИЛЬНА відповідь. Порожня картка їде в чернетку й чекає
#     людину; вигадана сумісність означає повернення товару й скаргу покупця,
#     а це дорожче за будь-яку незаповнену позицію.
#
# ЩО МИ СВІДОМО НЕ БЕРЕМО У МОДЕЛІ: OEM і крос-номери. Саме вони чіпляють
# позицію до крос-довідника Prom, тобто помилка в них приводить чужого покупця
# і гарантує повернення. Крос-номери лишаються порожніми, поки їх не дасть
# каталог або людина.
SCRATCH_CHARS = ("Тип запчастини", "Місце встановлення", "Матеріал", "Колір",
                 "Виробник", "Сторона встановлення", "Розмір", "Вага")

PROM_AI_SYSTEM_SCRATCH = (
    "Ти інженер-каталогізатор автозапчастин. Тобі дають артикул виробника, "
    "марку і сиру назву з прайсу. Картки цієї деталі в каталозі немає — треба "
    "відновити ТЕХНІЧНІ факти про неї.\n"
    "Поверни СТРОГО JSON з ключами: article, known, type, category, fitment, "
    "chars, note.\n"
    "  article  — той самий артикул, що прийшов, символ у символ.\n"
    "  known    — true, лише якщо ти впевнений, що це за деталь. Інакше false "
    "і всі решта полів порожні. «Не знаю» — нормальна відповідь.\n"
    "  type     — тип деталі українською, 1-3 слова: «фільтр масляний», "
    "«колодки гальмівні передні», «сайлентблок важеля».\n"
    "  category — категорія магазину українською, 1-2 слова: «Фільтри», "
    "«Гальмівна система», «Підвіска», «Двигун», «Кузов», «Оптика», "
    "«Електрика», «Салон», «Трансмісія», «Охолодження».\n"
    "  fitment  — масив рядків сумісності, формат «МАРКА МОДЕЛЬ КУЗОВ РОКИ», "
    "наприклад «BMW 3 F30 2011-2019». Тільки та марка, що прийшла у вхідних "
    "даних. Не впевнений у кузові — не пиши цей рядок узагалі. Порожній масив "
    "кращий за вигаданий кузов.\n"
    "  chars    — масив об'єктів {name, unit, value}. Поле name — СТРОГО одне "
    "зі списку: " + ", ".join(SCRATCH_CHARS) + ". Інші назви будуть відкинуті. "
    "Значення — коротке, без речень.\n"
    "  note     — один рядок, звідки впевненість (наприклад «типовий номер "
    "групи 11 — двигун BMW»), або порожньо.\n"
    "ЗАБОРОНЕНО: вигадувати OEM і крос-номери (їх не питаємо взагалі), "
    "вигадувати кузови, двигуни й роки заради заповненості, писати ціну, "
    "наявність, гарантію, терміни доставки, рекламні слова. "
    "Якщо артикул не схожий на жоден відомий тобі — known:false."
)

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
    # 01.08.2026: гілка gemma-3 знята з роздачі — усі три старі назви віддавали
    # 404, і сходинка мовчки не працювала. Назви нижче взяті не з голови, а зі
    # списку самого провайдера (MODE=ai_check, рядок «провайдер визнає»).
    "gemma": ("https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
              "GEMINI_API_KEY",
              ("gemma-4-31b-it", "gemma-4-26b-a4b-it"),
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


_SCRATCH_OK = {re.sub(r"\s+", " ", n).strip().lower() for n in SCRATCH_CHARS}


def _scratch_clean(ai, article, brand):
    """Відповідь профілю «з нуля» -> (fitment, chars, type, category) або None.

    Тут стоїть уся недовіра до моделі, і вона свідомо сувора:
      • артикул мусить повернутись той самий — інакше модель відповідала про
        іншу деталь (таке буває, коли вона «виправляє» номер на схожий);
      • known:false -> нічого не беремо взагалі;
      • рядок сумісності мусить починатися з НАШОЇ марки. Інакше в картку
        BMW заїжджає «Audi A4 B8», і покупець отримує не ту деталь;
      • назва характеристики — лише з канонічного списку, решта відкидається:
        Prom пише характеристики позиційно, і зайва назва не просто марна, вона
        зсуває блоки."""
    if not isinstance(ai, dict) or not ai.get("known"):
        return None
    if _norm(ai.get("article")) and _norm(ai.get("article")) != _norm(article):
        print(f"[ai] ⛔ з нуля: модель відповіла про «{ai.get('article')}», "
              f"а питали про «{article}» — не беру")
        return None
    b = str(brand or "").strip().lower()
    fit = []
    for line in (ai.get("fitment") or [])[:12]:
        s = re.sub(r"\s+", " ", str(line or "")).strip()
        if not s:
            continue
        if b and not s.lower().startswith(b):
            print(f"[ai] з нуля: «{s}» не про марку {brand} — відкидаю")
            continue
        if s not in fit:
            fit.append(s)
    chars, seen = [], set()
    for row in (ai.get("chars") or [])[:12]:
        if not isinstance(row, dict):
            continue
        nm = re.sub(r"\s+", " ", str(row.get("name") or "")).strip()
        val = re.sub(r"\s+", " ", str(row.get("value") or "")).strip()
        if not nm or not val or nm.lower() not in _SCRATCH_OK or nm.lower() in seen:
            continue
        if len(val) > 60:            # характеристика — не речення
            continue
        seen.add(nm.lower())
        chars.append((nm, str(row.get("unit") or "").strip(), val))
    typ = re.sub(r"\s+", " ", str(ai.get("type") or "")).strip()[:60]
    cat = re.sub(r"\s+", " ", str(ai.get("category") or "")).strip()[:40]
    if not (fit or chars or typ or cat):
        return None
    return fit, chars, typ, cat


def scratch_facts(article, brand="", name_src="", use_ai=True):
    """Технічні факти для позиції, якої нема в каталозі. None — модель не знає.

    Ціни, собівартості й умов постачальника в запиті нема — те саме правило,
    що для ai_enrich і ai_check: комерційні дані до третьої сторони не їдуть."""
    art = str(article or "").strip()
    if not use_ai or not art:
        return None
    facts = {"article": art, "brand": str(brand or "").strip(),
             "raw_name": str(name_src or "").strip()}
    payload = json.dumps(facts, ensure_ascii=False, sort_keys=True)
    ck = "scratch:" + payload
    if ck in _memo:
        return _memo[ck]
    try:
        txt = _ai_call(PROM_AI_SYSTEM_SCRATCH, payload)
        if not txt:
            return None
        mt = re.search(r"\{.*\}", txt, re.S)
        got = _scratch_clean(json.loads(mt.group(0)), art, brand) if mt else None
    except Exception as e:
        print(f"[ai] з нуля: пропуск ({str(e)[:100]})")
        return None
    _memo[ck] = got
    return got


def card_facts(product, clean_details_fn, fitment_fn):
    """Факти BM Parts у тому вигляді, у якому їх бачить ШІ.

    Винесено окремо 27.07: рівно ті самі факти потрібні ДВІЧІ — на створення
    картки і на другий прохід із зауваженнями (repair_fields). Дві копії цього
    словника розійшлися б, і перевірка numbers_ok() почала б рахувати «вигадки»
    від іншого набору дозволених номерів."""
    oem, repl = oem_and_replacements(product)
    # НІКОЛИ не додавати сюди ціну/собівартість/дилерські умови — це йде до третьої сторони.
    return {"article": product.get("article"), "brand": product.get("brand"),
            "name": product.get("name"), "nodes": product.get("nodes"),
            "oem": oem[:10], "analogs": repl[:10],
            "details": [{"name": n, "unit": u, "value": v} for (n, u, v) in clean_details_fn(product)],
            "fitment": fitment_fn(product, product.get("name") or "")}


def ai_enrich(product, clean_details_fn, fitment_fn, thin=False):
    """Факти BM Parts -> JSON з 10 полями або None."""
    return enrich_facts(card_facts(product, clean_details_fn, fitment_fn), thin=thin)


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
# Промпт аудиту НЕ пишеться руками. Він ГЕНЕРУЄТЬСЯ з того самого списку правил
# adding/rules.py, який читають шлюз і валідатор. Доти тут лежав переказ правил
# своїми словами — третя копія тих самих чисел, і вона вже розходилась із кодом:
# у промпті стояло «характеристик щонайменше 3», а валідатор вимагав 2.
# Приберете межу в rules.py — вона зникне і з коду, і з промпта одночасно.
AUDIT_SYSTEM = rules.audit_system()

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

# 27.07. Вимога власника: ШІ перевіряє ВСЮ картку, а не десять текстових полів.
# Технічні поля, які тепер теж їдуть на аудит. Вони не грошові й не таємні, зате
# саме на них ловляться найдорожчі помилки: назва каже «фільтр масляний», а група
# — «гальмівні диски»; у назві один артикул, а в адресі фото інший; вага 0,01 кг
# у гальмівного диска (це реальні гроші покупця на доставці).
# Ключ картки -> ім'я в payload. Перейменування навмисне: моделі краще відповідають
# на людські назви полів, ніж на «Вага,кг».
_AUDIT_TECH = {"Назва_групи": "Група_назва",
               "Виробник": "Виробник",
               "Код_маркування_(GTIN)": "GTIN",
               "Вага,кг": "Вага_кг",
               # 27.07-bis. Правило `section` має who='обидва', тобто вимога
               # перевірити підрозділ у промпті СТОЯЛА — а самих полів у payload
               # не було. Модель просили подивитись на те, чого їй не показали:
               # у кращому разі вона мовчала, у гіршому вигадувала зауваження.
               "Ідентифікатор_підрозділу": "Підрозділ_ID",
               "Посилання_підрозділу": "Підрозділ_посилання"}
# А ЦЬОГО назовні немає й не буде: ціна, собівартість, валюта, наявність,
# кількість. Наявність не йде свідомо — єдине правило про неї («в наявності»
# лише при відправці ≤3 днів) є чиста арифметика, її рахує код
# (rules.availability_ok + validator.validate_availability), і думка моделі тут
# не додає нічого, а поле про запаси магазину пішло б до третьої сторони.
_AUDIT_NEVER = ("Ціна", "Собівартість", "Валюта", "Наявність", "Кількість")
_AUDIT_IMG_MAX = 5    # більше й не треба: помилку видно вже на перших адресах
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


def _audit_payload(f, chars=None, images=None, article="", group="", known=()):
    """Картка -> факти для аудиту. Без цін, без собівартості, без наявності.

    27.07 payload розширено з 10 текстових полів до ВСІЄЇ картки, крім грошей:
    додались назва групи, виробник, GTIN, вага і справжні адреси фото (раніше
    їхала сама кількість — за числом «3» неможливо помітити, що всі три знімки
    ведуть на чужий артикул).

    known — те, що код УЖЕ порахував сам (перевірки за каноном з validator.py).
    Йде в payload окремим списком свідомо: модель має право повернути лише 6
    зауважень, і якщо вона витратить їх на переказ того, що й так порахував
    код, місця на власне спостереження не лишиться."""
    f = f or {}
    card = {}
    for k in _AUDIT_FIELDS:
        v = str(f.get(k) or "").strip()
        if not v:
            continue
        cut = _AUDIT_CUT.get(k)
        card[k] = v[:cut] if cut else v
    for k, out_name in _AUDIT_TECH.items():
        v = str(f.get(k) or "").strip()
        if v:
            card[out_name] = v
    card["Артикул"] = str(article or f.get("Код_товару") or "")
    card["Група"] = str(group or f.get("Номер_групи") or "")
    card["Характеристики"] = [{"назва": n, "одиниця": u, "значення": v}
                              for (n, u, v) in (chars or [])]
    # Фото: спершу справжній список, якщо викликач його дав; інакше — те, що вже
    # лежить у картці одним рядком через кому.
    urls = [str(u).strip() for u in (images or []) if str(u or "").strip()]
    if not urls:
        urls = [u.strip() for u in str(f.get("Посилання_зображення") or "").split(",")
                if u.strip()]
    card["Фото"] = urls[:_AUDIT_IMG_MAX]
    card["Фото_всього"] = len(urls)
    kn = [_clip(k) for k in (known or ()) if str(k or "").strip()]
    if kn:
        card["Вже_знайшов_код"] = kn[:_AUDIT_MAX_ISSUES]
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


def providers_ready():
    """Список провайдерів, у яких ЗАРАЗ є ключ. Порожній = ШІ не працюватиме.

    27.07. Додано після прогону №18: у логах не було жодного рядка «[ai]», а в
    колонці «Статус» — жодного зауваження. Виглядало так, ніби ШІ подивився й
    не знайшов проблем. Насправді ШІ не дивився взагалі: в репозиторії не було
    ключа жодного з 12 провайдерів, ladder виходив порожній, _ai_call повертав
    None, і мовчання неможливо було відрізнити від схвалення.

    Функція навмисно публічна: run.py друкує її результат ОДИН раз на прогін,
    щоб у журналі завжди було видно, чи ШІ взагалі міг працювати."""
    return _ladder()


def _canon_only(known):
    """Результат без ШІ: самі лише знахідки коду. Потрібен, бо канон мусить бути
    видно ЗАВЖДИ — і коли ключів нема, і коли вичерпано квоту."""
    kn = [_clip(k) for k in (known or ()) if str(k or "").strip()]
    if not kn:
        return None
    return {"verdict": "fix", "score": 0, "issues": kn[:_AUDIT_MAX_ISSUES], "ai": False}


def audit_card(f, chars=None, images=None, article="", group="", known=(), use_ai=True):
    """Друга думка ШІ про ГОТОВУ картку. Повертає dict або None.

    None — це НЕ помилка й не «картка погана». Це штатний стан: нема ключів,
    вимкнено AI_AUDIT, вичерпано квоту, провайдер не відповів або віддав не JSON.
    Викликач у такому разі просто нічого не дописує в статус і публікує картку
    так само, як публікував би без ШІ взагалі.

    known — знахідки коду за каноном (validator.validate_canon). Вони їдуть у
    payload, щоб модель не переказувала їх замість власних спостережень, і вони
    ж лишаються у відповіді, навіть якщо ШІ не відповів узагалі: розбіжність із
    канонічною таблицею — це ФАКТ, порахований кодом, і зникати разом із
    провайдером він не має права.

    Словник f НЕ змінюється — навмисно: аудит не має права правити картку, бо
    правки нікому було б перевірити. Він тільки називає проблему словами."""
    if not use_ai or not audit_on():
        return _canon_only(known)
    facts = _audit_payload(f, chars=chars, images=images, article=article,
                           group=group, known=known)
    payload = json.dumps(facts, ensure_ascii=False, sort_keys=True)
    if payload in _audit_memo:
        return _audit_memo[payload]
    try:
        txt = _ai_call(AUDIT_SYSTEM, payload)
        if not txt:
            return _canon_only(known)
        mt = re.search(r"\{.*\}", txt, re.S)
        if not mt:
            return _canon_only(known)
        res = _norm_audit(json.loads(mt.group(0)))
    except Exception as e:
        print(f"[ai] аудит пропущено ({str(e)[:100]})")
        return _canon_only(known)
    if res is None:
        return _canon_only(known)
    # Знахідки коду йдуть ПЕРШИМИ: вони точні, а зауваження моделі — дорадчі.
    kn = [_clip(k) for k in (known or ()) if str(k or "").strip()]
    merged, seen = [], set()
    for it in kn + res["issues"]:
        low = it.lower()
        if low in seen:
            continue
        seen.add(low)
        merged.append(it)
    res["issues"] = merged[:_AUDIT_MAX_ISSUES]
    res["ai"] = True
    if res["issues"]:
        res["verdict"] = "fix"
    _audit_memo[payload] = res
    return res


# ======================================================================== #
#                   ДРУГИЙ ПРОХІД: ШІ ДОПОВНЮЄ ЗА ЗАУВАЖЕННЯМИ             #
# ======================================================================== #
# Вимога власника 27.07: ШІ мусить не лише перевіряти, а й «доповнювати, і
# робити повноцінну картку, яка одразу залітає вже в кабінет». Дотепер аудит
# знаходив проблему — і на цьому все закінчувалось: зауваження лягало в колонку
# «Статус», а картка їхала в Export такою, як була.
#
# ЩО ЦЕЙ ПРОХІД МОЖЕ І ЧОГО НЕ МОЖЕ. Він переписує РІВНО ті самі 10 текстових
# полів, які ШІ й так автор (merge_ai), — назви, ключовики, описи, мету. Групи,
# ціни, наявності, характеристик, фото він не торкається ФІЗИЧНО: merge_ai не
# вміє писати в ці ключі. Це і є примирення з ПРАВИЛА §8 — заборона там не про
# «ШІ не має думати», а про «ШІ не має РУКИ» до технічних полів. Розбіжність із
# каноном не лікується текстом і йде на ручну курацію в Staging_Prom.
#
# Після правки картка ще раз проходить enforce_limits() і валідатор — останнє
# слово лишається за кодом, як і було.
_REPAIR_TAIL = (
    "\n\nЦЕ ДРУГИЙ ПРОХІД. У полі «поточна_картка» — те, що вже написано, у полі "
    "«зауваження» — що з цим не так. Перепиши поля так, щоб зауваження зникли, а "
    "все інше лишилось як є. Нових номерів, кузовів і років НЕ вигадуй: бери "
    "тільки те, що є у фактах."
)
REPAIR_SYSTEM = PROM_AI_SYSTEM + _REPAIR_TAIL

# Зауваження, за якими ШІ має право переписувати. Ключ — перше слово рядка
# «поле: чому» (формат задає rules.audit_system()). Усе інше — група, підрозділ,
# характеристики, вага, фото — свідомо НЕ тут: це технічні поля, їх ШІ не
# чіпає, і картка з такою проблемою їде на ручну курацію.
_REPAIR_FIELDS = ("назва", "мета", "запити", "опис", "пошук", "заголовок")
_REPAIR_TEXT = {"Назва_позиції", "Назва_позиції_укр", "Пошукові_запити",
                "Пошукові_запити_укр", "Опис", "Опис_укр", "HTML_заголовок",
                "HTML_заголовок_укр", "HTML_опис", "HTML_опис_укр"}
_fix_memo = {}


def repair_on():
    """AI_FIX=0 — вимкнути другий прохід. Він додає ТРЕТІЙ запит на позицію
    (створення + аудит + правка), а добова квота безкоштовних провайдерів
    рахується поштучно. Типово увімкнено — власник просив повноцінну картку."""
    v = (os.environ.get("AI_FIX") or "1").strip().lower()
    return v not in ("0", "false", "off", "ні", "нi", "no", "без")


def repairable(issues):
    """Зауваження -> лише ті, які лікуються переписуванням тексту.

    Рядки без префікса «поле:» (а такі дає перевірка коду за каноном) сюди НЕ
    потрапляють навмисно: «групи 999 немає в довіднику» не лікується красивішим
    описом, і просити модель це «виправити» — значить отримати вигадку."""
    out = []
    for it in issues or ():
        head = str(it).split(":", 1)[0].strip().lower()
        if head in _REPAIR_FIELDS:
            out.append(str(it))
    return out


def repair_fields(facts, issues, current=None, thin=False):
    """Факти + поточні тексти + зауваження -> ті самі 10 полів або None.

    None означає «лишаємо як було»: нема ключів, вичерпано квоту, модель
    відповіла не JSON або вигадала номер, якого нема у фактах. Жоден із цих
    випадків не має права зупинити публікацію."""
    fixes = repairable(issues)
    if not fixes:
        return None
    now = {k: str(v) for k, v in (current or {}).items() if k in _REPAIR_TEXT and v}
    payload = json.dumps({"факти": facts, "поточна_картка": now, "зауваження": fixes},
                         ensure_ascii=False, sort_keys=True)
    if payload in _fix_memo:
        return _fix_memo[payload]
    try:
        txt = _ai_call(REPAIR_SYSTEM if not thin else PROM_AI_SYSTEM_THIN + _REPAIR_TAIL,
                       payload)
        if not txt:
            return None
        mt = re.search(r"\{.*\}", txt, re.S)
        ai = json.loads(mt.group(0)) if mt else None
        if not ai:
            return None
        if not numbers_ok(ai, facts):
            return None
    except Exception as e:
        print(f"[ai] правку пропущено ({str(e)[:100]})")
        return None
    _fix_memo[payload] = ai
    return ai


def audit_line(res):
    """Один короткий рядок для колонки «Статус» в «Огляд_Додавання».

    Префікс обов'язковий, і їх ДВА. «ШІ:» — коли відповіла модель (це думка,
    яку можна й проігнорувати). «Канон:» — коли модель промовчала, а рядок усе
    одно є: значить, розбіжність із канонічною таблицею порахував код, і це
    факт. Плутати ці два джерела не можна, бо власник має з першого погляду
    бачити, кому вірити."""
    if not res:
        return ""
    # Типово «ШІ»: ключ 'ai' ставить лише той, хто знає протилежне
    # (_canon_only). Так старі виклики, що складали словник руками, лишаються
    # підписані так само, як були.
    tag = "ШІ" if res.get("ai", True) else "Канон"
    if res["verdict"] == "ok" and not res["issues"]:
        return f"{tag}: ок"
    return f"{tag}: " + "; ".join(res["issues"][:3])
