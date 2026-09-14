# PUMA Platform v1.2 — Deep Scan Exact Product

Quality-first build of доПУМАгатель.

## Core rules
- SKU Lock remains immutable.
- Every Tier-1 marketplace is checked: Rozetka, Epicentr, Prom, Allo, Foxtrot, Comfy, Kasta, Hotline.
- No adaptive early stop in Deep Scan.
- Up to 20 candidate URLs are retained per Tier-1 marketplace; Serper requests ask for up to 100 results.
- Up to 80 other-UA candidate URLs are retained.
- Only EXACT product matches enter market statistics by default.
- Explicit variant conflicts (memory/capacity/power/size/color when detectable from source data) override title similarity and are rejected.
- HIGH/POSSIBLE/CONFLICT candidates do not enter price statistics.
- Offer export includes Match status and Match reason for audit.
- Balanced market median is still one representative median per independent marketplace/other-UA host, while raw accepted offers remain available for competitor counts.

## Test recommendation
Deploy this build and run a small controlled YML batch first. Compare Tier-1 coverage and inspect the offer-level Match status/reason before scaling.
