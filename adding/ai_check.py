# -*- coding: utf-8 -*-
"""ПЕРЕВІРКА ШІ — окрема функція (MODE=ai_check).

НАВІЩО ОКРЕМО. Досі стан ШІ можна було дізнатись лише побічно: запустити
збірку карток і подивитись, що написано в журналі. Це погано з двох причин.
По-перше, збірка витрачає добовий ліміт провайдера на діагностику. По-друге,
вона показує лише ПЕРШУ сходинку, що спрацювала: якщо відповів gemini, про
решту ключів не буде ні слова — живі вони чи мертві, невідомо. Додали ключ і
хочете знати, чи він робочий, — доводилось гадати.

Тут навпаки: перевіряємо КОЖНОГО провайдера по черзі, до кінця, і кажемо про
кожного окремо. Один крихітний запит на провайдера — це дешевше за одну картку.

ЩО ЙДЕ В ЗАПИТІ. Рівно два рядки: «Відповідай одним словом» і «Напиши слово:
OK». Жодного артикулу, назви, ціни, собівартості чи дилерських умов — те саме
правило, що й для ai_enrich/audit_card: комерційні дані до третьої сторони не
їдуть НІКОЛИ. Тест test_ai_check.py це стереже.

ЩО ВІДРІЗНЯЄМО. Для перевірки важлива різниця, яку бойові сходи можуть собі
дозволити ігнорувати:
    нема ключа        — секрет не заданий, сходинка просто не існує;
    ключ не приймається — секрет заданий, але провайдер його не впізнав
                          (тобто ключ зіпсутий/чужий/протух) — це помилка власника;
    ліміт             — ключ ЖИВИЙ, просто вичерпано добову квоту; завтра сам оживе;
    нема робочої моделі — ключ живий, але всі назви моделей у таблиці протухли;
    працює            — і назва моделі, що реально відповіла.
Сплутати «ключ поганий» і «ліміт» — найдорожча помилка діагностики: у першому
випадку треба йти міняти секрет, у другому — не робити нічого.
"""
import json
import os
import urllib.error
import urllib.request

from adding import ai_layer as ai

# Нейтральний пінг. НІКОЛИ не додавати сюди дані товару, ціну, собівартість
# чи умови постачальника — це йде на сервер третьої сторони.
PING_SYSTEM = "Відповідай одним словом, без розділових знаків."
PING_USER = "Напиши слово: OK"

LABEL = {
    "ok":       "✅ працює",
    "limit":    "⏳ ключ живий, вичерпано ліміт",
    "denied":   "⛔ ключ є, доступ закрито",
    "bad_key":  "❌ ключ не приймається",
    "no_model": "⚠️ ключ живий, але жодна назва моделі не підійшла",
    "no_key":   "— нема ключа",
    "no_acct":  "⚠️ є CF_API_TOKEN, але нема CF_ACCOUNT_ID",
    "error":    "⚠️ не відповів",
}
# Стани, за яких провайдер реально дасть картку зараз.
GOOD = ("ok",)
# Стани, за яких ключ у секретах Є і він справжній (просто зараз недоступний).
ALIVE = ("ok", "limit", "denied", "no_model")


def _body(e):
    """Текст помилки одним рядком у нижньому регістрі. Читаємо РІВНО раз:
    urllib віддає тіло потоком, другий read() повернув би порожньо."""
    if not hasattr(e, "_pa_body"):
        try:
            e._pa_body = e.read().decode("utf-8", "replace").lower()
        except Exception:
            e._pa_body = ""
    return e._pa_body


def _bad_key(code, body):
    """Чи це «ключ не той». 401 — однозначно. Але Google на зіпсований ключ
    віддає 400 з текстом «API key not valid», і без розбору тіла це виглядало б
    як «нема такої моделі» — тобто власник пішов би шукати неіснуючу проблему."""
    if code == 401:
        return True
    if "api key" in body and ("not valid" in body or "invalid" in body or "expired" in body):
        return True
    return "unauthorized" in body or "invalid_api_key" in body


def _no_model(code, body):
    """Чи це «нема такої моделі» — те саме правило, що в бойових сходах."""
    if code not in (400, 404):
        return False
    return code == 404 or "model" in body


