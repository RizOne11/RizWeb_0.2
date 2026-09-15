"""Prom -> PUMA v1.3 canonical market model adapter.

Prom can expose multiple independent seller offers for the same exact product.
This adapter preserves every seller offer instead of collapsing the marketplace
to one representative price. Discovery snapshots remain transport-agnostic.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Optional

from priceintel.market_models import Evidence, MarketplaceCard, SellerOffer

_PROM_PRODUCT_ID = re.compile(r"(?:^|[-/])(?:p|m)?(\d{6,})(?:[-/.]|$)", re.I)


def product_id_from_url(url: str) -> Optional[str]:
    text = str(url or "")
    # Common Prom product URLs include /p123456789-name.html or m<id> links.
    match = re.search(r"/(?:p|m)(\d{6,})(?:[-/.]|$)", text, re.I)
    if match:
        return match.group(1)
    match = _PROM_PRODUCT_ID.search(text)
    return match.group(1) if match else None


def card_from_snapshots(
    snapshots: Iterable[Mapping[str, Any]],
    *,
    product_id: Optional[str] = None,
    title: str = "",
    model: Optional[str] = None,
    mpn: Optional[str] = None,
    gtin: Optional[str] = None,
    match_status: str = "UNVERIFIED",
) -> MarketplaceCard:
    """Build one Prom card while retaining all distinct seller offers."""
    rows = list(snapshots)
    if not rows:
        raise ValueError("Prom adapter requires at least one seller snapshot")

    first = rows[0]
    card_id = _clean(product_id) or _clean(first.get("product_id")) or product_id_from_url(str(first.get("url") or ""))
    # Prom seller pages may have distinct listing IDs. For a canonical exact-product
    # card, the caller can provide a stable product/model key; otherwise first listing
    # ID is retained only as the discovery card identity.
    card_id = card_id or _clean(mpn) or _clean(model) or _clean(first.get("mpn")) or _clean(first.get("model"))
    if not card_id:
        raise ValueError("Prom snapshots have no product/listing identity")

    card_url = str(first.get("url") or "")
    card_title = title.strip() or str(first.get("title") or "").strip()
    card_model = _clean(model) or _clean(first.get("model"))
    card_mpn = _clean(mpn) or _clean(first.get("mpn")) or card_model

    card = MarketplaceCard(
        marketplace="Prom",
        product_id=card_id,
        url=card_url,
        title=card_title,
        model=card_model,
        mpn=card_mpn,
        gtin=_clean(gtin) or _clean(first.get("gtin")),
        match_status=match_status or str(first.get("match_status") or "UNVERIFIED"),
        evidence=[Evidence(card_url, "product_page", "product_id", card_id)],
    )

    seen = set()
    for row in rows:
        offer = _offer_from_snapshot(row)
        key = (
            offer.seller_id or "",
            (offer.seller_name or "").strip().casefold(),
            offer.url,
            offer.price,
        )
        if key in seen:
            continue
        seen.add(key)
        card.add_offer(offer)
    return card


def _offer_from_snapshot(snapshot: Mapping[str, Any]) -> SellerOffer:
    url = str(snapshot.get("url") or "")
    seller_id = _clean(snapshot.get("seller_id") or snapshot.get("company_id"))
    seller_name = _clean(snapshot.get("seller_name") or snapshot.get("company_name"))
    price = _price(snapshot.get("price"))
    availability = _availability(snapshot.get("availability"))
    currency = str(snapshot.get("currency") or "UAH").upper()

    evidence = []
    if price is not None:
        evidence.append(Evidence(url, "product_page", "price", price))
    if availability != "UNKNOWN":
        evidence.append(Evidence(url, "product_page", "availability", availability))
    if seller_name:
        evidence.append(Evidence(url, "product_page", "seller_name", seller_name))
    if seller_id:
        evidence.append(Evidence(url, "product_page", "seller_id", seller_id))

    return SellerOffer(
        marketplace="Prom",
        seller_id=seller_id,
        seller_name=seller_name,
        price=price,
        currency=currency,
        availability=availability,
        url=url,
        evidence=evidence,
    )


def _clean(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    return text or None


def _price(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace("\u00a0", "").replace(" ", "").replace("₴", "").replace(",", ".")
    text = re.sub(r"[^0-9.]", "", text)
    try:
        return float(text)
    except ValueError:
        return None


def _availability(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"in_stock", "в наявності", "є в наявності", "готово до відправки", "готов к отправке", "available"}:
        return "IN_STOCK"
    if text in {"out_of_stock", "немає в наявності", "нет в наличии", "unavailable"}:
        return "OUT_OF_STOCK"
    return "UNKNOWN"
