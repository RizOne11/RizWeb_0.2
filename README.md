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
