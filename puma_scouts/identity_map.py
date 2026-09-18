from __future__ import annotations

import hashlib
import json
from typing import Iterable

from puma_scouts.models import IdentityConfidence, ProductMission, ValidatedOffer, Verdict
from puma_scouts.runtime_cache import identity_cache_seconds, runtime_cache


def mission_identity_key(mission: ProductMission) -> str:
    """Stable cache key for one supplier row + its public product identity."""
    data = mission.source_data or {}
    payload = {
        "article": str(mission.article or "").strip(),
        "name": str(data.get("name") or "").strip(),
        "brand": str(data.get("brand") or "").strip(),
        "model": str(data.get("model") or "").strip(),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).casefold()
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_identity_urls(mission: ProductMission, source: str, *, limit: int = 24) -> list[str]:
    cache = runtime_cache()
    ttl = identity_cache_seconds()
    if not cache or ttl <= 0:
        return []
    try:
        rows = cache.get_identities(mission_identity_key(mission), source, ttl, limit)
    except Exception:
        return []
    urls = []
    seen = set()
    for row in rows:
        url = str(row.get("url") or "").strip()
        if url and url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def remember_confirmed_identities(
    mission: ProductMission,
    source: str,
    validated: Iterable[ValidatedOffer],
) -> int:
    """Persist only strong confirmed PASS identities. Probable matches are never promoted."""
    cache = runtime_cache()
    if not cache:
        return 0
    key = mission_identity_key(mission)
    saved = 0
    for item in validated:
        if item.verdict != Verdict.PASS or item.identity_confidence != IdentityConfidence.CONFIRMED:
            continue
        offer = item.offer
        if offer.price is None:
            continue
        try:
            cache.put_identity(
                key,
                source,
                str(offer.url),
                str(offer.title or ""),
                str(offer.marketplace_product_id or ""),
                item.identity_confidence.value,
            )
            saved += 1
        except Exception:
            continue
    return saved
