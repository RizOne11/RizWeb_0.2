# PriceIntel v0.8.2 hotfix

- Centralized final verdict resolution.
- Hard red verdict when own price is >= configured threshold above a market median confirmed by 2+ independent sources.
- Adds explicit `FINAL VERDICT: ... | reason=...` log line.
- Adds `ENGINE v0.8.2` marker at job start so deployment version is visible immediately.
- Adds `Причина вердикту` to CSV/XLSX data rows.
