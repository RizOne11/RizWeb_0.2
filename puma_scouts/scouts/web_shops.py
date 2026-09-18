from __future__ import annotations

import asyncio
import html as html_lib
import os
from collections import defaultdict
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from puma_scouts.models import Marketplace, Offer, ProductMission, ScanHealth, ScanReport, Verdict
from puma_scouts.query import generate_queries
from puma_scouts.scouts.base import MarketplaceScout
from puma_scouts.scouts.catalog import _canonical, _jsonld_products, _clean, _price, _currency
from puma_scouts.serper import SerperDiscovery
from puma_scouts.runtime_cache import page_cache_seconds, runtime_cache
from puma_scouts.validator import validate_offer


class WebShopsScout(MarketplaceScout):
    marketplace = Marketplace.WEB_SHOPS
    blocked_domains = (
        "prom.ua", "epicentrk.ua", "hotline.ua", "rozetka.com.ua", "zakupka.com",
        "allo.ua", "comfy.ua", "foxtrot.com.ua", "kasta.ua", "google.com",
        "bing.com", "duckduckgo.com", "brave.com", "yandex.ru", "yandex.com",
        "youtube.com", "facebook.com", "instagram.com", "tiktok.com",
    )

    def __init__(self, *, timeout=15, max_candidates_per_query=20, max_per_domain=2):
        self.timeout = timeout
        self.max_candidates_per_query = max_candidates_per_query
        self.max_per_domain = max_per_domain
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128 Safari/537.36",
            "Accept-Language": "uk-UA,uk;q=0.9,ru;q=0.7,en;q=0.5",
        }
        self.serper = SerperDiscovery(max_results=max_candidates_per_query, timeout=min(timeout, 10.0))
        self.cache = runtime_cache()
        self.page_cache_ttl = page_cache_seconds()
        self.query_concurrency = max(1, min(int(os.getenv("PUMA_WEBSHOPS_QUERY_CONCURRENCY", "2")), 5))

    async def generate_queries(self, mission: ProductMission):
        article = mission.article.casefold().strip()
        out = []
        for query in generate_queries(mission):
            query = query.strip()
            if not query or query.casefold() == article or (article and article in query.casefold()):
                continue
            if query not in out:
                out.append(query)
        return [f"{query} купити грн" for query in out[:5]]

    def _blocked(self, host):
        host = host.casefold().removeprefix("www.")
        return any(host == x or host.endswith("." + x) for x in self.blocked_domains)

    def _unwrap(self, href, base):
        url = urljoin(base, html_lib.unescape(href))
        parsed = urlsplit(url)
        if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
            wrapped = parse_qs(parsed.query).get("uddg", [])
            url = unquote(wrapped[0]) if wrapped else url
        return url

    def _links(self, page, base):
        out = []
        per_domain = defaultdict(int)
        for tag in BeautifulSoup(page, "html.parser").find_all("a", href=True):
            url = self._unwrap(tag["href"], base)
            parsed = urlsplit(url)
            host = parsed.netloc.casefold().removeprefix("www.")
            if parsed.scheme not in ("http", "https") or not host or self._blocked(host) or not parsed.path or parsed.path == "/":
                continue
            text = (tag.get_text(" ", strip=True) + " " + url).casefold()
            uaish = host.endswith(".ua") or any(x in text for x in ("купити", "ціна", "грн", "uah", "україн"))
            if not uaish or per_domain[host] >= self.max_per_domain:
                continue
            canonical = _canonical(url)
            if canonical not in out:
                out.append(canonical)
                per_domain[host] += 1
            if len(out) >= self.max_candidates_per_query:
                break
        return out

    async def _get(self, client, url):
        response = await client.get(url, headers=self.headers, follow_redirects=True)
        response.raise_for_status()
        return response.text

    async def _get_product(self, client, url):
        key = _canonical(url)
        if self.cache and self.page_cache_ttl > 0:
            try:
                cached = self.cache.get(key, self.page_cache_ttl)
                if cached is not None:
                    return cached
            except Exception:
                pass
        page = await self._get(client, url)
        if self.cache and self.page_cache_ttl > 0:
            try:
                self.cache.put(key, page)
            except Exception:
                pass
        return page

    async def _urls(self, client, query):
        found = []
        search_urls = (
            f"https://html.duckduckgo.com/html/?q={quote_plus(query)}",
            f"https://www.bing.com/search?q={quote_plus(query)}&count=30&setlang=uk",
            f"https://search.brave.com/search?q={quote_plus(query)}&source=web",
        )
        pages = await asyncio.gather(
            *(self._get(client, search_url) for search_url in search_urls),
            return_exceptions=True,
        )
        for search_url, page in zip(search_urls, pages):
            if isinstance(page, Exception):
                continue
            for url in self._links(page, search_url):
                if url not in found:
                    found.append(url)
                if len(found) >= self.max_candidates_per_query:
                    return found
        return found

    async def _serper_urls(self, client, query):
        raw = await self.serper.search_urls(
            query,
            client=client,
            blocked_domains=self.blocked_domains,
        )
        found = []
        per_domain = defaultdict(int)
        for url in raw:
            parsed = urlsplit(url)
            host = parsed.netloc.casefold().removeprefix("www.")
            if not host or self._blocked(host) or not parsed.path or parsed.path == "/":
                continue
            if per_domain[host] >= self.max_per_domain:
                continue
            canonical = _canonical(url)
            if canonical not in found:
                found.append(canonical)
                per_domain[host] += 1
            if len(found) >= self.max_candidates_per_query:
                break
        return found

    def _offer(self, mission, url, page, query, method="free-web-search"):
        products = _jsonld_products(page)
        if not products:
            return None
        product = products[0]
        title = _clean(product.get("name"))
        offers = product.get("offers")
        offers = offers[0] if isinstance(offers, list) and offers else offers
        amount = availability = None
        currency = "UAH"
        if isinstance(offers, dict):
            amount = _price(offers.get("price") or offers.get("lowPrice"))
            currency = _currency(offers.get("priceCurrency") or offers.get("currency"))
            availability = _clean(offers.get("availability")) or None
        if not title or amount is None:
            return None
        host = urlsplit(url).netloc.casefold().removeprefix("www.")
        attrs = {"source": "web-shop-jsonld", "source_domain": host, "discovery_stage": method}
        for key in ("sku", "mpn", "gtin", "gtin13", "model"):
            if product.get(key):
                attrs[key] = product[key]
        brand = product.get("brand")
        attrs["brand"] = brand.get("name") if isinstance(brand, dict) else brand
        return Offer(
            article=mission.article,
            marketplace=self.marketplace,
            marketplace_product_id=_clean(product.get("sku")) or None,
            title=title,
            price=amount,
            currency=currency,
            availability=availability,
            url=_canonical(url),
            attributes=attrs,
            query_used=query,
            discovery_method=f"{method}->shop-jsonld",
        )

    async def _fetch_urls(self, client, mission, query, urls, method):
        async def one(url):
            try:
                return self._offer(mission, url, await self._get_product(client, url), query, method)
            except httpx.HTTPError:
                return None

        result = await asyncio.gather(*(one(url) for url in urls))
        return [offer for offer in result if offer]

    async def discover(self, mission, query):
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            offers = await self._fetch_urls(client, mission, query, await self._urls(client, query), "free-web-search")
            if offers:
                return offers
            if self.serper.enabled:
                return await self._fetch_urls(client, mission, query, await self._serper_urls(client, query), "serper")
            return []

    async def scan(self, mission):
        queries = await self.generate_queries(mission)
        unique = {}
        errors = []
        seen = 0
        query_sem = asyncio.Semaphore(self.query_concurrency)

        async with httpx.AsyncClient(
            timeout=self.timeout,
            limits=httpx.Limits(max_connections=30, max_keepalive_connections=15),
        ) as client:
            async def native_batch(query):
                async with query_sem:
                    try:
                        urls = await self._urls(client, query)
                        offers = await self._fetch_urls(client, mission, query, urls, "free-web-search")
                        return query, urls, offers, None
                    except Exception as exc:
                        return query, [], [], exc

            batches = await asyncio.gather(*(native_batch(query) for query in queries))
            for query, urls, offers, exc in batches:
                if exc is not None:
                    errors.append(f"native {query!r}: {exc}")
                    continue
                seen += len(urls)
                for offer in offers:
                    unique.setdefault(str(offer.url), offer)

            validated = [validate_offer(mission, offer) for offer in unique.values()]
            passes = [item for item in validated if item.verdict == Verdict.PASS]

            if not passes and self.serper.enabled:
                async def serper_batch(query):
                    async with query_sem:
                        try:
                            urls = await self._serper_urls(client, query)
                            offers = await self._fetch_urls(client, mission, query, urls, "serper")
                            return query, urls, offers, None
                        except Exception as exc:
                            return query, [], [], exc

                batches = await asyncio.gather(*(serper_batch(query) for query in queries[:2]))
                for query, urls, offers, exc in batches:
                    if exc is not None:
                        errors.append(f"serper {query!r}: {exc}")
                        continue
                    seen += len(urls)
                    for offer in offers:
                        unique.setdefault(str(offer.url), offer)

        validated = [validate_offer(mission, offer) for offer in unique.values()]
        passes = [item for item in validated if item.verdict == Verdict.PASS]
        conflicts = [item for item in validated if item.verdict == Verdict.CONFLICT]
        health = (
            ScanHealth.FOUND if passes and not errors
            else ScanHealth.PARTIAL if passes or conflicts
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
        )
