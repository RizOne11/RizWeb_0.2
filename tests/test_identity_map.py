from decimal import Decimal

import asyncio

from priceintel.cache import Cache
from puma_scouts import identity_map
from puma_scouts.models import (
    IdentityConfidence,
    Marketplace,
    Offer,
    ProductMission,
    ValidatedOffer,
    Verdict,
)
from puma_scouts.scouts import web_shops as web_module
from puma_scouts.scouts.web_shops import WebShopsScout


def _mission():
    return ProductMission(
        article="SKU-1",
        source_data={"name": "Honda EU35i", "brand": "Honda", "model": "EU35i"},
    )


def _offer(url="https://shop.example.ua/honda-eu35i", price=Decimal("34999")):
    return Offer(
        article="SKU-1",
        marketplace=Marketplace.WEB_SHOPS,
        title="Honda EU35i",
        price=price,
        currency="UAH",
        url=url,
        attributes={"source_domain": "shop.example.ua"},
    )


def _validated(offer=None):
    return ValidatedOffer(
        offer=offer or _offer(),
        verdict=Verdict.PASS,
        score=0.99,
        identity_confidence=IdentityConfidence.CONFIRMED,
    )


def test_identity_map_round_trip_uses_product_fingerprint(tmp_path, monkeypatch):
    cache = Cache(str(tmp_path / "identity.sqlite"))
    monkeypatch.setattr(identity_map, "runtime_cache", lambda: cache)
    monkeypatch.setattr(identity_map, "identity_cache_seconds", lambda: 3600)

    mission = _mission()
    saved = identity_map.remember_confirmed_identities(
        mission, "web_shops", [_validated()]
    )

    assert saved == 1
    assert identity_map.load_identity_urls(mission, "web_shops") == [
        "https://shop.example.ua/honda-eu35i"
    ]

    changed = ProductMission(
        article="SKU-1",
        source_data={"name": "Honda EU35i NEW", "brand": "Honda", "model": "EU35i"},
    )
    assert identity_map.load_identity_urls(changed, "web_shops") == []


def test_webshops_serper_stops_after_first_success(monkeypatch):
    scout = WebShopsScout(timeout=1, max_candidates_per_query=5)
    scout.serper.api_key = "test-key"
    mission = _mission()
    calls = []

    async def fake_queries(_mission):
        return ["Honda EU35i", "Хонда EU35i"]

    async def no_free_urls(client, query):
        return []

    async def serper_urls(client, query):
        calls.append(query)
        scout.serper.api_requests += 1
        return ["https://shop.example.ua/honda-eu35i"]

    async def fetch_urls(client, mission, query, urls, method):
        return [_offer()] if urls else []

    monkeypatch.setattr(web_module, "load_identity_urls", lambda *a, **k: [])
    monkeypatch.setattr(web_module, "remember_confirmed_identities", lambda *a, **k: 1)
    monkeypatch.setattr(web_module, "validate_offer", lambda mission, offer: _validated(offer))
    monkeypatch.setattr(scout, "generate_queries", fake_queries)
    monkeypatch.setattr(scout, "_urls", no_free_urls)
    monkeypatch.setattr(scout, "_serper_urls", serper_urls)
    monkeypatch.setattr(scout, "_fetch_urls", fetch_urls)

    report = asyncio.run(scout.scan(mission))

    assert calls == ["Honda EU35i"]
    assert report.metrics["serper_queries_attempted"] == 1
    assert report.metrics["serper_api_requests"] == 1
    assert report.metrics["serper_rescued"] is True
    assert report.metrics["serper_success_query"] == 1


def test_webshops_identity_hit_skips_discovery_and_serper(monkeypatch):
    scout = WebShopsScout(timeout=1, max_candidates_per_query=5)
    mission = _mission()
    free_search_calls = 0

    async def fake_queries(_mission):
        return ["Honda EU35i"]

    async def should_not_search(client, query):
        nonlocal free_search_calls
        free_search_calls += 1
        return []

    async def fetch_urls(client, mission, query, urls, method):
        assert method == "identity-refresh"
        return [_offer()] if urls else []

    monkeypatch.setattr(
        web_module,
        "load_identity_urls",
        lambda *a, **k: ["https://shop.example.ua/honda-eu35i"],
    )
    monkeypatch.setattr(web_module, "remember_confirmed_identities", lambda *a, **k: 1)
    monkeypatch.setattr(web_module, "validate_offer", lambda mission, offer: _validated(offer))
    monkeypatch.setattr(scout, "generate_queries", fake_queries)
    monkeypatch.setattr(scout, "_urls", should_not_search)
    monkeypatch.setattr(scout, "_fetch_urls", fetch_urls)

    report = asyncio.run(scout.scan(mission))

    assert free_search_calls == 0
    assert report.metrics["identity_refresh_hit"] is True
    assert report.metrics["identity_urls_loaded"] == 1
    assert report.metrics["serper_queries_attempted"] == 0



def test_shared_http_client_reused_for_scout_lifetime():
    scout = WebShopsScout(timeout=1, max_candidates_per_query=5)

    async def scenario():
        first = await scout.http_client()
        second = await scout.http_client()
        assert first is second
        assert not first.is_closed
        await scout.aclose()
        assert first.is_closed

    asyncio.run(scenario())


def test_refresh_only_marks_repair_without_discovery(monkeypatch):
    scout = WebShopsScout(timeout=1, max_candidates_per_query=5)
    mission = _mission()
    free_search_calls = 0
    seen_limit = None

    async def fake_queries(_mission):
        return ["Honda EU35i"]

    async def should_not_search(client, query):
        nonlocal free_search_calls
        free_search_calls += 1
        return []

    async def dead_identity(client, mission, query, urls, method):
        assert method == "identity-refresh"
        return []

    def load_urls(*args, **kwargs):
        nonlocal seen_limit
        seen_limit = kwargs.get("limit")
        return ["https://shop.example.ua/honda-eu35i"]

    monkeypatch.setenv("PUMA_REFRESH_ONLY", "1")
    monkeypatch.delenv("PUMA_REFRESH_WEB_URL_LIMIT", raising=False)
    monkeypatch.setattr(web_module, "load_identity_urls", load_urls)
    monkeypatch.setattr(scout, "generate_queries", fake_queries)
    monkeypatch.setattr(scout, "_urls", should_not_search)
    monkeypatch.setattr(scout, "_fetch_urls", dead_identity)

    async def scenario():
        try:
            return await scout.scan(mission)
        finally:
            await scout.aclose()

    report = asyncio.run(scenario())

    assert seen_limit == 3
    assert free_search_calls == 0
    assert report.metrics["refresh_only"] is True
    assert report.metrics["repair_required"] is True
    assert report.metrics["serper_queries_attempted"] == 0
    assert report.offers == []