def _hint(prov):
    """Слово, за яким упізнаємо «свої» моделі у списку провайдера.

    Беремо перший корінь першого кандидата: «gemma-3-27b-it» -> «gemma»,
    «@cf/meta/llama-3.3-70b» -> «llama». Це не точна наука, а фільтр, щоб
    у звіт не висипався весь каталог із сотні назв."""
    first = (ai.PROVIDERS.get(prov, ("", "", ("",)))[2] or ("",))[0]
    tail = str(first).split("/")[-1]
    return tail.split("-")[0].lower()


def _available_models(prov, timeout=15):
    """Які назви моделей провайдер визнає НАСПРАВДІ (список, не пінг).

    НАВІЩО. Стан «жодна назва не підійшла» сам по собі — глухий кут: ключ
    живий, сходинка мертва, а що вписати замість протухлої назви — невідомо.
    Тут ми питаємо в самого провайдера його ж список і кладемо кілька схожих
    назв прямо у звіт, щоб їх лишалось тільки скопіювати в AI_MODEL_<...>.

    Це GET по OpenAI-сумісному шляху /models. Жодних даних товару, ціни чи
    умов постачальника тут немає й бути не може — ми нічого не надсилаємо."""
    url = ai._url_for(prov)
    if not url.endswith("/chat/completions"):
        return []
    key = os.environ.get(ai.PROVIDERS[prov][1]) or os.environ.get("AI_TOKEN", "")
    req = urllib.request.Request(
        url[:-len("/chat/completions")] + "/models",
        headers={"Authorization": "Bearer " + key})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read().decode("utf-8"))
    except Exception:
        return []
    names = []
    for m in (d.get("data") or []):
        n = str(m.get("id") or "").strip()
        # Google віддає ідентифікатори як «models/gemma-3-27b-it» — у запиті
        # ж працює короткий вигляд, тому префікс одразу зрізаємо.
        if n.startswith("models/"):
            n = n[len("models/"):]
        if n:
            names.append(n)
    hint = _hint(prov)
    same = [n for n in names if hint in n.lower()]
    return (same or names)[:8]


def _request(prov, model, timeout):
    """Один пінг. Повертає текст відповіді або кидає HTTPError/Exception."""
    if prov == "anthropic":
        d = ai._post("https://api.anthropic.com/v1/messages",
                     {"model": model, "max_tokens": 16,
                      "messages": [{"role": "user", "content": PING_USER}]},
                     {"x-api-key": os.environ.get("ANTHROPIC_API_KEY", ""),
                      "anthropic-version": "2023-06-01",
                      "content-type": "application/json"}, timeout=timeout)
        return "".join(b.get("text", "") for b in d.get("content", [])
                       if b.get("type") == "text")
    envk = ai.PROVIDERS[prov][1]
    key = os.environ.get(envk) or os.environ.get("AI_TOKEN", "")
    # response_format тут НЕ ставимо: половина провайдерів віддає на нього 400,
    # і перевірка ключа перетворилась би на перевірку підтримки JSON-режиму.
    d = ai._post(ai._url_for(prov),
                 {"model": model, "max_tokens": 16, "temperature": 0,
                  "messages": [{"role": "system", "content": PING_SYSTEM},
                               {"role": "user", "content": PING_USER}]},
                 {"Authorization": "Bearer " + key,
                  "Content-Type": "application/json"}, timeout=timeout)
    return d["choices"][0]["message"]["content"]


def ping(prov, timeout=25):
    """Стан одного провайдера: dict(prov, state, model, detail, answer).

    Моделі перебираємо так само, як бойові сходи: 404 «нема моделі» -> наступна
    назва. Помилки ліміту й ключа перебором НЕ лікуються — виходимо одразу,
    інакше один вичерпаний ключ дав би три однакові 429 замість одного."""
    res = {"prov": prov, "state": "no_key", "model": "", "detail": "",
           "answer": "", "offer": []}
    if not ai._ready(prov):
        # Cloudflare без ID акаунта — це не «нема ключа», а недороблене
        # налаштування; сказати про це прямо дешевше, ніж потім ловити 404.
        if prov != "anthropic" and os.environ.get(ai.PROVIDERS[prov][1]) \
                and "{acct}" in ai.PROVIDERS[prov][0]:
            res["state"] = "no_acct"
        return res

    pause = 0.0 if prov == "anthropic" else min(ai.PROVIDERS[prov][3], 3.0)
    models = ai._models_for(prov)
    for i, model in enumerate(models):
        res["model"] = model
        ai._throttle(prov, pause)
        try:
            txt = _request(prov, model, timeout)
        except urllib.error.HTTPError as e:
            body = _body(e)
            if _bad_key(e.code, body):
                res["state"], res["detail"] = "bad_key", f"HTTP {e.code}"
                return res
            if e.code == 429:
                res["state"], res["detail"] = "limit", "HTTP 429"
                return res
            if e.code == 402:
                res["state"], res["detail"] = "limit", "HTTP 402 (квота вичерпана)"
                return res
            if e.code == 403:
                res["state"], res["detail"] = "denied", "HTTP 403"
                return res
            if _no_model(e.code, body) and i + 1 < len(models):
                continue
            if _no_model(e.code, body):
                res["state"], res["detail"] = "no_model", f"HTTP {e.code}"
                res["offer"] = _available_models(prov)
                return res
            res["state"], res["detail"] = "error", f"HTTP {e.code}"
            return res
        except Exception as e:
            res["state"], res["detail"] = "error", str(e)[:70]
            return res
        ai._model_ok[prov] = model
        res["state"] = "ok"
        res["answer"] = str(txt or "").strip()[:40]
        return res
    res["state"] = "no_model"
    res["offer"] = _available_models(prov)
    return res


