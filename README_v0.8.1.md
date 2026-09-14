# PriceIntel v0.8.1

Hotfix after the 30-product v0.8 validation run.

- Adds `VERDICT GUARD`: with at least 2 balanced market sources, own price >=10% above market median is forced to `🔴 НЕ РЕКЛАМУВАТИ`.
- `Запас, %` is now calculated relative to market median, making over/under-market percentage intuitive.
- Raises `other_ua_shops_max_hits` from 8 to 12 to reduce false `⚪ НЕ ЗНАЙДЕНО` caused by noisy early organic results.
- Keeps the Serper cost counter and balanced-source model from v0.8.0.
