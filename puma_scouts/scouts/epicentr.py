from __future__ import annotations

import asyncio
import html as html_lib
import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import quote_plus, urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup

from puma_scouts.identity_map import load_identity_urls, remember_confirmed_identities
from puma_scouts.models import Marketplace, Offer, ProductMission, ScanHealth, ScanReport, Verdict
from puma_scouts.query import generate_queries
from puma_scouts.scouts.base import MarketplaceScout
from puma_scouts.serper import SerperDiscovery
from puma_scouts.runtime_cache import page_cache_seconds, runtime_cache
from puma_scouts.validator import validate_offer

_EPICENTR_HOSTS = {"epicentrk.ua", "www.epicentrk.ua"}
_PRODUCT_PATH_RE = re.compile(r"/(?:ua/)?(?:shop|shop-mplc)/[^?#]+\.html$", re.I)


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(str(value or ""))).strip()


def _canonical_url(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit(("https", parsed.netloc.lower(), parsed.path, "", ""))


def _is_product_url(url: str) -> bool:
    parsed = urlsplit(url)
    return parsed.netloc.lower() in _EPICENTR_HOSTS and bool(_PRODUCT_PATH_RE.search(parsed.path))


def _decimal_price(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    text = re.sub(r"[^0-9.]", "", _clean(value).replace("\u00a0", "").replace(" ", "").replace(",", "."))
    try:
        result = Decimal(text)
        return result if result > 0 else None
    except (InvalidOperation, ValueError):
        return None


def _jsonld_products(page: str) -> list[dict[str, Any]]:
    products = []
    pattern = r'<script\b[^>]*\btype\s*=\s*["\']application/ld\+json["\'][^>]*>(.*?)</script\s*>'
    for raw in re.findall(pattern, page, flags=re.I | re.S):
        payload = None
        for candidate in (raw.strip(), html_lib.unescape(raw).strip()):
            try:
                payload = json.loads(candidate)
                break
            except (json.JSONDecodeError, TypeError):
                continue
        if payload is None:
            continue
        for item in payload if isinstance(payload, list) else [payload]:
            if not isinstance(item, dict):
                continue
            if str(item.get("@type", "")).casefold() == "product":
                products.append(item)
            graph = item.get("@graph")
            if isinstance(graph, list):
                products.extend(
                    x for x in graph
                    if isinstance(x, dict) and str(x.get("@type", "")).casefold() == "product"
                )
    return products


def _meta(page: str, key: str) -> str | None:
    soup = BeautifulSoup(page, "html.parser")
    tag = soup.find("meta", attrs={"property": key}) or soup.find("meta", attrs={"name": key})
    return _clean(tag.get("content")) if tag and tag.get("content") else None


def _extract_embedded_price(page: str) -> Decimal | None:
    soup = BeautifulSoup(page, "html.parser")
    for tag in soup.select('[itemprop="price"], [data-price], meta[property="product:price:amount"], meta[property="og:price:amount"]'):
        for attr in ("content", "value", "data-price"):
            price = _decimal_price(tag.get(attr))
            if price and price >= 10:
                return price
    patterns = (
        r'"(?:price|currentPrice|finalPrice|priceValue|productPrice|salePrice|actualPrice)"\s*:\s*(?:"|\{[^{}]{0,160}?"(?:value|amount)"\s*:\s*")?([0-9][0-9\s.,]{1,15})',
        r'(?:data-price|itemprop=["\']price["\'])[^>]{0,160}?(?:content|value|data-price)?\s*=\s*["\']([0-9][0-9\s.,]{1,15})',
        r'(?:Ціна|Цена)\s*:?\s*(?:</?[^>]+>\s*){0,6}([0-9][0-9\s]{2,10})\s*(?:₴|грн)',
        r'([0-9][0-9\s]{2,10})\s*(?:₴|грн)(?:\s*/\s*(?:шт\.?|од\.?))?',
    )
    for pattern in patterns:
        for match in re.finditer(pattern, page, flags=re.I | re.S):
            price = _decimal_price(match.group(1))
            if price and price >= 10:
                return price
    return None


def _offer_from_page(article: str, url: str, page: str, query: str, method: str = "native") -> Offer | None:
    title = _meta(page, "og:title") or ""
    price = _decimal_price(_meta(page, "product:price:amount") or _meta(page, "og:price:amount"))
    availability = None
    seller_name = None
    attrs = {"source": "epicentr-product-page", "discovery_stage": method}
    products = _jsonld_products(page)
    if products:
        product = products[0]
        title = _clean(product.get("name")) or title
        for key in ("sku", "mpn", "gtin", "gtin13", "model"):
            if product.get(key):
                attrs[key] = product[key]
        brand = product.get("brand")
        attrs["brand"] = brand.get("name") if isinstance(brand, dict) else brand
        offers = product.get("offers")
        offers = offers[0] if isinstance(offers, list) and offers else offers
        if isinstance(offers, dict):
            price = price or _decimal_price(offers.get("price") or offers.get("lowPrice"))
            availability = _clean(offers.get("availability")) or None
            seller = offers.get("seller")
            seller_name = _clean(seller.get("name")) if isinstance(seller, dict) else None
    if not title:
        soup = BeautifulSoup(page, "html.parser")
        title = _clean(soup.title.string if soup.title else "")
    if not title:
        return None
    price = price or _extract_embedded_price(page)
    return Offer(
        article=article,
        marketplace=Marketplace.EPICENTR,
        marketplace_product_id=_clean(attrs.get("sku")) or None,
        seller_name=seller_name,
        title=title,
        price=price,
        availability=availability,
        url=_canonical_url(url),
        image_urls=[],
        attributes=attrs,
        query_used=query,
        discovery_method=f"epicentr-{method}->product-page",
    )


class EpicentrScout(MarketplaceScout):
    marketplace = Marketplace.EPICENTR

    def __init__(self, *, timeout: float = 15.0, max_candidates_per_query: int = 30) -> None:
        self.timeout = timeout
        self.max_candidates_per_query = max_candidates_per_query
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128 Safari/537.36",
            "Accept-Language": "uk-UA,uk;q=0.9,ru;q=0.7,en;q=0.5",
        }
        self.serper = SerperDiscovery(max_results=max_candidates_per_query, timeout=min(timeout, 10.0))
        self.cache = runtime_cache()
        self.page_cache_ttl = page_cache_seconds()

    async def generate_queries(self, mission: ProductMission) -> list[str]:
        article = mission.article.casefold().strip()
        useful = []
        for query in generate_queries(mission):
            q = query.strip()
            if not q or q.casefold() == article or re.fullmatch(r"(?:19|20)\d{2}", q) or (article and article in q.casefold()):
                continue
            if q not in useful:
                useful.append(q)
        return useful[:4]

    async def _get(self, client: httpx.AsyncClient, url: str) -> str:
        response = await client.get(url, headers=self.headers, follow_redirects=True)
        response.raise_for_status()
        return response.text

    async def _get_product(self, client: httpx.AsyncClient, url: str) -> str:
        key = _canonical_url(url)
        if self.cache and self.page_cache_ttl > 0:
            try:
                cached = await asyncio.to_thread(self.cache.get, key, self.page_cache_ttl)
                if cached is not None:
                    return cached
            except Exception:
                pass
        page = await self._get(client, url)
        if self.cache and self.page_cache_ttl > 0:
            try:
                await asyncio.to_thread(self.cache.put, key, page)
            except Exception:
                pass
        return page

    async def _candidate_urls(self, client: httpx.AsyncClient, query: str) -> list[str]:
        found = {}
        last_error = None
        for search_url in (
            f"https://epicentrk.ua/ua/search/?q={quote_plus(query)}",
            f"https://epicentrk.ua/ua/search/?search={quote_plus(query)}",
        ):
            try:
                page = await self._get(client, search_url)
            except httpx.HTTPError as exc:
                last_error = exc
                continue
            decoded = html_lib.unescape(page).replace("\\/", "/")
            for href in re.findall(r'href=["\']([^"\']+)["\']', decoded, flags=re.I):
                url = urljoin(search_url, href)
                if _is_product_url(url):
                    found.setdefault(_canonical_url(url), None)
            for raw in re.findall(r'https?://(?:www\.)?epicentrk\.ua/(?:ua/)?(?:shop|shop-mplc)/[^\s"\'<>]+?\.html', decoded, flags=re.I):
                if _is_product_url(raw):
                    found.setdefault(_canonical_url(raw), None)
            if found:
                break
        if found:
            return list(found)[: self.max_candidates_per_query]
        if last_error:
            raise last_error
        return []

    async def _serper_candidate_urls(self, client: httpx.AsyncClient, query: str) -> list[str]:
        urls = await self.serper.search_urls(query, client=client, site="epicentrk.ua")
        return [url for url in urls if _is_product_url(url)][: self.max_candidates_per_query]

    async def _fetch_offers(self, client, mission, query, urls, method):
        async def one(url):
            try:
                return _offer_from_page(mission.article, url, await self._get_product(client, url), query, method)
            except (httpx.HTTPError, ValueError, json.JSONDecodeError):
                return None
        result = await asyncio.gather(*(one(url) for url in urls))
        return [offer for offer in result if offer]

    async def discover(self, mission: ProductMission, query: str) -> list[Offer]:
        client = await self.http_client()
        offers = await self._fetch_offers(client, mission, query, await self._candidate_urls(client, query), "native")
        if offers:
            return offers
        if self.serper.enabled:
            return await self._fetch_offers(client, mission, query, await self._serper_candidate_urls(client, query), "serper")
        return []

    async def scan(self, mission: ProductMission) -> ScanReport:
        queries = await self.generate_queries(mission)
        unique = {}
        errors = []
        seen = 0
        source_name = self.marketplace.value
        metrics = {
            "identity_urls_loaded": 0,
            "identity_refresh_hit": False,
            "identity_urls_saved": 0,
            "serper_queries_attempted": 0,
            "serper_api_requests": 0,
            "serper_cache_hits": 0,
            "serper_rescued": False,
            "serper_success_query": 0,
            "refresh_only": self.refresh_only(),
            "identity_urls_attempted": 0,
            "repair_required": False,
        }

        client = await self.http_client()
        identity_limit = self.identity_refresh_limit() if self.refresh_only() else self.max_candidates_per_query
        known_urls = load_identity_urls(mission, source_name, limit=identity_limit)
        metrics["identity_urls_loaded"] = len(known_urls)
        metrics["identity_urls_attempted"] = len(known_urls)
        if known_urls:
            identity_offers = await self._fetch_offers(
                client, mission, "identity-map", known_urls, "identity-refresh"
            )
            for offer in identity_offers:
                unique.setdefault(str(offer.url), offer)
            identity_validated = [validate_offer(mission, offer) for offer in unique.values()]
            identity_price_passes = [
                item for item in identity_validated
                if item.verdict == Verdict.PASS and item.offer.price is not None
            ]
            if identity_price_passes:
                metrics["identity_refresh_hit"] = True
                metrics["identity_urls_saved"] = remember_confirmed_identities(
                    mission, source_name, identity_validated
                )
                return ScanReport(
                    article=mission.article,
                    marketplace=self.marketplace,
                    health=ScanHealth.FOUND,
                    queries_generated=0,
                    pages_scanned=len(unique),
                    candidates_seen=len(known_urls),
                    candidates_collected=len(unique),
                    duplicates_removed=max(0, len(known_urls) - len(unique)),
                    search_rounds=0,
                    errors=[],
                    offers=identity_validated,
                    metrics=metrics,
                )
            unique.clear()

        if self.refresh_only():
            metrics["repair_required"] = True
            return ScanReport(
                article=mission.article,
                marketplace=self.marketplace,
                health=ScanHealth.NOT_FOUND,
                queries_generated=0,
                pages_scanned=0,
                candidates_seen=metrics["identity_urls_attempted"],
                candidates_collected=0,
                duplicates_removed=0,
                search_rounds=0,
                errors=[],
                offers=[],
                metrics=metrics,
            )

        native_results = await asyncio.gather(
            *(self._candidate_urls(client, query) for query in queries),
            return_exceptions=True,
        )
        native_batches = []
        for query, result in zip(queries, native_results):
            if isinstance(result, Exception):
                errors.append(f"search {query!r}: {type(result).__name__}: {result}")
                continue
            seen += len(result)
            native_batches.append((query, result))

        native_offers = await asyncio.gather(
            *(self._fetch_offers(client, mission, query, urls, "native") for query, urls in native_batches),
            return_exceptions=True,
        )
        for (query, _), offers in zip(native_batches, native_offers):
            if isinstance(offers, Exception):
                errors.append(f"fetch {query!r}: {type(offers).__name__}: {offers}")
                continue
            for offer in offers:
                unique.setdefault(str(offer.url), offer)

        validated = [validate_offer(mission, offer) for offer in unique.values()]
        price_passes = [
            item for item in validated
            if item.verdict == Verdict.PASS and item.offer.price is not None
        ]

        # Query #2 is only spent if query #1 failed to produce a priced PASS.
        if not price_passes and self.serper.enabled:
            for index, query in enumerate(queries[:2], 1):
                metrics["serper_queries_attempted"] += 1
                before_api = self.serper.api_requests
                before_cache = self.serper.cache_hits
                try:
                    urls = await self._serper_candidate_urls(client, query)
                    offers = await self._fetch_offers(client, mission, query, urls, "serper")
                except Exception as exc:
                    errors.append(f"serper {query!r}: {type(exc).__name__}: {exc}")
                    metrics["serper_api_requests"] += self.serper.api_requests - before_api
                    metrics["serper_cache_hits"] += self.serper.cache_hits - before_cache
                    continue
                metrics["serper_api_requests"] += self.serper.api_requests - before_api
                metrics["serper_cache_hits"] += self.serper.cache_hits - before_cache
                seen += len(urls)
                for offer in offers:
                    unique.setdefault(str(offer.url), offer)

                validated = [validate_offer(mission, offer) for offer in unique.values()]
                price_passes = [
                    item for item in validated
                    if item.verdict == Verdict.PASS and item.offer.price is not None
                ]
                if price_passes:
                    metrics["serper_rescued"] = True
                    metrics["serper_success_query"] = index
                    break

        validated = [validate_offer(mission, offer) for offer in unique.values()]
        passes = [item for item in validated if item.verdict == Verdict.PASS]
        conflicts = [item for item in validated if item.verdict == Verdict.CONFLICT]
        metrics["identity_urls_saved"] = remember_confirmed_identities(
            mission, source_name, validated
        )
        health = (
            ScanHealth.PARTIAL if passes and errors
            else ScanHealth.FOUND if passes
            else ScanHealth.PARTIAL if conflicts
            else ScanHealth.ACCESS_LIMITED if errors and not validated
            else ScanHealth.NOT_FOUND
        )
        return ScanReport(
            article=mission.article,
            marketplace=self.marketplace,
            health=health,
            queries_generated=len(queries),
            pages_scanned=len(unique),
            candidates_seen=seen,
            candidates_collected=len(unique),
            duplicates_removed=max(0, seen - len(unique)),
            search_rounds=len(queries),
            errors=errors,
            offers=validated,
            metrics=metrics,
        )
