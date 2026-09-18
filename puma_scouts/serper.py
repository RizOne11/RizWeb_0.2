from __future__ import annotations

import json
import os
import re
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit

import httpx

from puma_scouts.runtime_cache import runtime_cache, serper_cache_seconds


SERPER_ENDPOINT = "https://google.serper.dev/search"


def _canonical_url(value: str) -> str | None:
    try:
        parsed = urlsplit(str(value or "").strip())
    except ValueError:
        return None
    host = parsed.netloc.casefold().removeprefix("www.")
    if parsed.scheme not in {"http", "https"} or not host or not parsed.path or parsed.path == "/":
        return None
    return urlunsplit(("https", parsed.netloc.casefold(), parsed.path, "", ""))


def _host_matches(candidate_host: str, expected_host: str) -> bool:
    candidate = candidate_host.casefold().removeprefix("www.")
    expected = expected_host.casefold().removeprefix("www.")
    return candidate == expected or candidate.endswith("." + expected)


def _blocked(candidate_host: str, blocked_domains: Iterable[str]) -> bool:
    host = candidate_host.casefold().removeprefix("www.")
    for domain in blocked_domains:
        expected = str(domain or "").casefold().removeprefix("www.")
        if expected and (host == expected or host.endswith("." + expected)):
            return True
    return False



def _serper_safe_query(query: str) -> str:
    """Normalize paid-search queries for free-tier compatibility.

    Older PUMA 2.0 learned that quoted phrases, site: operators and negative
    exclusions can be rejected on some Serper accounts. Marketplace filtering can
    be done locally after the search response, so those operators are optional.
    """
    q = " ".join(str(query or "").split()).strip()
    q = re.sub(r'(?:^|\s)site:[^\s]+', ' ', q, flags=re.I)
    q = re.sub(r'(?:^|\s)-["“”][^"“”]+["“”]', ' ', q)
    q = re.sub(r'(?:^|\s)-[^\s]+', ' ', q)
    q = q.replace('"', ' ').replace('“', ' ').replace('”', ' ').replace(chr(96), ' ')
    return " ".join(q.split()).strip()


def _price_num(value: Any) -> float | None:
    text = str(value or "").replace("\u00a0", " ").replace(",", ".")
    match = re.search(r"(?<!\d)(\d{1,3}(?:[ .]\d{3})+|\d{2,8})(?:\.\d{1,2})?", text)
    if not match:
        return None
    try:
        number = float(re.sub(r"[ .]", "", match.group(0)))
    except ValueError:
        return None
    return number if number > 0 else None


