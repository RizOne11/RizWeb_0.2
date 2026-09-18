from __future__ import annotations

import asyncio
from decimal import Decimal

from puma_scouts.models import (
    IdentityConfidence,
    Marketplace,
    Offer,
    ProductMission,
    ValidatedOffer,
    Verdict,
)
from puma_scouts.scouts import catalog as catalog_module
from puma_scouts.scouts.rozetka_serper import RozetkaSerperScout


def _mission():
    return ProductMission(
        article="ROW-TEST",
        source_data={"name": "JBL C50HI Red", "brand": "JBL", "model": "C50HI"},
    )


def _offer():
    return Offer(
        article="ROW-TEST",
        marketplace=Marketplace.ROZETKA,
        marketplace_product_id="123456",
        title="Навушники JBL C50HI Red",
        price=Decimal("399"),
        currency="UAH",
        url="https://rozetka.com.ua/ua/jbl-c50hi-red/p123456/",
        attributes={"brand": "JBL", "model": "C50HI"},
    )


def _validated(offer):
    return ValidatedOffer(
        offer=offer,
        verdict=Verdict.PASS,
        score=0.99,
        identity_confidence=IdentityConfidence.CONFIRMED,
    )


def test_rozetka_lab_disables_native_and_external_discovery():
    scout = RozetkaSerperScout(timeout=1, max_candidates_per_query=5)

    async def scenario():
        try:
            assert await scout._native_candidate_urls(None, "JBL C50HI") == []
            assert await scout._external_candidate_urls(None, "JBL C50HI") == []
        finally:
            await scout.aclose()

    asyncio.run(scenario())


def test_rozetka_lab_uses_serper_and_stops_after_first_success(monkeypatch):
    scout = RozetkaSerperScout(timeout=1, max_candidates_per_query=5)
    scout.serper.api_key = "test-key"
    mission = _mission()
    stages = []

    async def fake_queries(_mission):
        return ["JBL C50HI Red", "JBL C50HI"]

    async def fake_stage(client, mission, query, method):
        stages.append((method, query))
        if method == "serper":
            scout.serper.api_requests += 1
            return 1, [_offer()]
        return 0, []

    monkeypatch.setattr(catalog_module, "load_identity_urls", lambda *a, **k: [])
    monkeypatch.setattr(catalog_module, "remember_confirmed_identities", lambda *a, **k: 1)
    monkeypatch.setattr(catalog_module, "validate_offer", lambda mission, offer: _validated(offer))
    monkeypatch.setattr(scout, "generate_queries", fake_queries)
    monkeypatch.setattr(scout, "_discover_stage", fake_stage)

    async def scenario():
        try:
            return await scout.scan(mission)
        finally:
            await scout.aclose()

    report = asyncio.run(scenario())

    serper_calls = [item for item in stages if item[0] == "serper"]
    assert serper_calls == [("serper", "JBL C50HI Red")]
    assert report.metrics["serper_queries_attempted"] == 1
    assert report.metrics["serper_api_requests"] == 1
    assert report.metrics["serper_rescued"] is True
    assert report.metrics["serper_success_query"] == 1
    assert report.health.value == "FOUND"



def test_rozetka_query_matrix_prioritizes_public_model():
    scout = RozetkaSerperScout(timeout=1, max_candidates_per_query=5)
    mission = _mission()

    async def scenario():
        try:
            return await scout.generate_queries(mission)
        finally:
            await scout.aclose()

    queries = asyncio.run(scenario())
    assert queries[0] == "C50HI"
    assert queries[1] == "JBL C50HI"


def test_rozetka_serper_filters_host_locally_without_site_operator(monkeypatch):
    scout = RozetkaSerperScout(timeout=1, max_candidates_per_query=5)
    calls = []

    async def fake_hits(query, **kwargs):
        calls.append((query, kwargs))
        return [
            {
                "url": "https://rozetka.com.ua/ua/jbl-c50hi-red/p123456/",
                "title": "Навушники JBL C50HI Red",
                "snippet": "399 грн",
                "price_hint": 399,
                "source": "organic",
            }
        ]

    monkeypatch.setattr(scout.serper, "search_hits", fake_hits)

    async def scenario():
        try:
            return await scout._serper_candidate_urls(None, "JBL C50HI")
        finally:
            await scout.aclose()

    urls = asyncio.run(scenario())
    assert urls == ["https://rozetka.com.ua/ua/jbl-c50hi-red/p123456/"]
    assert calls[0][1]["allowed_host"] == "rozetka.com.ua"
    assert calls[0][1]["use_site_operator"] is False


def test_rozetka_serper_metadata_price_fallback():
    scout = RozetkaSerperScout(timeout=1, max_candidates_per_query=5)
    mission = _mission()
    url = "https://rozetka.com.ua/ua/jbl-c50hi-red/p123456/"
    scout._serper_hit_meta[url] = {
        "url": url,
        "title": "Навушники JBL C50HI Red",
        "snippet": "Ціна 399 грн",
        "price_hint": 399,
        "source": "organic",
    }
    offer = scout._serper_fallback_offer(mission, url, "JBL C50HI")
    assert offer is not None
    assert offer.marketplace == Marketplace.ROZETKA
    assert offer.marketplace_product_id == "123456"
    assert offer.price == Decimal("399")
    assert offer.discovery_method == "serper->rozetka-local-filter->snippet-price"