def check_all(timeout=25):
    """Усі провайдери зі сходів, у порядку ORDER. Перевіряємо ВСІХ, навіть тих,
    кого зараз вимкнено через AI_PROVIDERS: власник має бачити повну картину,
    а не лише той підмножину, яку сам звузив."""
    raw = (os.environ.get("AI_PROVIDERS") or "").strip()
    picked = {p.strip().lower() for p in raw.split(",") if p.strip()}
    out = []
    for prov in ai.ORDER:
        r = ping(prov, timeout=timeout)
        r["in_ladder"] = (not picked) or prov in picked
        out.append(r)
    return out


def summary(results):
    """Один рядок для клітинки Q1 — коротко й без емодзі-каші."""
    ok = [r for r in results if r["state"] == "ok"]
    lim = [r for r in results if r["state"] in ("limit", "denied")]
    bad = [r for r in results if r["state"] in ("bad_key", "no_model", "error", "no_acct")]
    parts = []
    if ok:
        parts.append("працюють " + ", ".join(
            f"{r['prov']} ({r['model']})" for r in ok[:4]))
    else:
        parts.append("не працює ЖОДЕН провайдер")
    if lim:
        parts.append("ліміт: " + ", ".join(r["prov"] for r in lim))
    if bad:
        parts.append("проблема: " + ", ".join(f"{r['prov']} {LABEL[r['state']].split(' ', 1)[-1]}"
                                              for r in bad[:3]))
    no_key = [r["prov"] for r in results if r["state"] == "no_key"]
    if no_key:
        parts.append(f"без ключа {len(no_key)}")
    return ("перевірка ШІ: " + " | ".join(parts))[:400]


def report(results):
    """Повний звіт у журнал — по рядку на провайдера."""
    print("[ai-check] стан провайдерів:")
    for r in results:
        line = f"  {r['prov']:<11} {LABEL[r['state']]}"
        if r["state"] == "ok":
            line += f" — модель «{r['model']}»"
            if r["answer"]:
                line += f", відповідь «{r['answer']}»"
        elif r["detail"]:
            line += f" — {r['detail']}"
        if not r.get("in_ladder", True) and r["state"] in ALIVE:
            line += "  [вимкнено через AI_PROVIDERS]"
        print(line)
        # Підказка живими назвами: власнику лишається скопіювати одну з них,
        # а не гадати, чим замінити протухлу назву моделі.
        if r["state"] == "no_model" and r.get("offer"):
            print(f"      провайдер визнає: {', '.join(r['offer'])}")
            print(f"      постав AI_MODEL_{r['prov'].upper()}=<одна з них> "
                  f"або впиши її в PROVIDERS")
    alive = [r["prov"] for r in results if r["state"] in ALIVE]
    work = [r["prov"] for r in results if r["state"] in GOOD]
    print(f"[ai-check] ключів у секретах: {len(alive)}; працює зараз: {len(work)}")
    if not work:
        print("[ai-check] ⚠️ зараз не відповідає ЖОДЕН провайдер — картки "
              "збиратимуться без ШІ (це не помилка, але тексти будуть простіші)")
    return work


def run_check(sh=None, timeout=25):
    """Точка входу для MODE=ai_check. Пише підсумок у Q1, якщо є таблиця."""
    results = check_all(timeout=timeout)
    report(results)
    if sh is not None:
        from adding.panel import write_status
        write_status(sh, summary(results))
    return results
