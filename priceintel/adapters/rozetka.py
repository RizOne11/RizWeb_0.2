"""Rozetka -> PUMA v1.3 canonical market model adapter.

The adapter is deliberately transport-agnostic: discovery/fetch code supplies a
normalized snapshot, and this module turns it into evidence-backed domain data.
This keeps stale search snippets separate from verified product-page facts.
"""
from __future__ import annotations

import re
from typing import Any, Mapping, Optional

from priceintel.market_models import Evidence, MarketplaceCard, SellerOffer

_ROZETKA_PRODUCT_ID = re.compile(r"/p(\d+)(?:/|$)")


def product_id_from_url(url: str) -> Optional[str]:
    match = _ROZETKA_PRODUCT_ID.search(url or "")
    return match.group(1) if match else None


def canonical_product_url(url: str) -> str:
    product_id = product_id_from_url(url)
    if not product_id:
        return url
    return f"https://hard.rozetka.com.ua/ua/{product_id}/p{product_id}/"


def card_from_snapshot(snapshot: Mapping[str, Any]) -> MarketplaceCard:
    """Build one Rozetka marketplace card from a verified page/API snapshot.

    Required identity is intentionally strict: a missing product id is a parser
    error, not NOT_FOUND. Price/stock are seller-offer facts and remain separate
    from card identity.
    """
    raw_url = str(snapshot.get("url") or "")
    product_id = str(snapshot.get("product_id") or product_id_from_url(raw_url) or "")
    if not product_id:
        raise ValueError("Rozetka snapshot has no canonical product id")

    url = canonical_product_url(raw_url) if raw_url else f"https://hard.rozetka.com.ua/ua/{product_id}/p{product_id}/"
    title = str(snapshot.get("title") or "").strip()
    model = _clean(snapshot.get("model"))
    mpn = _clean(snapshot.get("mpn")) or model

    evidence = [
        Evidence(url, "product_page", "product_id", product_id),
    ]
    if title:
        evidence.append(Evidence(url, "product_page", "title", title))
    if model:
        evidence.append(Evidence(url, "product_page", "model", model))

    card = MarketplaceCard(
        marketplace="Rozetka",
        product_id=product_id,
        url=url,
        title=title,
        model=model,
        mpn=mpn,
        gtin=_clean(snapshot.get("gtin")),
        match_status=str(snapshot.get("match_status") or "UNVERIFIED"),
        evidence=evidence,
    )

    price = _price(snapshot.get("price"))
    availability = _availability(snapshot.get("availability"))
    seller_name = _clean(snapshot.get("seller_name"))
    seller_id = _clean(snapshot.get("seller_id"))

    if price is not None or seller_name or availability != "UNKNOWN":
        offer_evidence = []
        if price is not None:
            offer_evidence.append(Evidence(url, "product_page", "price", price))
        if availability != "UNKNOWN":
            offer_evidence.append(Evidence(url, "product_page", "availability", availability))
        if seller_name:
            offer_evidence.append(Evidence(url, "product_page", "seller_name", seller_name))
        card.add_offer(SellerOffer(
            marketplace="Rozetka",
            seller_id=seller_id,
            seller_name=seller_name,
            price=price,
            currency=str(snapshot.get("currency") or "UAH").upper(),
            availability=availability,
            url=url,
            evidence=offer_evidence,
        ))
    return card


def _clean(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    return text or None


def _price(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace("\u00a0", "").replace(" ", "").replace("₴", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _availability(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"in_stock", "є в наявності", "есть в наличии", "available"}:
        return "IN_STOCK"
    if text in {"out_of_stock", "немає в наявності", "нет в наличии", "unavailable"}:
        return "OUT_OF_STOCK"
    return "UNKNOWN"
