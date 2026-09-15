"""Epicentr -> PUMA v1.3 canonical market model adapter.

The adapter consumes normalized product-page snapshots and keeps seller, price
and availability as evidence-backed offer facts. Network/discovery code stays
outside this module so stale search snippets cannot become market facts.
"""
from __future__ import annotations

import re
from typing import Any, Mapping, Optional

from priceintel.market_models import Evidence, MarketplaceCard, SellerOffer


def product_id_from_url(url: str) -> Optional[str]:
    text = str(url or "")
    # Epicentr marketplace URLs commonly end with a stable slug before .html.
    match = re.search(r"/([^/?#]+)\.html(?:[?#]|$)", text, re.I)
    return match.group(1) if match else None


def card_from_snapshot(snapshot: Mapping[str, Any]) -> MarketplaceCard:
    url = str(snapshot.get("url") or "")
    product_id = _clean(snapshot.get("product_id")) or product_id_from_url(url)
    if not product_id:
        raise ValueError("Epicentr snapshot has no product identity")

    title = str(snapshot.get("title") or "").strip()
    model = _clean(snapshot.get("model"))
    mpn = _clean(snapshot.get("mpn")) or model
    match_status = str(snapshot.get("match_status") or "UNVERIFIED")

    card = MarketplaceCard(
        marketplace="Epicentr",
        product_id=product_id,
        url=url,
        title=title,
        model=model,
        mpn=mpn,
        gtin=_clean(snapshot.get("gtin")),
        match_status=match_status,
        evidence=[
            Evidence(url, "product_page", "product_id", product_id),
            Evidence(url, "product_page", "title", title),
        ],
    )

    price = _price(snapshot.get("price"))
    availability = _availability(snapshot.get("availability"))
    seller_id = _clean(snapshot.get("seller_id"))
    seller_name = _clean(snapshot.get("seller_name"))
    currency = str(snapshot.get("currency") or "UAH").upper()

    evidence = []
    if price is not None:
        evidence.append(Evidence(url, "product_page", "price", price))
    if availability != "UNKNOWN":
        evidence.append(Evidence(url, "product_page", "availability", availability))
    if seller_name:
        evidence.append(Evidence(url, "product_page", "seller_name", seller_name))

    card.add_offer(SellerOffer(
        marketplace="Epicentr",
        seller_id=seller_id,
        seller_name=seller_name,
        price=price,
        currency=currency,
        availability=availability,
        url=url,
        evidence=evidence,
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
