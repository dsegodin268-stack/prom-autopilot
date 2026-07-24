# Prom Autopilot (Visimics)

Автоматизація магазину автозапчастин **Visimics** на Prom.ua (~3900 позицій):
щоденний репрайсинг усього каталогу + конвеєр додавання нових позицій.

```
Постачальники                GitHub Actions                Google Таблиця (HUB)
BMW/Porsche Sheets  ─┐
AutoNova (Drive zip) ┼──►  nightly.yml → repricing ────►  Export Products Sheet ──► Prom (фід по URL)
AutoNova web-API     ┤                                    + Звіт_Ціни (журнал)
BM Parts API        ─┘     sync_bmparts.yml → mirror ──►  окрема книга «BM Parts»
                           add.yml → adding ───────────►  Огляд_Додавання → Export
```

## Модулі (1 папка = 1 процес)

| Модуль | Запуск | Що робить |
|---|---|---|
| `repricing/` | `python -m repricing.run` (nightly.yml, cron ~08:23 Київ + кнопка в таблиці) | Водоспад собівартості (BMW → Porsche → AutoNova-Drive → BMW-пари → autonova-web → BM Parts) → ціна за тарифом/конкурентом → **якірний захист** → запис Ціна/Наявність/Кількість в Export → «Звіт_Ціни» |
| `adding/` | `python -m adding.run` (add.yml, вручну) | review: нові коди BM Parts → «Огляд_Додавання»; enrich: відмічені «Взяти» → повна картка за ПРАВИЛА_PROM → **валідатор** → Export |
| `bmparts_mirror/` | `python -m bmparts_mirror.run` (sync_bmparts.yml, cron ~07:43) | Дзеркало наявності BM Parts (~125k) в окрему книгу |
| `competitors/` | вручну (потребує playwright) | Скрапер цін конкурентів з Prom → вкладка `competitors` |
| `common/` | — | Спільне ядро: **єдине ціноутворення**, нормалізація артикулів, Google-клієнти, клієнт BM Parts |
| `tools/` | `python -m tools.bmparts_probe` (bmparts_probe.yml) | Проба одного артикула / BULK-прайсу |
| `tests/` | `pytest tests/` (ci.yml на кожен push) | Тести чистих функцій (нормалізація, ціни, brandId, якір) |

## Ключові правила

- **DRY-RUN за замовчуванням**: запис у таблиці лише при `LIVE=1` (repo variable або input `live` у nightly).
- **Якірний захист** (`repricing/guard.py`): без конкурента/override ціна не пишеться, якщо вона
  нижча 60% якоря (`repricing/data/anchor_prices.csv`) або падає більш ніж на 25%. Утримані — у «Звіт_Ціни».
- **Валідатор** (`adding/validator.py`): CRITICAL-картки в Export не потрапляють.
- Артикули матчаться ТІЛЬКИ нормалізовано (`common/normalize._nkey`) — BM Parts зберігає коди з дефісами.
- AutoNova: прайс з Drive-теки (наповнює Apps Script у таблиці) + живий web-API під `AUTONOVA_COOKIE`
  (+ `AUTONOVA_PROXY` за потреби). IMAP-пошту і статичний кеш видалено 2026-07-24.

## Секрети (GitHub → Settings → Secrets)

`GCP_SA_KEY`, `BMPARTS` (env `BMPARTS_TOKEN`), `AUTONOVA_FOLDER_ID`, `AUTONOVA_COOKIE`,
`AUTONOVA_PROXY` (опц.), `ANTHROPIC_API_KEY` / `GH_MODELS_TOKEN` (опц., AI-шар додавання).
Variables: `LIVE`, `LIVE_ONLY`, `BMPARTS_BRANDS`, `BMPARTS_TAB_LIMIT`.

## Документація

- **PROJECT_HISTORY.md** — канонічна пам'ять проєкту (рішення власника, журнал змін).
- **ПРАВИЛА_PROM.md** — правила наповнення карток (назви, ключовики, описи, мета, характеристики).
- **MIGRATION_2026-07-24.md** — що і чому змінилося при переході на модульну структуру.
