from priceintel.adapters.prom import card_from_snapshots


def test_gold_p27qcb_ra_preserves_two_prom_sellers():
    card = card_from_snapshots(
        [
            {
                "url": "https://prom.ua/ua/m5380328037794579431-monitor-xiaomi-redmi.html",
                "title": "Монітор Xiaomi Redmi A27Q 2025 P27QCB-RA",
                "model": "P27QCB-RA",
                "mpn": "P27QCB-RA",
                "seller_id": "extreme-ukraine",
                "seller_name": "Extreme-Ukraine",
                "price": "7 978,10 ₴",
                "currency": "UAH",
                "availability": "Готово до відправки",
            },
            {
                "url": "https://prom.ua/ua/example-winner-p27qcb-ra.html",
                "title": "Монітор Xiaomi Redmi A27Q 2025 P27QCB-RA",
                "model": "P27QCB-RA",
                "mpn": "P27QCB-RA",
                "seller_id": "winner",
                "seller_name": "Winner",
                "price": "10 999 ₴",
                "currency": "UAH",
                "availability": "В наявності",
            },
        ],
        product_id="P27QCB-RA",
        model="P27QCB-RA",
        mpn="P27QCB-RA",
        match_status="PASS",
    )

    assert card.marketplace == "Prom"
    assert card.product_id == "P27QCB-RA"
    assert card.match_status == "PASS"
    assert len(card.offers) == 2
    assert {offer.seller_name for offer in card.offers} == {"Extreme-Ukraine", "Winner"}
    assert {offer.price for offer in card.offers} == {7978.10, 10999.0}
    assert all(offer.availability == "IN_STOCK" for offer in card.offers)
    assert all(offer.is_market_eligible for offer in card.offers)


def test_prom_duplicate_snapshot_does_not_duplicate_offer():
    snapshot = {
        "url": "https://prom.ua/ua/m5380328037794579431-monitor-xiaomi-redmi.html",
        "model": "P27QCB-RA",
        "seller_id": "extreme-ukraine",
        "seller_name": "Extreme-Ukraine",
        "price": "7 978,10 ₴",
        "availability": "Готово до відправки",
    }
    card = card_from_snapshots([snapshot, snapshot], product_id="P27QCB-RA", match_status="PASS")
    assert len(card.offers) == 1


def test_prom_unknown_availability_is_not_market_eligible():
    card = card_from_snapshots(
        [{
            "url": "https://prom.ua/ua/example.html",
            "model": "P27QCB-RA",
            "seller_name": "Unknown seller",
            "price": "8 500 ₴",
            "availability": "",
        }],
        product_id="P27QCB-RA",
        match_status="PASS",
    )
    assert card.offers[0].availability == "UNKNOWN"
    assert card.offers[0].is_market_eligible is False
