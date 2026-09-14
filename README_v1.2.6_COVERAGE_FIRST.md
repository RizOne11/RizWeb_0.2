# PUMA Platform v1.2.6 — Coverage-First Exact Market Orchestrator

Ціль: максимально повне відновлення українського ринку для **ідентичного** товару, але без марнування API на очевидно чужі кандидати.

## Що змінено

- **Coverage-first discovery**: один сильний broad MPN-запит + максимум один targeted MPN-запит на marketplace, якщо broad-пулу недостатньо.
- **Cheap Candidate Gate до scrape**: category/search/filter сторінки та очевидні конфлікти відсіюються до дорогого Firecrawl verify.
- **Product-page guard** для Rozetka / Prom / Epicentr / Hotline.
- **Canonical offer dedup**: локалізовані URL того самого Rozetka/Epicentr/Hotline товару більше не рахуються окремими конкурентами.
- **Firecrawl pacing + 429 backoff**: не молотимо API після rate-limit; у quality-first режимі краще почекати, ніж втратити покриття.
- **Ukraine commerce != тільки .ua**: українські магазини на .com/.net допускаються лише за сильними UA-commerce ознаками (UAH/₴/грн/Ukraine у домені тощо).
- **IN_STOCK only** лишається жорстким правилом основного ринку.

## Gold regression: Xiaomi P27QCB-RA

Мінімальна очікувана картина після повного (не скасованого) запуску:
- Rozetka: 1 унікальний exact offer (не 3 дублікати);
- Prom: щонайменше 2 direct exact offers, якщо обидва в наявності;
- Epicentr: exact offer 9998 UAH, якщо ще `Готов к отправке`;
- Hotline: exact offer 9999 UAH, якщо ще доступний;
- Other Ukraine stores: exact + in-stock only.

Не масштабувати на сотні товарів, доки gold regression не проходить стабільно.
