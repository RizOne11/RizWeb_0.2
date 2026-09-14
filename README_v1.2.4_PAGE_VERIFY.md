# PUMA Platform v1.2.4 — Page Verification + Multi-Offer Expansion

Quality-first patch focused on the Xiaomi A27Q gold regression.

- stronger page extraction: JSON-LD → product meta → embedded application state → safe text fallback
- installment/monthly values are filtered from generic text fallback
- extraction source is logged
- universal candidate expansion for every Tier-1 marketplace when only one listing is found
- expansion excludes known listing IDs to surface alternate seller/listing URLs
- expansion is capped at 2 queries to protect Serper credits
- supplier SKU remains immutable and is never standalone external identity proof

Gold test: Xiaomi Redmi A27Q 2025 P27QCB-RA / supplier SKU 002288.
