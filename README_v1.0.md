# PriceIntel v1.0 — Production Release

**Made by Пума (Чернявський А.)**

v1.0 фіксує робочу production-базу після v0.9.

## Що увійшло
- balanced market: один незалежний майданчик/магазин = один голос;
- adaptive search: каскад продовжується, якщо незалежних кандидатних джерел замало;
- parallel prefetch сторінок;
- захист від подвійного запуску;
- безпечний F5 через POST/Redirect/GET;
- checkpoint/resume;
- hard guard для завищеної власної ціни;
- Serper price validation;
- release metrics: час, товари/хв, покриття, середні джерела, API та кеш;
- фірмове авторство у веб-інтерфейсі, CSV, деталізації та Excel.

## Файли для заміни з v0.9
1. `app.py`
2. `config.json`
3. `priceintel/runner.py`
4. `priceintel/report_xlsx.py`
5. `templates/index.html`
6. `templates/job.html`
7. `templates/preview.html`
8. `static/app.css`

Після deploy шукай у логах:
- `ENGINE v1.0`
- `ADAPTIVE SEARCH STOP`
- `PREFETCH`
- `CHECKPOINT SAVED`
- `RELEASE METRICS`

Після стабільного тесту v1.0 ядро не змінюємо до реального фідбеку з реклами.
