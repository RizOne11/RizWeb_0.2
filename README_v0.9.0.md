# PriceIntel v0.9.0 — Performance & Recovery

База: v0.8.3.

Що змінено:
- POST/Redirect/GET: F5 на сторінці job більше не повторює форму і не запускає другий аналіз.
- Захист від дубля: однаковий CSV + постачальник + маркетплейси + limit не запускаються паралельно.
- Checkpoint після кожного повністю завершеного товару.
- Resume для canceled/error/interrupted job через кнопку «Продовжити з checkpoint».
- Паралельний prefetch сторінок конкурентів (`page_fetch_workers=6`).
- HTTP timeout скорочено до 12 с.
- SQLite cache захищено lock для багатопоточності.
- Логи: `ENGINE v0.9.0`, `PREFETCH`, `CHECKPOINT SAVED`, `RESUME CHECKPOINT`.

Замінити у GitHub:
1. `app.py`
2. `priceintel/runner.py`
3. `priceintel/cache.py`
4. `templates/job.html`
5. `config.json`

Після deploy перевірити маркери:
- `ENGINE v0.9.0`
- `PREFETCH:`
- `CHECKPOINT SAVED:`
- після першого POST URL має бути `/jobs/<job_id>`, а не `/analyze`.

Тест:
- запустити 30 товарів;
- на 5–10 товарі натиснути F5: аналіз НЕ має стартувати з нуля;
- за бажанням натиснути «Зупинити аналіз», після зупинки — «Продовжити з checkpoint».
