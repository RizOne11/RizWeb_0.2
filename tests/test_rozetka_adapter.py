from priceintel.adapters.rozetka import card_from_snapshot, canonical_product_url, product_id_from_url


def test_rozetka_localized_urls_collapse_to_product_id():
    ua = "https://hard.rozetka.com.ua/ua/592071073/p592071073/"
    ru = "https://hard.rozetka.com.ua/592071073/p592071073/"
    assert product_id_from_url(ua) == "592071073"
    assert product_id_from_url(ru) == "592071073"
    assert canonical_product_url(ua) == canonical_product_url(ru)


def test_gold_p27qcb_ra_snapshot_becomes_verified_offer():
    card = card_from_snapshot({
        "url": "https://hard.rozetka.com.ua/ua/592071073/p592071073/",
        "title": "Монітор Xiaomi Redmi A27Q 2025 з багатофункціональною підставкою P27QCB-RA / 2560 x 1440 2K / IPS / 100 Гц / 27″ / Чорний",
        "model": "P27QCB-RA",
        "mpn": "P27QCB-RA",
        "seller_name": "WOWtech",
        "price": "8 999₴",
        "currency": "UAH",
        "availability": "Є в наявності",
        "match_status": "PASS",
    })

    assert card.product_id == "592071073"
    assert card.model == "P27QCB-RA"
    assert card.mpn == "P27QCB-RA"
    assert card.match_status == "PASS"
    assert len(card.offers) == 1
    assert card.offers[0].seller_name == "WOWtech"
    assert card.offers[0].price == 8999.0
    assert card.offers[0].availability == "IN_STOCK"
    assert card.offers[0].is_market_eligible is True
    assert {e.field for e in card.offers[0].evidence} >= {"price", "availability", "seller_name"}


def test_missing_product_id_is_parser_error_not_not_found():
    try:
        card_from_snapshot({"url": "https://hard.rozetka.com.ua/ua/monitors/", "title": "catalog"})
    except ValueError as exc:
        assert "product id" in str(exc).lower()
    else:
        raise AssertionError("expected strict parser error")
