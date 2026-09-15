"""PUMA v1.3 canonical market pipeline.

Combines verified marketplace cards without collapsing seller-level offers.
This is the bridge between marketplace adapters and the existing analytics runner.
"""
from __future__ import annotations

from typing import Iterable

from priceintel.market_models import CanonicalProduct, MarketplaceCard

SUPPORTED_MARKETPLACES = {"Rozetka", "Prom", "Epicentr", "Hotline"}


def assemble_market(
    *,
    title: str,
    cards: Iterable[MarketplaceCard],
    brand: str | None = None,
    model: str | None = None,
    mpn: str | None = None,
    gtin: str | None = None,
) -> CanonicalProduct:
    """Build one canonical product from independently verified marketplace cards.

    Only PASS cards enter the canonical market.  UNVERIFIED/CONFLICT/REJECT cards
    remain outside price analytics rather than silently contaminating the market.
    Seller offers stay separate; eligibility is evaluated at offer level.
    """
    product = CanonicalProduct(title=title, brand=brand, model=model, mpn=mpn, gtin=gtin)
    seen_cards = set()

    for card in cards:
        if card.marketplace not in SUPPORTED_MARKETPLACES:
            continue
        if card.match_status != "PASS":
            continue
        key = (card.marketplace, card.product_id or "", card.url or "")
        if key in seen_cards:
            continue
        seen_cards.add(key)
        product.add_card(card)

    return product


def market_summary(product: CanonicalProduct) -> dict:
    eligible = product.seller_offers(eligible_only=True)
    by_marketplace = {}
    for card in product.cards:
        offers = [offer for offer in card.offers if offer.is_market_eligible]
        by_marketplace.setdefault(card.marketplace, 0)
        by_marketplace[card.marketplace] += len(offers)

    prices = [offer.price for offer in eligible if offer.price is not None]
    return {
        "marketplaces": len([name for name, count in by_marketplace.items() if count]),
        "eligible_offers": len(eligible),
        "offers_by_marketplace": by_marketplace,
        "min_price": min(prices) if prices else None,
        "max_price": max(prices) if prices else None,
    }
