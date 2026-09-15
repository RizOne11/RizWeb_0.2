"""Canonical market model for PUMA v1.3.

Separates product identity, marketplace cards, seller offers and evidence.
Discovery may find a card; only verified seller offers are eligible for price analytics.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class Evidence:
    source_url: str
    source_kind: str  # api | product_page | catalog | search | structured_data
    field: str
    value: Any
    observed_at: Optional[str] = None
    confidence: float = 1.0
    note: str = ""


@dataclass
class SellerOffer:
    marketplace: str
    seller_id: Optional[str] = None
    seller_name: Optional[str] = None
    price: Optional[float] = None
    currency: str = "UAH"
    availability: str = "UNKNOWN"
    url: str = ""
    evidence: List[Evidence] = field(default_factory=list)

    @property
    def is_market_eligible(self) -> bool:
        return (
            self.price is not None
            and self.price > 0
            and self.currency == "UAH"
            and self.availability == "IN_STOCK"
        )


@dataclass
class MarketplaceCard:
    marketplace: str
    product_id: Optional[str] = None
    url: str = ""
    title: str = ""
    model: Optional[str] = None
    mpn: Optional[str] = None
    gtin: Optional[str] = None
    match_status: str = "UNVERIFIED"  # PASS | CONFLICT | REJECT | UNVERIFIED
    offers: List[SellerOffer] = field(default_factory=list)
    evidence: List[Evidence] = field(default_factory=list)

    def add_offer(self, offer: SellerOffer) -> None:
        if offer.marketplace != self.marketplace:
            raise ValueError("offer marketplace must match card marketplace")
        self.offers.append(offer)


@dataclass
class CanonicalProduct:
    title: str
    brand: Optional[str] = None
    model: Optional[str] = None
    mpn: Optional[str] = None
    gtin: Optional[str] = None
    cards: List[MarketplaceCard] = field(default_factory=list)
    evidence: List[Evidence] = field(default_factory=list)

    def add_card(self, card: MarketplaceCard) -> None:
        self.cards.append(card)

    def seller_offers(self, *, eligible_only: bool = False) -> List[SellerOffer]:
        offers = [offer for card in self.cards for offer in card.offers]
        if eligible_only:
            offers = [offer for offer in offers if offer.is_market_eligible]
        return offers

    def marketplace_offers(self, marketplace: str, *, eligible_only: bool = False) -> List[SellerOffer]:
        return [
            offer
            for offer in self.seller_offers(eligible_only=eligible_only)
            if offer.marketplace == marketplace
        ]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