def _price_from_text(value: Any) -> float | None:
    text = str(value or "")
    patterns = (
        r"(\d[\d\s\u00a0.,]{1,14})\s*(?:грн|₴|UAH)\b",
        r"(?:грн|₴|UAH)\s*(\d[\d\s\u00a0.,]{1,14})",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            price = _price_num(match.group(1))
            if price:
                return price
    return None


def extract_serper_links(
    payload: dict[str, Any],
    *,
    allowed_host: str | None = None,
    blocked_domains: Iterable[str] = (),
    max_results: int = 10,
) -> list[str]:
    """Extract candidate product-page URLs from Serper response only.

    Serper remains discovery-only. Every returned page still goes through the
    normal PUMA extractor, validator, category rules and price-integrity gates.
    """
    found: list[str] = []
    seen: set[str] = set()
    sections = []
    for key in ("organic", "shopping"):
        value = payload.get(key)
        if isinstance(value, list):
            sections.extend(value)

    for item in sections:
        if not isinstance(item, dict):
            continue
        url = _canonical_url(item.get("link") or "")
        if not url:
            continue
        host = urlsplit(url).netloc.casefold().removeprefix("www.")
        if allowed_host and not _host_matches(host, allowed_host):
            continue
        if _blocked(host, blocked_domains):
            continue
        if url in seen:
            continue
        seen.add(url)
        found.append(url)
        if len(found) >= max(1, int(max_results)):
            break
    return found


class SerperDiscovery:
    """Optional URL discovery backed by Serper/Google Search.

    The expensive part is cached by sanitized query+site. Candidate filtering is
    applied after the cached raw response, so different scouts can safely reuse
    one discovery response without weakening validation.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        max_results: int | None = None,
        country: str = "ua",
        language: str = "uk",
        timeout: float = 10.0,
        cache: Any | None = None,
        cache_ttl: int | None = None,
    ) -> None:
        self.api_key = (api_key if api_key is not None else os.getenv("SERPER_API_KEY", "")).strip()
        self.max_results = max(1, min(int(max_results or os.getenv("PUMA_SERPER_MAX_RESULTS", "10")), 50))
        self.country = country
        self.language = language
        self.timeout = timeout
        self.cache = runtime_cache() if cache is None else cache
        self.cache_ttl = serper_cache_seconds() if cache_ttl is None else max(0, int(cache_ttl))
        self.api_requests = 0
        self.cache_hits = 0
        self.disabled_reason = ""

    @property
    def enabled(self) -> bool:
        flag = os.getenv("PUMA_SERPER_ENABLED", "auto").strip().casefold()
        if flag in {"0", "false", "off", "no"}:
            return False
        return bool(self.api_key) and not self.disabled_reason

    def _cache_key(self, search_query: str) -> str:
        return (
            "puma-serper-v2:"
            + "|".join(
                [
                    self.country.casefold(),
                    self.language.casefold(),
                    str(self.max_results),
                    search_query.casefold(),
                ]
            )
        )

    def _load_cached(self, key: str) -> dict[str, Any] | None:
        if not self.cache or self.cache_ttl <= 0:
            return None
        try:
            raw = self.cache.get_search(key, self.cache_ttl)
            if not raw:
                return None
            payload = json.loads(raw)
            if isinstance(payload, dict):
                self.cache_hits += 1
                return payload
        except Exception:
            return None
        return None

    def _save_cached(self, key: str, payload: dict[str, Any]) -> None:
        if not self.cache or self.cache_ttl <= 0:
            return
        try:
            self.cache.put_search(key, json.dumps(payload, ensure_ascii=False))
        except Exception:
            pass

    async def search_hits(
        self,
        query: str,
        *,
        client: Any | None = None,
        site: str | None = None,
        allowed_host: str | None = None,
        blocked_domains: Iterable[str] = (),
        use_site_operator: bool = True,
    ) -> list[dict[str, Any]]:
        """Return Serper result metadata while optionally filtering a host locally."""
        query = _serper_safe_query(query)
        if not self.enabled or not query:
            return []

        search_query = f"site:{site} {query}" if (site and use_site_operator) else query
        cache_key = self._cache_key(search_query)
        payload = self._load_cached(cache_key)

        owns_client = False
        if payload is None:
            body = {
                "q": search_query,
                "gl": self.country,
                "hl": self.language,
                "num": self.max_results,
            }
            headers = {
                "X-API-KEY": self.api_key,
                "Content-Type": "application/json",
            }

            owns_client = client is None
            if owns_client:
                client = httpx.AsyncClient(timeout=self.timeout)
            try:
                self.api_requests += 1
                response = await client.post(SERPER_ENDPOINT, headers=headers, json=body)
                status = int(getattr(response, "status_code", 0) or 0)
                if status in {401, 403, 429}:
                    self.disabled_reason = f"http_{status}"
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    return []
                self._save_cached(cache_key, payload)
            except (httpx.HTTPError, ValueError, TypeError, RuntimeError):
                return []
            finally:
                if owns_client:
                    await client.aclose()

        filter_host = allowed_host or site
        hits: list[dict[str, Any]] = []
        seen: set[str] = set()
        for source in ("organic", "shopping"):
            items = payload.get(source)
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                url = _canonical_url(item.get("link") or "")
                if not url:
                    continue
                host = urlsplit(url).netloc.casefold().removeprefix("www.")
                if filter_host and not _host_matches(host, filter_host):
                    continue
                if _blocked(host, blocked_domains) or url in seen:
                    continue
                seen.add(url)
                title = str(item.get("title") or "")
                snippet = str(item.get("snippet") or item.get("source") or "")
                price_hint = (
                    _price_num(item.get("price"))
                    or _price_num(item.get("extracted_price"))
                    or _price_from_text(snippet)
                    or _price_from_text(title)
                )
                hits.append({
                    "url": url,
                    "title": title,
                    "snippet": snippet,
                    "position": item.get("position"),
                    "source": source,
                    "price_hint": price_hint,
                    "search_query": search_query,
                })
                if len(hits) >= self.max_results:
                    return hits
        return hits

    async def search_urls(
        self,
        query: str,
        *,
        client: Any | None = None,
        site: str | None = None,
        allowed_host: str | None = None,
        blocked_domains: Iterable[str] = (),
        use_site_operator: bool = True,
    ) -> list[str]:
        hits = await self.search_hits(
            query,
            client=client,
            site=site,
            allowed_host=allowed_host,
            blocked_domains=blocked_domains,
            use_site_operator=use_site_operator,
        )
        return [str(hit.get("url") or "") for hit in hits if hit.get("url")]

