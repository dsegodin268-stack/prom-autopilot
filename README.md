# Visimics Autopilot — платформа авто-наповнення Prom

Тягне дані постачальників (BM Parts API + прайси з пошти: Autonova, BMW, VAG, Porsche…),
рахує ціну за твоїм правилом націнки, будує заголовки/категорії, і генерує **Prom-YML фід**,
який Prom автоматично імпортує за URL. Оновлює **ціни + наявність + асортимент** щоніч.

## Архітектура
`suppliers/` — джерела (excel-прайс, bmparts_api) · `ingest/email_fetch.py` — забір із пошти (IMAP)
`engine/` — категоризація, заголовки, ціноутворення · `output/prom_yml.py` — генератор фіда
`main.py` — оркестратор · `config.yaml` — усі налаштування · `.github/workflows/` — щонічний cron

## Що робиш ТИ (кліки з паролями — я їх не роблю)
1. Створи приватний репозиторій на GitHub, залий цей код.
2. Settings → Secrets → додай: `MAIL_USER`, `MAIL_PASS` (app-password пошти),
   `BMPARTS_TOKEN` (токен BM Parts).
3. Увімкни GitHub Pages (гілка `gh-pages`). Фід буде за URL:
   `https://<user>.github.io/<repo>/prom.yml`
4. У Prom: Товари → Імпорт → **автоімпорт за посиланням** → встав цей URL → розклад.
5. У `config.yaml`: заміни блок `markup` на своє правило; впиши реальні `email_from`
   постачальників і `api_base` BM Parts (із доків).

## Що вже працює (протестовано)
- Парсинг прайсів BM Parts + VAG (14 997 позицій) → валідний Prom-YML.
- Дедуплікація по найдешевшому джерелу.
- Категорії + заголовки за формулою + ціна за правилом націнки.

## Поетапне впровадження
1. Ціни+наявність на наявних товарах (звузити фід до in-stock у `config`).
2. Підключити пошту (Autonova/VAG) — заповнити `email_from`.
3. Підключити BM Parts API (`bmparts_api.py`) — вставити ендпоінт/поля з доків, staged.
4. Асортимент: нові товари з фіда додаються в Prom автоматично.
5. Розширювати новими постачальниками — додати блок у `suppliers` конфіга.

## Локальний тест
`pip install -r requirements.txt && python main.py config.yaml` → `feed/prom.yml`

## Де хоститься фід (архітектура хостингу)
- **Збірка:** GitHub Actions (cron щоніч) — будує `feed/prom.yml`.
- **Хостинг (звідки Prom тягне):**
  - **Варіант A — Google Cloud Storage (рекомендовано, бо у вас уже так):** GitHub Actions
    заливає фід у існуючий GCS-бакет (`gcloud storage cp`), Prom тягне той самий URL.
    Потрібно: у GitHub → Variables додати `GCS_BUCKET=назва_бакета`; у Secrets — `GCP_SA_KEY`
    (JSON service-account з правом Storage Object Admin на бакет).
    Prom-import URL: `https://storage.googleapis.com/НАЗВА_БАКЕТА/prom.yml`
  - **Варіант B — GitHub Pages (безкоштовно, без хмари):** якщо `GCS_BUCKET` порожній —
    фід публікується на Pages: `https://<user>.github.io/<repo>/prom.yml`.
- **На боці Prom:** Товари → Імпорт → автоімпорт за посиланням → вставити URL фіда → розклад.

## Дашборд (де живе)
- Статичний інтерактивний дашборд `dashboard/index.html` + дані `dashboard/dashboard_data.json`.
- Щонічний прогін оновлює дані й кладе `dashboard.html` поряд із фідом → хоститься на
  **GitHub Pages / GCS** разом із `prom.yml`. URL: `https://<host>/dashboard.html`.
- Локально: `python build_dashboard.py` → відкрий `dashboard/index.html`.
- Автономна копія з вбудованими даними — `Visimics_Dashboard.html` (відкривається без сервера).
- Альтернатива нуль-коду: Looker Studio, підключений до Google-таблиці.

## Пошта (інтеграція)
`ingest/email_fetch.py`: IMAP (Gmail app-password у секретах), бере НАЙСВІЖІШИЙ лист від
відправника постачальника за `since_days`, витягує .xlsx, парсить за мапою колонок.
У `config.yaml` для постачальника: type: email, email_from, columns. Секрети: MAIL_USER, MAIL_PASS.
