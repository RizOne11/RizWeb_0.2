from puma_scouts.models import ProductMission
from puma_scouts.price_score import assess_price_market
from puma_scouts.production import product_report


def offer(source, price, *, domain="", confidence="CONFIRMED"):
    return {
        "article": "A1",
        "name": "Test product",
        "source": source,
        "price": float(price),
        "currency": "UAH",
        "domain": domain,
        "identity_confidence": confidence,
        "url": f"https://{domain or source}.example/{price}",
    }


def test_balanced_market_uses_one_median_per_independent_source():
    offers = [
        offer("prom", 90),
        offer("prom", 110),
        offer("epicentr", 120),
        offer("web_shops", 80, domain="shop-a.ua"),
        offer("web_shops", 100, domain="shop-b.ua"),
    ]
    result = assess_price_market(offers, 100)

    assert result["market_sources"] == 4
    assert sorted(x["price"] for x in result["market_representatives"]) == [80, 100, 100, 120]
    assert result["market_median"] == 100


def test_price_score_matches_legacy_anchor_points():
    market = [offer("prom", 100), offer("epicentr", 100)]

    assert assess_price_market(market, 85)["price_score"] == 100
    assert assess_price_market(market, 100)["price_score"] == 50
    assert assess_price_market(market, 120)["price_score"] == 0


def test_hot_verdict_is_downgraded_with_only_one_independent_source():
    result = assess_price_market([offer("prom", 100)], 80)
    assert result["price_score"] == 100
    assert result["price_verdict"] == "🟡 ТЕСТУВАТИ"
    assert result["price_verdict_reason"] == "ONLY_ONE_INDEPENDENT_SOURCE"


def test_hot_or_green_is_downgraded_without_confirmed_identity():
    offers = [
        offer("prom", 100, confidence="PROBABLE"),
        offer("epicentr", 110, confidence="PROBABLE"),
    ]
    result = assess_price_market(offers, 85)
    assert result["price_score"] >= 65
    assert result["price_verdict"] == "🟡 ТЕСТУВАТИ"
    assert result["price_verdict_reason"] == "NO_CONFIRMED_IDENTITY"


def test_extreme_price_outlier_is_audited_but_excluded():
    bad = offer("prom", 100)
    offers = [
        bad,
        offer("epicentr", 1000),
        offer("web_shops", 1100, domain="shop.ua"),
    ]
    result = assess_price_market(offers, 1000)

    assert result["suspicious_price_count"] == 1
    assert bad["price_status"] == "SUSPICIOUS"
    assert "price consensus outlier" in bad["price_reason"]
    assert result["market_min"] == 1000
    assert result["market_max"] == 1100


def test_product_report_exposes_score_and_balanced_market_metrics():
    mission = ProductMission(
        article="A1",
        source_data={"name": "Test product", "own_price": "90"},
    )
    rows = [
        offer("prom", 100),
        offer("prom", 120),
        offer("epicentr", 110),
    ]
    product = product_report([mission], rows)[0]

    assert product["price_score"] > 50
    assert product["price_verdict"]
    assert product["sources"] == 2
    assert product["median_price"] == 110
    assert product["valid_offer_count"] == 3
