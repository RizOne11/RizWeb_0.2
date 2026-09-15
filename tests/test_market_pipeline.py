from priceintel.market_models import MarketplaceCard, SellerOffer
from priceintel.market_pipeline import assemble_market, market_summary


def _card(marketplace, product_id, price, seller, *, status="PASS", availability="IN_STOCK"):
    card = MarketplaceCard(
        marketplace=marketplace,
        product_id=product_id,
        title="Xiaomi Redmi A27Q 2025",
        model="P27QCB-RA",
        mpn="P27QCB-RA",
        match_status=status,
    )
    card.add_offer(SellerOffer(
        marketplace=marketplace,
        seller_name=seller,
        price=price,
        currency="UAH",
        availability=availability,
    ))
    return card


def test_gold_p27qcb_ra_combines_four_marketplaces_without_losing_sellers():
    cards = [
        _card("Rozetka", "592071073", 8999, "WOWtech"),
        _card("Prom", "P27QCB-RA", 7978.10, "Extreme-Ukraine"),
        _card("Prom", "P27QCB-RA-2", 10999, "Winner"),
        _card("Epicentr", "epic2288", 9298, "Wondertech"),
        _card("Hotline", "116913", 9999, "Wondertech"),
    ]
    product = assemble_market(
        title="Xiaomi Redmi A27Q 2025",
        brand="Xiaomi",
        model="P27QCB-RA",
        mpn="P27QCB-RA",
        cards=cards,
    )

    summary = market_summary(product)
    assert summary["marketplaces"] == 4
    assert summary["eligible_offers"] == 5
    assert summary["offers_by_marketplace"] == {
        "Rozetka": 1, "Prom": 2, "Epicentr": 1, "Hotline": 1
    }
    assert summary["min_price"] == 7978.10
    assert summary["max_price"] == 10999
    assert len(product.marketplace_offers("Prom", eligible_only=True)) == 2


def test_unverified_card_cannot_contaminate_market():
    good = _card("Rozetka", "592071073", 8999, "WOWtech")
    stale = _card("Hotline", "stale", 1000, "Bad snapshot", status="UNVERIFIED")
    product = assemble_market(title="Xiaomi Redmi A27Q 2025", mpn="P27QCB-RA", cards=[good, stale])
    summary = market_summary(product)
    assert summary["marketplaces"] == 1
    assert summary["eligible_offers"] == 1
    assert summary["min_price"] == 8999


def test_unknown_availability_does_not_enter_price_market():
    unknown = _card("Epicentr", "epic", 1, "Unknown", availability="UNKNOWN")
    product = assemble_market(title="Xiaomi Redmi A27Q 2025", mpn="P27QCB-RA", cards=[unknown])
    summary = market_summary(product)
    assert summary["marketplaces"] == 0
    assert summary["eligible_offers"] == 0
    assert summary["min_price"] is None
