# Міграція на модульну структуру — 2026-07-24

## Що змінилося

**Нова структура:** 1 папка = 1 процес. `common/` (спільне ядро), `repricing/` (оновлення цін),
`adding/` (додавання позицій), `bmparts_mirror/` (дзеркало BM Parts), `competitors/` (скрапер),
`tools/` (проби), `tests/` (юніт-тести). Точки входу: `python -m <модуль>.run`.

## Мапа перенесення

| Було | Стало |
|---|---|
| `main.py` (710 рядків, все в одному) | `repricing/run.py` + `repricing/sources/*` + `guard.py` + `overrides.py` + `export_writer.py` + `report.py` |
| `bmparts.py` | `common/bmparts_client.py` (клієнт+факти) + `tools/bmparts_probe.py` (проба) |
| `add_positions.py` | `adding/run.py` + `adding/review.py` |
| `enrich_add.py` | `adding/card_builder.py` + `adding/groups.py` + `adding/ai_layer.py` |
| `validator.py` | `adding/validator.py` — ТЕПЕР ПІДКЛЮЧЕНИЙ у конвеєр (CRITICAL не пишеться) |
| `sync_bmparts.py` | `bmparts_mirror/run.py` |
| `ingest/scrape_competitors.py` | `competitors/scrape.py` |
| `anchor_prices.csv` | `repricing/data/anchor_prices.csv` |
| дублікати `final_price`/`num`/`_nkey` | ЄДИНА копія в `common/` |

## Видалено (мертвий код / за рішенням власника 24.07)

- **Старий прототип цілком:** `engine/`, `ingest/`, `output/`, `suppliers/` — жоден активний
  процес їх не використовував (єдиний споживач — мертвий `build_dashboard.py`).
- `build_dashboard.py` + `dashboard/` — застиглий локальний експеримент із мертвим шляхом пісочниці.
- `config.yaml`, `config.example.yaml` — ніким не читались, тарифи суперечили коду.
- `add.yml` у корені — неактивна копія workflow (файл-пастка; AI-ключі перенесено в активний).
- `__pycache__/` — з git, додано `.gitignore`.
- **AutoNova IMAP** (`pull_autonova`) — дублював Drive-канал, вимагав пароль від пошти,
  не вмів zip. Секрети `MAIL_USER`/`MAIL_PASS` більше не потрібні.
- **AutoNova статичний кеш** (`autonova_web_cache.csv`, 322 ціни, зібрані разово) — ціни
  ніколи не перевірялися. Замінено живим web-API (`AUTONOVA_COOKIE` + `AUTONOVA_PROXY`).

## Виправлені баги (знайдені при аналізі 24.07)

1. **Якірний захист УВІМКНЕНО.** У старому main.py `load_anchor`/`ANCHOR_FLOOR`/`MAX_DROP_PCT`
   були оголошені, але НІКОЛИ не викликались — LOCKED-рішення №5 не діяло. Тепер `repricing/guard.py`
   реально утримує ціни (нижче 60% якоря або падіння >25% без конкурента) зі статусом у «Звіт_Ціни».
2. **Єдине ціноутворення.** Було 4 копії (main.py, enrich_add.py, engine/pricing.py, config.yaml);
   enrich_add не мав MIN_MARKUP_ABS → нова картка отримувала іншу ціну, ніж нічний репрайсер.
   Тепер одна функція в `common/pricing.py`.
3. **AI-ключі доходять до CI.** Активний workflow add.yml не передавав ANTHROPIC_API_KEY /
   GH_MODELS_TOKEN / AI_MODEL (вони були лише в неактивній кореневій копії) → AI-шар мовчки
   не працював. Перенесено.
4. **Валідатор на воротах.** validate_card викликається перед записом у Export; CRITICAL —
   пропуск зі статусом у «Огляд_Додавання».
5. **nightly.yml: input `live`** — ручний запуск можна робити в DRY-RUN (live=0), не чіпаючи
   vars.LIVE; кнопка з таблиці працює як раніше (без input → vars.LIVE).
6. Прибрано невикористовувані env: PROM_API_KEY, LIVE_LIMIT, MAIL_USER, MAIL_PASS.

## Що НЕ змінювалося

Логіка водоспаду, тарифна сітка, формули пар BMW, brandId-евристики autonova, формат
«Звіт_Ціни», поведінка дзеркала BM Parts, Apps Script у таблиці, ПРАВИЛА_PROM.md.
