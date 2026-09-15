from priceintel.market_models import CanonicalProduct, Evidence, MarketplaceCard, SellerOffer


def test_multiple_prom_sellers_are_preserved():
    product = CanonicalProduct(title="Xiaomi Redmi Display A27Q 2025", brand="Xiaomi", model="P27QCB-RA", mpn="P27QCB-RA")
    card = MarketplaceCard(
        marketplace="Prom",
        product_id="gold-prom-card",
        title="Xiaomi Redmi Display A27Q 2025 P27QCB-RA",
        model="P27QCB-RA",
        mpn="P27QCB-RA",
        match_status="PASS",
    )
    card.add_offer(SellerOffer(marketplace="Prom", seller_id="seller-a", price=7978.10, availability="IN_STOCK"))
    card.add_offer(SellerOffer(marketplace="Prom", seller_id="seller-b", price=10999.00, availability="IN_STOCK"))
    product.add_card(card)

    offers = product.marketplace_offers("Prom", eligible_only=True)
    assert len(offers) == 2
    assert sorted(x.price for x in offers) == [7978.10, 10999.00]


def test_discovery_evidence_does_not_make_unknown_offer_eligible():
    offer = SellerOffer(
        marketplace="Rozetka",
        seller_name="example",
        price=8999.0,
        availability="UNKNOWN",
        evidence=[Evidence(source_url="https://example.invalid/catalog", source_kind="catalog", field="price", value=8999.0)],
    )
    assert offer.is_market_eligible is False


def test_verified_in_stock_uah_offer_is_eligible():
    offer = SellerOffer(marketplace="Rozetka", price=8999.0, availability="IN_STOCK", currency="UAH")
    assert offer.is_market_eligible is True
