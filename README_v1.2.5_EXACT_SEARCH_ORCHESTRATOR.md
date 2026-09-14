# PUMA Platform v1.2.5 — Exact Search Orchestrator

Ціль релізу: максимально повний пошук **ідентичного товару**, який **є в наявності в Україні** на момент аналізу.

## Що змінилось

- Firecrawl став первинним discovery-каналом для marketplace-targeted пошуку. Для доменів використовується native `includeDomains`, а не `site:` у Serper.
- Serper більше не є single point of failure. `site:` прибирається до виклику Serper, тому Free-помилка `Query pattern not allowed for free accounts` не ламає Tier-1 перевірку.
- Exa доданий як незалежний recovery provider (`EXA_API_KEY` опціональний).
- Firecrawl може працювати у keyless starter mode. Якщо додати `FIRECRAWL_API_KEY`, використовуються вищі ліміти.
- Firecrawl structured page verification використовується як fallback для 403/JS/anti-bot, відсутньої ціни або невідомої наявності.
- Географія ринку: тільки Україна. Tier-1 домени + інші `.ua` магазини.
- Основний звіт: **тільки IN_STOCK**. OUT_OF_STOCK та UNKNOWN після verification не впливають на статистику і не додаються в офери.
- Додано `Провайдер пошуку` та `Наявність` в audit offers.
- Технічні характеристики типу `DCI-P3`, `HDR10`, `2K`, `100Hz` більше не повинні ставати model/MPN токенами.
- Метрики API розділено на Serper / Firecrawl / Exa.

## Exact Search chain

1. Product Fingerprint з YML.
2. Broad Ukraine discovery.
3. Tier-1 targeted recovery для Rozetka / Prom / Epicentr / Allo / Foxtrot / Comfy / Kasta / Hotline.
4. Merge + canonical URL dedup.
5. Exact Product Gate. Supplier SKU — лише corroboration, не глобальний доказ.
6. Page verification: direct HTML/JSON-LD → Firecrawl fallback.
7. Availability Gate: тільки IN_STOCK.
8. Price Gate: основна повна ціна товару, без розстрочки/місячних платежів.
9. Multi-offer collection: різні canonical listing IDs залишаються окремими конкурентами.
10. Balanced market: один marketplace/host = один незалежний market source для медіани.

## Environment

- `SERPER_API_KEY` — опціональний recovery channel.
- `FIRECRAWL_API_KEY` — опціональний; без нього дозволений keyless starter mode.
- `EXA_API_KEY` — опціональний recovery channel.

## Gold regression

Xiaomi Redmi A27Q 2025 / `P27QCB-RA`:
- Rozetka exact card must be discovered and verified.
- Prom must collect multiple exact seller/listing offers when available.
- A27Q Type-C 2026 / 120 Hz must be rejected as CONFLICT.
- Out-of-stock listings must not enter the report/statistics.

Marshall Major IV is the false-positive control: unrelated pages that merely contain supplier SKU `11676` must never become EXACT.
