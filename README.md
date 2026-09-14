# PriceIntel Web v0.3 — Serper

Ця версія замінює HTML-парсинг DuckDuckGo/Bing на Serper Google Search API.

## Що змінилось
- 1 Serper search-запит на 1 товар.
- Один запит шукає одразу по Rozetka, Prom, Epicentr, Allo, Foxtrot і Comfy.
- Результати розкладаються по маркетплейсах локально.
- Далі програма відкриває знайдені сторінки, витягує ціну та застосовує Match Score.
- Детальні логи залишені для тестування.

## Налаштування Render
1. Render -> твій Web Service -> Environment.
2. Add Environment Variable.
3. Name: `SERPER_API_KEY`
4. Value: твій ключ із Serper.
5. Save Changes.
6. Render зробить redeploy (або Manual Deploy -> Deploy latest commit).

**Не додавай API key у GitHub і не надсилай його в чат.**

## Тест
Почни з 5 товарів. У Render Logs має бути:
- `Serper API key configured: True`
- `SERPER QUERY: ...`
- `SERPER HTTP 200`
- `SERPER ORGANIC: ... result(s)`
- `SERPER rozetka.com.ua: ... hit(s)` тощо.

Якщо пошукові результати є, але пропозицій 0 — наступний етап проблеми вже у fetch/extract/match, і лог покаже конкретну причину.

## Ліміти
Безкоштовні 2,500 Serper queries ≈ до 2,500 товарів у цій архітектурі (по одному search-запиту на товар), не рахуючи повторних запусків.


## v0.4.1
- Added supplier field to upload form.
- Category + supplier are included in browser preview, main CSV and competitor offers CSV.

## v0.4.2
- Added `Запас до рынка, грн` = market median minus supplier/own price.
- Added `Запас до рынка, %` = reserve divided by own price.
- Both fields are included in the browser report and main CSV.
- Positive value means the market median is above your price; negative means your price is above the median.

## v0.4.3 — Price Validation
- Serper fallback prices are checked against the supplier/own price.
- Default anomaly threshold: >3x difference (`serper_price_ratio_limit` in config.json).
- Suspicious Serper prices remain visible in the competitor-offers CSV.
- Suspicious prices are excluded from MIN / MEDIAN / AVG / MAX / Price Score / verdict calculations.
- If a product has only suspicious prices, verdict becomes `⚠️ ЦІНА НЕ ПІДТВЕРДЖЕНА`.
- Main report includes `Підозрілих цін`.
- Offers report includes `Статус цены` and `Причина проверки`.

## v0.5.0 — Market report
- Verdict moved to the first column.
- AVG renamed to `Середня`.
- Added separate columns with all valid prices found on Rozetka, Prom, Epicentr, Allo, Foxtrot and Comfy.
- Added `= моїй ціні`: count of valid competitor offers exactly equal to the supplier/own price.
- Main report is sorted: РЕКЛАМУВАТИ → ТЕСТУВАТИ → ЦІНА НЕ ПІДТВЕРДЖЕНА → НЕ РЕКЛАМУВАТИ → НЕ ЗНАЙДЕНО.
- Added styled Excel export with the same column order as the browser report.
- CSV and detailed competitor offers export remain available.
