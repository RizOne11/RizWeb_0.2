import asyncio
import json

from puma_scouts.models import ProductMission
from puma_scouts.query import generate_queries
from puma_scouts.serper import SerperDiscovery, extract_serper_links


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code
        self.calls = []

    async def post(self, url, *, headers, json):
        self.calls.append({"url": url, "headers": headers, "json": json})
        return _FakeResponse(self.payload, self.status_code)


class _FakeCache:
    def __init__(self):
        self.data = {}

    def get_search(self, key, max_age):
        return self.data.get(key)

    def put_search(self, key, payload):
        self.data[key] = payload


def test_serper_extracts_only_requested_marketplace_host():
    payload = {
        "organic": [
            {"link": "https://prom.ua/ua/p123-product.html"},
            {"link": "https://seller.prom.ua/p456-product.html"},
            {"link": "https://epicentrk.ua/ua/shop/other.html"},
            {"link": "https://prom.ua/ua/p123-product.html?utm_source=x"},
        ]
    }
    links = extract_serper_links(payload, allowed_host="prom.ua", max_results=10)
    assert links == [
        "https://prom.ua/ua/p123-product.html",
        "https://seller.prom.ua/p456-product.html",
    ]


def test_serper_is_discovery_only_and_never_reintroduces_article():
    mission = ProductMission(
        article="36-031",
        source_data={"name": "Молоток слесарный Polax 1000 г (36-031)", "brand": "Polax"},
    )
    queries = generate_queries(mission)
    assert queries
    assert all(mission.article.casefold() not in q.casefold() for q in queries)

    client = _FakeClient({"organic": [{"link": "https://prom.ua/ua/p999-hammer.html"}]})
    discovery = SerperDiscovery(api_key="test-key", max_results=5, cache=False)
    links = asyncio.run(discovery.search_urls(queries[0], client=client, site="prom.ua"))

    assert links == ["https://prom.ua/ua/p999-hammer.html"]
    assert client.calls
    call = client.calls[0]
    assert call["headers"]["X-API-KEY"] == "test-key"
    assert mission.article.casefold() not in call["json"]["q"].casefold()
    assert call["json"]["q"].startswith("site:prom.ua ")


def test_serper_without_key_is_disabled_and_makes_no_request():
    client = _FakeClient({"organic": [{"link": "https://prom.ua/ua/p1.html"}]})
    discovery = SerperDiscovery(api_key="", cache=False)
    links = asyncio.run(discovery.search_urls("Polax hammer", client=client, site="prom.ua"))
    assert links == []
    assert client.calls == []


def test_serper_reuses_cached_raw_discovery_response():
    cache = _FakeCache()
    client = _FakeClient({"organic": [{"link": "https://prom.ua/ua/p77-product.html"}]})
    discovery = SerperDiscovery(api_key="test-key", max_results=5, cache=cache, cache_ttl=3600)

    first = asyncio.run(discovery.search_urls("Polax hammer", client=client, site="prom.ua"))
    second = asyncio.run(discovery.search_urls("Polax hammer", client=client, site="prom.ua"))

    assert first == second == ["https://prom.ua/ua/p77-product.html"]
    assert len(client.calls) == 1
    assert discovery.api_requests == 1
    assert discovery.cache_hits == 1


def test_serper_circuit_breaker_stops_repeated_429_requests():
    client = _FakeClient({}, status_code=429)
    discovery = SerperDiscovery(api_key="test-key", cache=False)

    assert asyncio.run(discovery.search_urls("Polax hammer", client=client, site="prom.ua")) == []
    assert discovery.disabled_reason == "http_429"
    assert asyncio.run(discovery.search_urls("Polax hammer", client=client, site="prom.ua")) == []
    assert len(client.calls) == 1
