from __future__ import annotations

import hashlib
import json
import os
from typing import Iterable

from puma_scouts.models import IdentityConfidence, ProductMission, ValidatedOffer, Verdict
from puma_scouts.lingua import fold_homoglyphs
from puma_scouts.runtime_cache import identity_cache_seconds, runtime_cache


def _stable_text(value) -> str:
    return " ".join(fold_homoglyphs(value).split()).strip()


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


def _discovery_state_key(mission: ProductMission) -> str:
    return (
        "puma:discovery-sources:v1:"
        + mission_identity_key(mission)
        + ":"
        + mission_identity_version(mission)
    )


def remember_discovery_sources(mission: ProductMission, sources: Iterable[str]) -> bool:
    """Remember only marketplaces that produced accepted offers in full Discovery.

    Empty source lists are persisted too, so Fast Refresh can distinguish a
    known Discovery miss from missing/legacy state and avoid wasteful repair.
    """
    cache = runtime_cache()
    if not cache:
        return False
    clean = sorted({str(source or "").strip() for source in sources if str(source or "").strip()})
    try:
        cache.put_search(
            _discovery_state_key(mission),
            json.dumps({"sources": clean}, ensure_ascii=False, separators=(",", ":")),
        )
        return True
    except Exception:
        return False


def load_discovery_sources(mission: ProductMission) -> list[str] | None:
    """Return known Discovery sources, [] for a known miss, None for no state."""
    cache = runtime_cache()
    ttl = identity_cache_seconds()
    if not cache or ttl <= 0:
        return None
    try:
        raw = cache.get_search(_discovery_state_key(mission), ttl)
    except Exception:
        return None
    if raw is None:
        return None
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    values = payload.get("sources") if isinstance(payload, dict) else None
    if not isinstance(values, list):
        return None
    return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def _candidate_hint_key(mission: ProductMission, source: str) -> str:
    return (
        "puma:candidate-hints:v1:"
        + mission_identity_key(mission)
        + ":"
        + mission_identity_version(mission)
        + ":"
        + str(source or "").strip().casefold()
    )


def remember_candidate_hints(
    mission: ProductMission,
    source: str,
    validated: Iterable[ValidatedOffer],
    *,
    limit: int = 6,
) -> int:
    """Persist untrusted PASS/PROBABLE URLs for cheap revalidation.

    Candidate hints are deliberately separate from the Identity Map. They are
    never trusted as identity and must pass the full validator again on refresh.
    """
    cache = runtime_cache()
    if not cache:
        return 0
    candidates = []
    for item in validated:
        if (
            item.verdict == Verdict.PASS
            and item.identity_confidence == IdentityConfidence.PROBABLE
            and item.offer.price is not None
        ):
            url = str(item.offer.url or "").strip()
            if url:
                candidates.append((float(item.score or 0), url))
    urls = []
    seen = set()
    for _, url in sorted(candidates, key=lambda pair: pair[0], reverse=True):
        if url in seen:
            continue
        seen.add(url)
        urls.append(url)
        if len(urls) >= max(1, int(limit)):
            break
    try:
        cache.put_search(
            _candidate_hint_key(mission, source),
            json.dumps({"urls": urls}, ensure_ascii=False, separators=(",", ":")),
        )
        return len(urls)
    except Exception:
        return 0


def load_candidate_hint_urls(
    mission: ProductMission,
    source: str,
    *,
    limit: int = 6,
) -> list[str]:
    cache = runtime_cache()
    ttl = identity_cache_seconds()
    if not cache or ttl <= 0:
        return []
    try:
        raw = cache.get_search(_candidate_hint_key(mission, source), ttl)
    except Exception:
        return []
    if raw is None:
        return []
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    values = payload.get("urls") if isinstance(payload, dict) else None
    if not isinstance(values, list):
        return []
    urls = []
    seen = set()
    for value in values:
        url = str(value or "").strip()
        if url and url not in seen:
            seen.add(url)
            urls.append(url)
        if len(urls) >= max(1, int(limit)):
            break
    return urls


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


def _safe_probable_identity(item: ValidatedOffer) -> bool:
    """Allow only PROBABLE rows that already carry a strong identity anchor.

    Plain title/token similarity is intentionally not enough. This prevents the
    0.79 similarity-only bucket from becoming a durable identity while allowing
    category-profile downgrades of otherwise strongly identified products.
    """
    if item.conflicts:
        return False
    strong_prefixes = (
        "strong identifier match:",
        "explicit model match:",
        "exact model code match:",
    )
    return any(
        str(evidence or "").startswith(strong_prefixes)
        for evidence in (item.positive_evidence or [])
    )


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
        elif (
            allow_probable
            and item.identity_confidence == IdentityConfidence.PROBABLE
            and _safe_probable_identity(item)
        ):
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
