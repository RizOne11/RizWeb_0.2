# PUMA Platform v1.2.3 — Universal Marketplace Search Matrix

Цей патч перебудовує саме discovery/search layer перед Exact Product Gate.

## Що змінилось

- Одна й та сама Search Matrix використовується для **кожного** налаштованого Tier‑1 джерела: Rozetka, Prom, Epicentr, Allo, Foxtrot, Comfy, Kasta, Hotline.
- Для кожного маркетплейсу виконуються site-targeted запити `site:domain`, навіть якщо broad search уже знайшов один кандидат. Мета — зібрати кілька продавців/цін, а не зупинитися на першій картці.
- Broad Search Matrix окремо збирає інші українські `.ua` магазини з тих самих запитів.
- Порядок пошукових ключів: public model/MPN → supplier SKU + нормалізований SKU → model family → cleaned full title → raw full title → secondary model tokens.
- Supplier SKU залишається immutable, але не є самостійним доказом глобальної ідентичності товару.
- URL дедуплікуються без `utm_*`, `rsltid`, `srsltid`, `gclid` та іншого tracking noise; реальні product-selector параметри (наприклад Prom `p=`) не видаляються.
- Tier‑1 статус тепер відрізняє `EXACT_FOUND`, `CANDIDATES_REJECTED`, `CHECKED_NOT_FOUND`, `ERROR`.
- Exact Matcher нормалізує кольори, Hz/Гц та інші одиниці; явний конфлікт частоти/роздільної здатності має статус `CONFLICT`.
- Price consensus verification з v1.2.2 збережено: аномальна ціна не впливає на ринкову статистику без додаткової довіри до неї.
- Заголовок Excel `= моїй ціні` виправлений на `За моєю ціною`.
- Serper cache працює на конкретному query; повторний запуск того самого тесту має використовувати кеш до TTL.

## Еталонний regression case

Xiaomi Redmi A27Q 2025 P27QCB-RA, supplier SKU `002288`.

Очікування: точна модель має проходити як `EXACT` навіть якщо marketplace не містить supplier SKU; `P27QCB-RA` + відсутність variant conflict — сильний identity proof. Для Prom/Rozetka система повинна збирати кілька кандидатів, а не зупинятися після одного hit.

## Тести

`PYTHONPATH=. pytest -q`

У збірці: 8 тестів, включно з Search Matrix по всіх 8 Tier‑1, exact Xiaomi без supplier SKU та conflict на 120 Hz / 1920x1080.
