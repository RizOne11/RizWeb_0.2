from __future__ import annotations

import asyncio
import re
from decimal import Decimal
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from puma_scouts.models import Marketplace, Offer, ProductMission
from puma_scouts.query import article_is_published, extract_identifiers, generate_queries
from puma_scouts.scouts.catalog import CatalogScout, _canonical, _clean, _currency, _price


class RozetkaSerperScout(CatalogScout):
    """Rozetka lab using the strongest PUMA 2.0 ideas on top of current PUMA.

    Discovery intentionally avoids Rozetka native search. Serper receives a safe
    operator-free identity query; returned results are filtered to Rozetka locally.
    Product identity, validator rules, Identity Map, FAST REFRESH and REPAIR remain
    the current PUMA implementation.
    """

    marketplace = Marketplace.ROZETKA
    host = "rozetka.com.ua"
    allow_subdomains = True
    product_path_hints = ()
    search_templates = ()

    def __init__(self, *, timeout=15, max_candidates_per_query=20):
        super().__init__(timeout=timeout, max_candidates_per_query=max_candidates_per_query)
        self._serper_hit_meta: dict[str, dict] = {}

    def _is_candidate(self, url: str) -> bool:
        parsed = urlsplit(str(url or ""))
        if not self._host_matches(parsed.netloc):
            return False
        return bool(re.search(r"/p\d+(?:/|$)", parsed.path, re.I))

    async def generate_queries(self, mission: ProductMission) -> list[str]:
        """Quality-first matrix inspired by the old priceintel engine.

        Supplier row article remains excluded unless it is explicitly published in
        the source identity, preserving the current PUMA false-positive safeguards.
        """
        data = {str(k).casefold(): str(v or "").strip() for k, v in (mission.source_data or {}).items()}
        brand = next((data.get(k) for k in ("brand", "vendor", "бренд", "виробник") if data.get(k)), "")
        name = next((data.get(k) for k in ("name", "title", "назва", "название") if data.get(k)), "")
        identifiers = extract_identifiers(mission)

        def strength(value: str):
            compact = re.sub(r"[^0-9a-zа-яіїєґ]+", "", value.casefold(), flags=re.I)
            mixed = bool(re.search(r"[a-zа-яіїєґ]", compact, re.I) and re.search(r"\d", compact))
            return (1 if mixed else 0, 1 if "-" in value else 0, len(compact))

        identifiers = sorted(dict.fromkeys(identifiers), key=strength, reverse=True)
        out: list[str] = []

        def add(value: str):
            value = " ".join(str(value or "").split()).strip()
            if value and value.casefold() not in {q.casefold() for q in out}:
                out.append(value)

        # Strong public model/MPN first: CatalogScout only spends the first two
        # queries on paid fallback, so ordering is material.
        if identifiers:
            add(identifiers[0])
            if brand:
                add(f"{brand} {identifiers[0]}")

        # Published supplier code is allowed only when it is visibly part of the
        # public product identity; opaque internal supplier IDs stay excluded.
        if article_is_published(mission):
            add(mission.article)

        # Human-readable family/title fallbacks.
        clean_name = re.sub(r"\([^)]{0,80}\)|\[[^]]{0,80}\]", " ", name)
        clean_name = " ".join(clean_name.split())
        if brand and clean_name:
            words = clean_name.split()[:7]
            if brand.casefold() not in {w.casefold() for w in words}:
                words.insert(0, brand)
            add(" ".join(words))
        add(clean_name)

        # Secondary identifiers and bilingual variants from the current engine.
        for identifier in identifiers[1:3]:
            add(identifier)
            if brand:
                add(f"{brand} {identifier}")
        for query in generate_queries(mission):
            add(query)

        return out[:8]

    async def _native_candidate_urls(self, client, query):
        return []

    async def _external_candidate_urls(self, client, query):
        return []

    async def _serper_candidate_urls(self, client, query):
        # Critical PUMA 2.0 lesson: do NOT send site:rozetka.com.ua to Serper.
        # Search normally, then filter to Rozetka locally.
        hits = await self.serper.search_hits(
            query,
            client=client,
            allowed_host=self.host,
            use_site_operator=False,
        )
        urls = []
        for hit in hits:
            url = str(hit.get("url") or "")
            if not self._is_candidate(url):
                continue
            canonical = _canonical(url)
            self._serper_hit_meta[canonical] = dict(hit)
            if canonical not in urls:
                urls.append(canonical)
            if len(urls) >= self.max_candidates_per_query:
                break
        return urls

    @staticmethod
    def _meta_content(soup: BeautifulSoup, *selectors: tuple[str, str]) -> str:
        for attr, value in selectors:
            tag = soup.find("meta", attrs={attr: value})
            if tag and tag.get("content"):
                return str(tag.get("content")).strip()
        return ""

    def _html_fallback_offer(self, mission: ProductMission, url: str, page: str, query: str, method: str):
        soup = BeautifulSoup(page, "html.parser")
        title = (
            self._meta_content(soup, ("property", "og:title"), ("name", "twitter:title"))
            or _clean(soup.find("h1").get_text(" ", strip=True) if soup.find("h1") else "")
        )
        price_value = self._meta_content(
            soup,
            ("property", "product:price:amount"),
            ("itemprop", "price"),
        )
        if not price_value:
            price_tag = soup.find(attrs={"itemprop": "price"})
            if price_tag:
                price_value = str(price_tag.get("content") or price_tag.get_text(" ", strip=True) or "")
        price = _price(price_value)
        if not title:
            return None

        product_id = None
        match = re.search(r"/p(\d+)(?:/|$)", url, re.I)
        if match:
            product_id = match.group(1)

        return Offer(
            article=mission.article,
            marketplace=self.marketplace,
            marketplace_product_id=product_id,
            title=title,
            price=price,
            currency="UAH",
            availability=None,
            url=_canonical(url),
            attributes={"source": "rozetka-html-meta", "discovery_stage": method},
            query_used=query,
            discovery_method=f"rozetka-{method}->html-meta",
        )

    def _offer(self, mission: ProductMission, url: str, page: str, query: str, method: str):
        parsed = super()._offer(mission, url, page, query, method)
        if parsed is not None and parsed.price is not None:
            return parsed

        fallback = self._html_fallback_offer(mission, url, page, query, method)
        if fallback is None:
            return parsed
        if parsed is not None:
            if parsed.price is None:
                parsed.price = fallback.price
            if not parsed.marketplace_product_id:
                parsed.marketplace_product_id = fallback.marketplace_product_id
            parsed.attributes["rozetka_html_meta_fallback"] = True
            return parsed
        return fallback

    def _serper_fallback_offer(self, mission: ProductMission, url: str, query: str):
        hit = self._serper_hit_meta.get(_canonical(url)) or {}
        title = _clean(hit.get("title"))
        price_hint = hit.get("price_hint")
        if not title or price_hint in (None, ""):
            return None
        try:
            price = Decimal(str(price_hint))
        except Exception:
            return None
        if price <= 0:
            return None

        match = re.search(r"/p(\d+)(?:/|$)", url, re.I)
        product_id = match.group(1) if match else None
        return Offer(
            article=mission.article,
            marketplace=self.marketplace,
            marketplace_product_id=product_id,
            title=title,
            price=price,
            currency="UAH",
            availability=None,
            url=_canonical(url),
            attributes={
                "source": "serper-rozetka-fallback",
                "discovery_stage": "serper",
                "serper_snippet": _clean(hit.get("snippet")),
                "serper_result_source": _clean(hit.get("source")),
            },
            query_used=query,
            discovery_method="serper->rozetka-local-filter->snippet-price",
        )

    async def _fetch_offers(self, client, mission, query, urls, method):
        async def one(url):
            parsed = None
            try:
                page = await self._get_product(client, url)
                parsed = self._offer(mission, url, page, query, method)
            except Exception:
                parsed = None

            # Current page parsing remains preferred. Serper metadata is only a
            # fallback when Rozetka blocks/direct HTML extraction fails.
            if parsed is not None and parsed.price is not None:
                return parsed
            if method == "serper":
                return self._serper_fallback_offer(mission, url, query) or parsed
            return parsed

        result = await asyncio.gather(*(one(url) for url in urls))
        return [offer for offer in result if offer]
