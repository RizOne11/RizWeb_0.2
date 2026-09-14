# PUMA Platform v1.2.5.1 — Provider Hotfix

Hotfix after the Xiaomi A27Q gold test on Render.

## What failed
- Firecrawl keyless calls from Render shared IP were rejected with HTTP 403 (API key required).
- Serper Free rejected quoted query patterns and the old loop wasted dozens of requests.
- Exa remains optional and requires `EXA_API_KEY` inside the Render app; connecting the ChatGPT plugin does not inject that key into Render.

## Fixes
- Firecrawl keyless is OFF by default. Add a free `FIRECRAWL_API_KEY` in Render Environment.
- Firecrawl has an auth circuit breaker: one 401/403 disables it for the remainder of the run instead of spamming requests.
- Serper automatically converts exact queries to free-safe plain queries (removes quotes, `site:`, negative exclusions).
- Serper has a circuit breaker if the account still rejects the normalized query pattern.
- Ukraine-only and IN_STOCK-only rules remain unchanged.

## Xiaomi A27Q gold regression URLs (reference only; not hardcoded into runtime search)
- Rozetka: `https://hard.rozetka.com.ua/ua/592071073/p592071073/`
- Hotline: `https://hotline.ua/ua/computer-monitory/xiaomi-a27q-2025-p27qcb-ra/`
- Epicentr: `https://epicentrk.ua/ua/shop/mplc-monitor-redmi-a27q-2025-z-bagatofunkcional-nou-pidstavkou-p27qcb-ra-2560x1440-2k-ips-100-gc-27-cornij-epic2288-1f14234a-3bd7-6d9e-b7c9-856f19325e0a.html`
- Prom seller/listing examples remain gold coverage checks.

Expected live evidence on 2026-09-14: Hotline had one in-stock Wondertech offer at 9,999 UAH; Epicentr had an in-stock Wondertech marketplace offer at 9,998 UAH.
