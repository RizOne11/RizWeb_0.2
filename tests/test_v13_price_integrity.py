import json

from puma_scouts.models import ProductMission
from puma_scouts.production import product_report
from puma_scouts.scouts.catalog import PromScout
from puma_scouts.scouts.web_shops import WebShopsScout


def _mission():
    return ProductMission(
        article="11676",
        source_data={
            "name": "Комплект наушники с кейсом Marshall Major IV Bluetooth Black (1005773)",
            "brand": "Marshall",
            "model": "Major IV",
            "own_price": "4248.75",
        },
    )


def _jsonld_page(price: str, currency: str) -> str:
    payload = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": "Навушники Marshall Major IV Bluetooth Black (1005773)",
        "sku": "1005773",
        "brand": {"@type": "Brand", "name": "Marshall"},
        "offers": {
            "@type": "Offer",
            "price": price,
            "priceCurrency": currency,
            "availability": "https://schema.org/InStock",
        },
    }
    return '<script type="application/ld+json">' + json.dumps(payload) + "</script>"


def test_web_shop_preserves_jsonld_currency():
    scout = WebShopsScout()
    offer = scout._offer(
        _mission(),
        "https://shop.example.ua/marshall-major-iv",
        _jsonld_page("89.16", "USD"),
        "Marshall Major IV",
    )
    assert offer is not None
    assert offer.currency == "USD"
    assert float(offer.price) == 89.16


def test_catalog_scout_preserves_jsonld_currency():
    scout = PromScout()
    offer = scout._offer(
        _mission(),
        "https://prom.ua/ua/p123-marshall-major-iv.html",
        _jsonld_page("99.50", "USD"),
        "Marshall Major IV",
        "native",
    )
    assert offer is not None
    assert offer.currency == "USD"
    assert float(offer.price) == 99.50


def test_product_report_never_mixes_foreign_currency_into_uah_statistics():
    rows = [
        {
            "article": "11676",
            "name": _mission().source_data["name"],
            "source": "web_shops",
            "price": 89.16,
            "currency": "USD",
            "found_title": "Навушники Marshall Major IV Bluetooth Black (1005773)",
            "identity_confidence": "CONFIRMED",
        },
        {
            "article": "11676",
            "name": _mission().source_data["name"],
            "source": "hotline",
            "price": 3999.0,
            "currency": "UAH",
            "found_title": "Marshall Major IV Black (1005773)",
            "identity_confidence": "CONFIRMED",
        },
    ]
    report = product_report([_mission()], rows)[0]
    assert report["min_price"] == 3999.0
    assert report["median_price"] == 3999.0
    assert report["avg_price"] == 3999.0
    assert report["max_price"] == 3999.0
    assert "89.16" not in report["marketplaces"]


def test_uah_currency_alias_is_accepted_for_statistics():
    rows = [
        {
            "article": "11676",
            "name": _mission().source_data["name"],
            "source": "web_shops",
            "price": 4100.0,
            "currency": "₴",
            "found_title": "Навушники Marshall Major IV Bluetooth Black (1005773)",
            "identity_confidence": "CONFIRMED",
        }
    ]
    report = product_report([_mission()], rows)[0]
    assert report["min_price"] == 4100.0
