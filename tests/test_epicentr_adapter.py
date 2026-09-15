from priceintel.adapters.epicentr import card_from_snapshot, product_id_from_url


def test_epicentr_gold_p27qcb_ra_verified_offer_is_eligible():
    url = (
        "https://epicentrk.ua/shop/mplc-monitor-redmi-a27q-2025-z-bagatofunkcional-nou-"
        "pidstavkou-p27qcb-ra-2560x1440-2k-ips-100-gc-27-cornij-epic2288-"
        "1f14234a-3bd7-6d9e-b7c9-856f19325e0a.html"
    )
    card = card_from_snapshot({
        "url": url,
        "title": "Монітор Redmi A27Q 2025 P27QCB-RA",
        "model": "P27QCB-RA",
        "mpn": "P27QCB-RA",
        "seller_name": "Wondertech",
        "price": "9 298 ₴",
        "currency": "UAH",
        "availability": "Готово до відправки",
        "match_status": "PASS",
    })

    assert card.marketplace == "Epicentr"
    assert card.model == "P27QCB-RA"
    assert card.mpn == "P27QCB-RA"
    assert len(card.offers) == 1
    assert card.offers[0].seller_name == "Wondertech"
    assert card.offers[0].price == 9298.0
    assert card.offers[0].availability == "IN_STOCK"
    assert card.offers[0].is_market_eligible
    assert {e.field for e in card.offers[0].evidence} >= {"price", "availability", "seller_name"}


def test_epicentr_unknown_availability_is_not_market_eligible():
    card = card_from_snapshot({
        "url": "https://epicentrk.ua/shop/example-product.html",
        "model": "P27QCB-RA",
        "price": 9298,
        "availability": "уточнюйте",
    })
    assert card.offers[0].availability == "UNKNOWN"
    assert not card.offers[0].is_market_eligible


def test_epicentr_product_id_comes_from_stable_slug():
    url = "https://epicentrk.ua/shop/mplc-monitor-redmi-p27qcb-ra-abc123.html"
    assert product_id_from_url(url) == "mplc-monitor-redmi-p27qcb-ra-abc123"
