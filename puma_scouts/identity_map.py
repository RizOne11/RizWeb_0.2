from __future__ import annotations

import hashlib
import json
import os
from typing import Iterable

from puma_scouts.models import IdentityConfidence, ProductMission, ValidatedOffer, Verdict
from puma_scouts.runtime_cache import identity_cache_seconds, runtime_cache


def _stable_text(value) -> str:
    return " ".join(str(value or "").split()).strip().casefold()


def mission_identity_key(mission: ProductMission) -> str:
    """Stable SKU-level key.

    When supplier is known, supplier+article is the durable identity anchor.
    Without supplier, fall back to the public identity fingerprint so unrelated
    catalogs that reuse the same internal article cannot collide.
    """
    data = mission.source_data or {}
    supplier = _stable_text(data.get("supplier"))
    article = _stable_text(mission.article)
    if supplier and article:
        payload = {"supplier": supplier, "article": article}
    else:
        payload = {
            "article": article,
            "name": _stable_text(data.get("name")),
            "brand": _stable_text(data.get("brand")),
            "model": _stable_text(data.get("model")),
        }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def mission_identity_version(mission: ProductMission) -> str:
    """Version/checksum of material public identity fields for a stable SKU."""
    data = mission.source_data or {}
    payload = {
        "name": _stable_text(data.get("name")),
        "brand": _stable_text(data.get("brand")),
        "model": _stable_text(data.get("model")),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def load_identity_urls(mission: ProductMission, source: str, *, limit: int = 24) -> list[str]:
    cache = runtime_cache()
    ttl = identity_cache_seconds()
    if not cache or ttl <= 0:
        return []
    try:
        rows = cache.get_identities(
            mission_identity_key(mission),
            source,
            ttl,
            limit,
            identity_version=mission_identity_version(mission),
        )
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


def _save_probable_enabled() -> bool:
    return os.getenv("PUMA_IDENTITY_SAVE_PROBABLE", "0").strip().casefold() in {
        "1", "true", "yes", "on"
    }


def remember_confirmed_identities(
    mission: ProductMission,
    source: str,
    validated: Iterable[ValidatedOffer],
) -> int:
    """Persist reusable validated URLs.

    CONFIRMED PASS identities are always persisted. PROBABLE PASS identities can
    be persisted experimentally with PUMA_IDENTITY_SAVE_PROBABLE=1; they are
    never promoted to CONFIRMED and still pass through the normal validator on
    every direct refresh.
    """
    cache = runtime_cache()
    if not cache:
        return 0
    key = mission_identity_key(mission)
    version = mission_identity_version(mission)
    allow_probable = _save_probable_enabled()
    saved = 0
    for item in validated:
        if item.verdict != Verdict.PASS:
            continue
        if item.identity_confidence == IdentityConfidence.CONFIRMED:
            pass
        elif allow_probable and item.identity_confidence == IdentityConfidence.PROBABLE:
            pass
        else:
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
                identity_version=version,
            )
            saved += 1
        except Exception:
            continue
    return saved
