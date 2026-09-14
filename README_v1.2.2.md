# PUMA Platform v1.2.2 — Deep Scan Exact Verification Gate

Hotfix/quality release focused on false-positive control without increasing Serper usage.

Changes:
- Supplier SKU remains immutable (SKU Lock), but is no longer treated as a globally unique external identifier by itself.
- Numeric supplier articles cannot force an EXACT match on unrelated pages.
- Stronger brand/title/model corroboration before EXACT acceptance.
- Ukrainian/Russian/English colour aliases normalized (e.g. Black = чорний = черный).
- Second price verification gate excludes obvious extraction/installment/outlier prices from market statistics while keeping them in the audit report.
- No extra Serper requests are made by the second price verification gate.
- Excel header `= моїй ціні` renamed to `За моєю ціною` so Excel no longer turns it into `#NAME?`.
