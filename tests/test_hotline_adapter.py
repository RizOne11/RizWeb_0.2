from priceintel.adapters.hotline import card_from_snapshots, product_id_from_url


def test_hotline_gold_p27qcb_ra_offer_is_preserved():
    url = "https://hotline.ua/ua/computer/monitory/116913-639725/"
    card = card_from_snapshots([{
        "url": url,
        "title": "Xiaomi Redmi A27Q 2025",
        "model": "P27QCB-RA",
        "mpn": "P27QCB-RA",
        "seller_name": "Wondertech",
        "price": "9 999 ₴",
        "currency": "UAH",
        "availability": "В наявності",
    }], product_id="P27QCB-RA", model="P27QCB-RA", mpn="P27QCB-RA", match_status="PASS")

    assert card.marketplace == "Hotline"
    assert card.mpn == "P27QCB-RA"
    assert len(card.offers) == 1
    assert card.offers[0].seller_name == "Wondertech"
    assert card.offers[0].price == 9999.0
    assert card.offers[0].availability == "IN_STOCK"
    assert card.offers[0].is_market_eligible


def test_hotline_preserves_multiple_shop_offers():
    rows = [
        {"url": "https://hotline.ua/ua/computer/monitory/116913-639725/", "shop_id": "a", "shop_name": "Shop A", "price": 9999, "availability": "В наявності"},
        {"url": "https://hotline.ua/ua/computer/monitory/116913-639725/", "shop_id": "b", "shop_name": "Shop B", "price": 10200, "availability": "В наявності"},
    ]
    card = card_from_snapshots(rows, product_id="P27QCB-RA", mpn="P27QCB-RA")
    assert len(card.offers) == 2
    assert {o.seller_name for o in card.offers} == {"Shop A", "Shop B"}


def test_hotline_unknown_availability_is_not_eligible():
    card = card_from_snapshots([{
        "url": "https://hotline.ua/ua/computer/monitory/116913-639725/",
        "seller_name": "Wondertech", "price": 9999, "availability": "уточнюйте",
    }], product_id="P27QCB-RA")
    assert card.offers[0].availability == "UNKNOWN"
    assert not card.offers[0].is_market_eligible


def test_hotline_product_id_parser_accepts_monitor_path():
    assert product_id_from_url("https://hotline.ua/ua/computer/monitory/116913-639725/") == "116913"
