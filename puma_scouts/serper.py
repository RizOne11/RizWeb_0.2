from __future__ import annotations

import os
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit

import httpx


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


def extract_serper_links(
    payload: dict[str, Any],
    *,
    allowed_host: str | None = None,
    blocked_domains: Iterable[str] = (),
    max_results: int = 10,
) -> list[str]:
    """Extract candidate product-page URLs from Serper response only.

    This function does not score, validate, or price products. It only returns
    candidate URLs for the existing PUMA extract/validator pipeline.
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
    """Optional URL discovery layer backed by Serper/Google Search.

    It is intentionally discovery-only: callers provide an already sanitized
    article-free query, and the returned URLs still pass through PUMA's normal
    extraction, identity matching, contamination checks and price integrity.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        max_results: int | None = None,
        country: str = "ua",
        language: str = "uk",
        timeout: float = 10.0,
    ) -> None:
        self.api_key = (api_key if api_key is not None else os.getenv("SERPER_API_KEY", "")).strip()
        self.max_results = max(1, min(int(max_results or os.getenv("PUMA_SERPER_MAX_RESULTS", "10")), 20))
        self.country = country
        self.language = language
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        flag = os.getenv("PUMA_SERPER_ENABLED", "auto").strip().casefold()
        if flag in {"0", "false", "off", "no"}:
            return False
        return bool(self.api_key)

    async def search_urls(
        self,
        query: str,
        *,
        client: Any | None = None,
        site: str | None = None,
        blocked_domains: Iterable[str] = (),
    ) -> list[str]:
        query = str(query or "").strip()
        if not self.enabled or not query:
            return []

        search_query = f"site:{site} {query}" if site else query
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
            response = await client.post(SERPER_ENDPOINT, headers=headers, json=body)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                return []
            return extract_serper_links(
                payload,
                allowed_host=site,
                blocked_domains=blocked_domains,
                max_results=self.max_results,
            )
        except (httpx.HTTPError, ValueError, TypeError, RuntimeError):
            return []
        finally:
            if owns_client:
                await client.aclose()
