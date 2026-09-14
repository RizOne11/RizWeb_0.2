import json
import os
import re
import urllib.parse
import requests

PRICE_RE = re.compile(
    r'(?<!\d)(\d{1,3}(?:[\s\u00a0.,]\d{3})+|\d{2,7})(?:[.,]\d{1,2})?\s*(?:грн|₴|uah)',
    re.I,
)


def _price_num(v):
    if v is None:
        return None
    s = re.sub(r"[^0-9.,]", "", str(v)).replace(",", ".")
    if s.count(".") > 1:
        s = s.replace(".", "")
    try:
        return float(s)
    except Exception:
        return None


def _price_from_text(text):
    m = PRICE_RE.search(text or "")
    return _price_num(m.group(1)) if m else None


def _serper_safe_query(query):
    """Normalize queries for Serper free-tier compatibility.

    Free accounts may reject quoted phrases, site: operators and negative quoted
    exclusions. PUMA applies marketplace/domain filtering locally, so these
    operators are not required for correctness.
    """
    q = " ".join(str(query or "").split()).strip()
    q = re.sub(r'(?:^|\s)site:[^\s]+', ' ', q, flags=re.I)
    q = re.sub(r'(?:^|\s)-["“”][^"“”]+["“”]', ' ', q)
    q = re.sub(r'(?:^|\s)-[^\s]+', ' ', q)
    q = q.replace('"', ' ').replace('“', ' ').replace('”', ' ').replace('`', ' ')
    return " ".join(q.split()).strip()


def _canonical_url(url):
    """Normalize tracking noise without collapsing real product selector params."""
    try:
        parsed = urllib.parse.urlsplit(url or "")
        if not parsed.scheme or not parsed.netloc:
            return url or ""
        drop = {"rsltid", "srsltid", "gclid", "fbclid", "ved", "sa", "source"}
        q = []
        for k, v in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True):
            lk = k.lower()
            if lk.startswith("utm_") or lk in drop:
                continue
            q.append((k, v))
        query = urllib.parse.urlencode(q, doseq=True)
        return urllib.parse.urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, query, ""))
    except Exception:
        return url or ""


def _host(url):
    try:
        host = urllib.parse.urlparse(url or "").netloc.lower().split(":")[0]
    except Exception:
        return ""
    return host[4:] if host.startswith("www.") else host


def _market_domain(url, domains):
    host = _host(url)
    for domain in domains:
        d = domain.lower().strip()
        if host == d or host.endswith("." + d):
            return domain
    return None


def _empty_grouped(domains):
    grouped = {d: [] for d in domains}
    grouped["__other__"] = []
    return grouped


def _append_hit(grouped, hit, domains, limit_per_domain=20, other_limit=80):
    url = hit.get("url") or ""
    if not url:
        return
    domain = _market_domain(url, domains)
    key = hit.get("canonical_url") or _canonical_url(url) or url
    if domain:
        current = grouped.setdefault(domain, [])
        if len(current) >= limit_per_domain:
            return
        if any((x.get("canonical_url") or x.get("url")) == key for x in current):
            return
        current.append(hit)
        return

    host = _host(url)
    excluded_other_hosts = {
        "facebook.com", "instagram.com", "youtube.com", "youtu.be",
        "tiktok.com", "pinterest.com", "linkedin.com", "wikipedia.org",
    }
    blocked_host = any(host == x or host.endswith("." + x) for x in excluded_other_hosts)
    # PUMA market scope: Ukraine only. A .ua store can be retained as Other-UA;
    # non-UA domains are ignored here and cannot affect the report.
    if host.endswith(".ua") and not blocked_host:
        current = grouped.setdefault("__other__", [])
        if len(current) >= other_limit:
            return
        if any((x.get("canonical_url") or x.get("url")) == key for x in current):
            return
        hit["host"] = host
        current.append(hit)


def _merge_grouped(dst, src, domains, limit_per_domain=20, other_limit=80):
    for d in domains:
        for hit in src.get(d, []):
            _append_hit(dst, hit, domains, limit_per_domain, other_limit)
    for hit in src.get("__other__", []):
        _append_hit(dst, hit, domains, limit_per_domain, other_limit)
    return dst


class SerperSearch:
    ENDPOINT = "https://google.serper.dev/search"

    def __init__(self, api_key=None, logger=None, gl="ua", hl="uk", num=50, cache=None, cache_ttl=259200):
        self.api_key = api_key or os.getenv("SERPER_API_KEY", "").strip()
        self.log = logger or (lambda msg: None)
        self.gl = gl
        self.hl = hl
        self.num = int(num)
        self.cache = cache
        self.cache_ttl = int(cache_ttl)
        self.api_requests = 0
        self.cache_hits = 0
        self.last_error = ""
        self.disabled_reason = ""

        self.s = requests.Session()
        self.s.headers.update({
            "X-API-KEY": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

    def _extract_identifier(self, query):
        q = " ".join(str(query or "").split()).strip()
        m = re.search(r'["“”]([^"“”]+)["“”]', q)
        if m:
            identifier = m.group(1).strip()
        else:
            identifier = q.split()[0].strip() if q else ""
        return identifier.strip('\'"“”`') or q

    def _cache_key(self, simple_query, domains):
        return "serper:v125:" + simple_query.lower() + ":" + ",".join(sorted(d.lower() for d in domains))

    def _request(self, simple_query, domains):
        if self.disabled_reason:
            return None
        self.last_error = ""
        cache_key = self._cache_key(simple_query, domains)
        if self.cache:
            raw = self.cache.get_search(cache_key, self.cache_ttl)
            if raw:
                try:
                    self.cache_hits += 1
                    self.log(f"SERPER CACHE HIT: {simple_query}")
                    return json.loads(raw)
                except Exception:
                    pass

        payload = {"q": simple_query, "gl": self.gl, "hl": self.hl, "num": self.num}
        self.log(f"SERPER QUERY: {simple_query}")
        try:
            self.api_requests += 1
            r = self.s.post(self.ENDPOINT, json=payload, timeout=35)
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
            self.log(f"SERPER ERROR {self.last_error}")
            return None

        self.log(f"SERPER HTTP {r.status_code} content-type={r.headers.get('content-type','')} len={len(r.content)}")
        if r.status_code == 401:
            raise RuntimeError("Serper rejected the API key (HTTP 401).")
        if r.status_code == 403:
            raise RuntimeError("Serper access forbidden (HTTP 403). Check API key/account.")
        if r.status_code == 429:
            raise RuntimeError("Serper rate limit or credits exhausted (HTTP 429).")
        if r.status_code >= 400:
            body = r.text[:500]
            self.last_error = f"HTTP {r.status_code}: {body}"
            self.log(f"SERPER BODY: {body}")
            if r.status_code == 400 and "query pattern not allowed" in body.lower():
                self.disabled_reason = "FREE_ACCOUNT_QUERY_PATTERN_BLOCK"
                self.log("SERPER CIRCUIT BREAKER: free-account query pattern rejected; disabling Serper for this run")
            return None

        try:
            data = r.json()
        except Exception as e:
            self.last_error = f"JSON {type(e).__name__}: {e}"
            self.log(f"SERPER JSON ERROR {type(e).__name__}: {e}")
            return None

        if self.cache:
            try:
                self.cache.put_search(cache_key, json.dumps(data, ensure_ascii=False))
            except Exception as e:
                self.log(f"SERPER CACHE WRITE ERROR {type(e).__name__}: {e}")
        return data

    def search_all(self, query, domains, limit_per_domain=5, exact_query=False):
        if not self.api_key:
            return _empty_grouped(domains)

        raw_query = " ".join(str(query or "").split()).strip() if exact_query else self._extract_identifier(query)
        simple_query = _serper_safe_query(raw_query)
        if not simple_query:
            return _empty_grouped(domains)
        if simple_query != raw_query:
            self.log(f"SERPER SAFE QUERY: {raw_query!r} -> {simple_query!r}")
        data = self._request(simple_query, domains)
        grouped = _empty_grouped(domains)
        if not data:
            return grouped

        organic = data.get("organic") or []
        shopping = data.get("shopping") or []
        self.log(f"SERPER RESULTS: organic={len(organic)} shopping={len(shopping)}")
        for source, items in (("organic", organic), ("shopping", shopping)):
            for item in items:
                url = item.get("link") or ""
                if not url:
                    continue
                title = item.get("title") or ""
                snippet = item.get("snippet") or item.get("source") or ""
                hit = {
                    "title": title,
                    "url": url,
                    "canonical_url": _canonical_url(url),
                    "snippet": snippet,
                    "position": item.get("position"),
                    "source": source,
                    "price_hint": (
                        _price_num(item.get("price"))
                        or _price_num(item.get("extracted_price"))
                        or _price_from_text(snippet)
                        or _price_from_text(title)
                    ),
                    "search_query": simple_query,
                    "discovery_provider": "serper",
                }
                _append_hit(grouped, hit, domains, limit_per_domain, 80)
        return grouped


class FirecrawlSearch:
    SEARCH_ENDPOINT = "https://api.firecrawl.dev/v2/search"
    SCRAPE_ENDPOINT = "https://api.firecrawl.dev/v2/scrape"

    def __init__(self, api_key=None, logger=None, timeout=45, location="Ukraine", allow_keyless=True):
        self.api_key = api_key or os.getenv("FIRECRAWL_API_KEY", "").strip()
        self.allow_keyless = bool(allow_keyless)
        self.log = logger or (lambda msg: None)
        self.timeout = float(timeout)
        self.location = location
        self.api_requests = 0
        self.last_error = ""
        self.disabled_reason = ""
        self.s = requests.Session()
        self.s.headers.update({"Content-Type": "application/json", "Accept": "application/json"})
        if self.api_key:
            self.s.headers["Authorization"] = f"Bearer {self.api_key}"

    @property
    def enabled(self):
        return not self.disabled_reason and (bool(self.api_key) or self.allow_keyless)

    def _disable_for_auth(self, status_code, body):
        text = str(body or "")
        if status_code in (401, 403):
            if not self.api_key:
                self.disabled_reason = "API_KEY_REQUIRED_FROM_RENDER"
            else:
                self.disabled_reason = "API_KEY_REJECTED"
            self.log(f"FIRECRAWL CIRCUIT BREAKER: {self.disabled_reason}; disabling Firecrawl for this run")

    def search(self, query, domains=None, limit=20):
        if not self.enabled:
            return []
        payload = {
            "query": " ".join(str(query or "").split()).strip(),
            "limit": max(1, min(int(limit), 100)),
            "sources": [{"type": "web"}],
            "location": self.location,
        }
        if domains:
            payload["includeDomains"] = list(domains)
        self.log(f"FIRECRAWL SEARCH: q={payload['query']!r} domains={domains or 'UA web'}")
        try:
            self.api_requests += 1
            r = self.s.post(self.SEARCH_ENDPOINT, json=payload, timeout=self.timeout)
            self.log(f"FIRECRAWL SEARCH HTTP {r.status_code} len={len(r.content)}")
            if r.status_code >= 400:
                self.last_error = f"HTTP {r.status_code}: {r.text[:400]}"
                self.log(f"FIRECRAWL SEARCH ERROR: {self.last_error}")
                self._disable_for_auth(r.status_code, r.text[:400])
                return []
            data = r.json()
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
            self.log(f"FIRECRAWL SEARCH ERROR: {self.last_error}")
            return []

        body = data.get("data") or {}
        web = body.get("web") if isinstance(body, dict) else None
        if web is None and isinstance(body, list):
            web = body
        return web or []

    def _group_results(self, results, domains, query, limit_per_domain=20, other_limit=80):
        grouped = _empty_grouped(domains)
        for item in results:
            url = item.get("url") or item.get("link") or ""
            if not url:
                continue
            title = item.get("title") or ""
            desc = item.get("description") or item.get("snippet") or ""
            metadata = item.get("metadata") or {}
            meta_text = " ".join(str(metadata.get(k) or "") for k in (
                "title", "description", "og:title", "og:description"
            ))
            hit = {
                "title": title,
                "url": url,
                "canonical_url": _canonical_url(metadata.get("url") or metadata.get("og:url") or url),
                "snippet": desc,
                "position": item.get("position"),
                "source": "web",
                "price_hint": _price_from_text(" ".join([title, desc, meta_text])),
                "search_query": query,
                "discovery_provider": "firecrawl",
            }
            _append_hit(grouped, hit, domains, limit_per_domain, other_limit)
        return grouped

    def search_all(self, query, domains, limit_per_domain=20, other_limit=80):
        # Explicit-domain mode: used for Tier-1 marketplace discovery/recovery.
        results = self.search(query, domains=domains or None, limit=max(limit_per_domain * max(1, len(domains)), 10))
        return self._group_results(results, domains, query, limit_per_domain, other_limit)

    def search_ukraine_web(self, query, domains, limit=40, limit_per_domain=20, other_limit=80):
        # No domain filter here: discover independent Ukrainian shops as well as
        # marketplaces, then retain only target domains and .ua stores.
        results = self.search(query, domains=None, limit=limit)
        return self._group_results(results, domains, query, limit_per_domain, other_limit)

    def scrape_product(self, url):
        """Structured, live-ish page verification used only as a fallback.

        This deliberately asks for the current full product price and availability,
        excluding installment/monthly values and recommendation widgets.
        """
        if not self.enabled:
            return None
        schema = {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "current_full_product_price_uah": {"type": ["number", "null"]},
                "seller": {"type": ["string", "null"]},
                "brand": {"type": ["string", "null"]},
                "model_mpn": {"type": ["string", "null"]},
                "seller_product_code_or_sku": {"type": ["string", "null"]},
                "refresh_rate_hz": {"type": ["number", "null"]},
                "resolution": {"type": ["string", "null"]},
                "color": {"type": ["string", "null"]},
                "availability": {"type": ["string", "null"]},
                "canonical_url": {"type": ["string", "null"]},
            },
        }
        prompt = (
            "Extract ONLY the main product shown on this product page. Return the current full one-time price in UAH, "
            "not installment/monthly payments, old price, recommended products, accessories or ads. Also extract seller, "
            "brand, exact model/MPN, SKU if visible, refresh rate, resolution, color, availability and canonical URL."
        )
        payload = {
            "url": url,
            "formats": [{"type": "json", "prompt": prompt, "schema": schema}],
            "onlyMainContent": True,
            "location": {"country": "UA", "languages": ["uk", "ru"]},
            "maxAge": 0,
        }
        self.log(f"FIRECRAWL VERIFY: {url[:140]}")
        try:
            self.api_requests += 1
            r = self.s.post(self.SCRAPE_ENDPOINT, json=payload, timeout=max(self.timeout, 60))
            self.log(f"FIRECRAWL VERIFY HTTP {r.status_code} len={len(r.content)}")
            if r.status_code >= 400:
                self.log(f"FIRECRAWL VERIFY ERROR: {r.text[:400]}")
                self._disable_for_auth(r.status_code, r.text[:400])
                return None
            data = r.json().get("data") or {}
            obj = data.get("json") if isinstance(data, dict) else None
            if not isinstance(obj, dict):
                return None
            return {
                "title": obj.get("title") or "",
                "description": " ".join(str(obj.get(x) or "") for x in (
                    "brand", "model_mpn", "seller_product_code_or_sku", "refresh_rate_hz",
                    "resolution", "color", "availability"
                )),
                "price": _price_num(obj.get("current_full_product_price_uah")),
                "availability": obj.get("availability") or "",
                "seller": obj.get("seller") or "",
                "sku": obj.get("seller_product_code_or_sku") or "",
                "url": obj.get("canonical_url") or url,
                "canonical_url": _canonical_url(obj.get("canonical_url") or url),
                "extract_source": "firecrawl_json",
            }
        except Exception as e:
            self.log(f"FIRECRAWL VERIFY ERROR {type(e).__name__}: {e}")
            return None


class ExaSearch:
    ENDPOINT = "https://api.exa.ai/search"

    def __init__(self, api_key=None, logger=None, timeout=35):
        self.api_key = api_key or os.getenv("EXA_API_KEY", "").strip()
        self.log = logger or (lambda msg: None)
        self.timeout = float(timeout)
        self.api_requests = 0
        self.s = requests.Session()
        if self.api_key:
            self.s.headers.update({"x-api-key": self.api_key, "Content-Type": "application/json"})

    @property
    def enabled(self):
        return bool(self.api_key)

    def _search_raw(self, query, include_domains=None, num_results=20):
        if not self.enabled:
            return []
        payload = {
            "query": query,
            "type": "auto",
            "numResults": min(100, max(1, int(num_results))),
            "contents": {"highlights": True},
        }
        if include_domains:
            payload["includeDomains"] = list(include_domains)
        self.log(f"EXA SEARCH: q={query!r} domains={include_domains or 'UA web'}")
        try:
            self.api_requests += 1
            r = self.s.post(self.ENDPOINT, json=payload, timeout=self.timeout)
            self.log(f"EXA HTTP {r.status_code} len={len(r.content)}")
            if r.status_code >= 400:
                self.log(f"EXA ERROR: {r.text[:400]}")
                return []
            return (r.json() or {}).get("results") or []
        except Exception as e:
            self.log(f"EXA ERROR {type(e).__name__}: {e}")
            return []

    def _group_results(self, results, domains, query, limit_per_domain=20, other_limit=80):
        grouped = _empty_grouped(domains)
        for item in results:
            url = item.get("url") or ""
            text = " ".join(item.get("highlights") or [])
            hit = {
                "title": item.get("title") or "",
                "url": url,
                "canonical_url": _canonical_url(url),
                "snippet": text,
                "source": "exa",
                "price_hint": _price_from_text(text),
                "search_query": query,
                "discovery_provider": "exa",
            }
            _append_hit(grouped, hit, domains, limit_per_domain, other_limit)
        return grouped

    def search_all(self, query, domains, limit_per_domain=20, other_limit=80):
        results = self._search_raw(query, include_domains=domains or None,
                                   num_results=max(10, limit_per_domain * max(1, len(domains))))
        return self._group_results(results, domains, query, limit_per_domain, other_limit)

    def search_ukraine_web(self, query, domains, limit=30, limit_per_domain=20, other_limit=80):
        results = self._search_raw(query, include_domains=None, num_results=limit)
        return self._group_results(results, domains, query, limit_per_domain, other_limit)


class HybridSearch:
    """PUMA v1.2.5.1 discovery orchestrator.

    Targeted marketplace queries: Firecrawl native domain filter first, then Exa,
    then Serper only as a fallback. Broad Ukraine discovery: Firecrawl + Serper +
    Exa are merged. Existing runner can keep using search_all(), but the provider
    no longer depends on Serper's unsupported free-account site: query pattern.
    """

    SITE_RE = re.compile(r"(?:^|\s)site:([^\s]+)", re.I)

    def __init__(self, logger=None, gl="ua", hl="uk", num=50, cache=None, cache_ttl=259200,
                 firecrawl_enabled=True, exa_enabled=True, serper_enabled=True,
                 timeout=45, other_limit=80, recovery_min_hits=2, firecrawl_keyless=True):
        self.log = logger or (lambda msg: None)
        self.other_limit = int(other_limit)
        self.recovery_min_hits = max(0, int(recovery_min_hits))
        self.serper = SerperSearch(logger=self.log, gl=gl, hl=hl, num=num, cache=cache, cache_ttl=cache_ttl)
        self.firecrawl = FirecrawlSearch(logger=self.log, timeout=timeout, allow_keyless=firecrawl_keyless) if firecrawl_enabled else FirecrawlSearch(api_key="", logger=self.log, allow_keyless=False)
        self.exa = ExaSearch(logger=self.log, timeout=timeout) if exa_enabled else ExaSearch(api_key="", logger=self.log)
        self.serper_enabled = bool(serper_enabled)

    @property
    def api_requests(self):
        return self.serper.api_requests + self.firecrawl.api_requests + self.exa.api_requests

    @property
    def cache_hits(self):
        return self.serper.cache_hits

    def _strip_site(self, query):
        m = self.SITE_RE.search(query or "")
        domain = m.group(1).strip() if m else ""
        clean = self.SITE_RE.sub(" ", query or "")
        clean = " ".join(clean.split()).strip()
        return clean, domain

    def search_all(self, query, domains, limit_per_domain=20, exact_query=False):
        clean_query, site_domain = self._strip_site(query)
        target_domains = [site_domain] if site_domain else list(domains)
        target_domains = [d for d in target_domains if d]
        grouped = _empty_grouped(domains)

        # 1) Firecrawl is primary for marketplace discovery. Recovery providers
        # are called only when the primary channel did not produce enough
        # candidates. This protects API budgets without sacrificing coverage.
        if self.firecrawl.enabled:
            if site_domain:
                fc = self.firecrawl.search_all(clean_query, target_domains, limit_per_domain, self.other_limit)
            else:
                fc = self.firecrawl.search_ukraine_web(
                    clean_query, domains, limit=max(20, min(60, limit_per_domain * 3)),
                    limit_per_domain=limit_per_domain, other_limit=self.other_limit
                )
            _merge_grouped(grouped, fc, domains, limit_per_domain, self.other_limit)

        def candidate_count():
            return sum(len(grouped.get(d, [])) for d in domains) + len(grouped.get("__other__", []))

        # 2) Exa is an independent recovery channel.
        if self.exa.enabled and candidate_count() < self.recovery_min_hits:
            if site_domain:
                ex = self.exa.search_all(clean_query, target_domains, limit_per_domain, self.other_limit)
            else:
                ex = self.exa.search_ukraine_web(
                    clean_query, domains, limit=max(20, min(50, limit_per_domain * 2)),
                    limit_per_domain=limit_per_domain, other_limit=self.other_limit
                )
            _merge_grouped(grouped, ex, domains, limit_per_domain, self.other_limit)

        # 3) Serper is final recovery only. Never send site: on free accounts;
        # target-domain filtering happens locally.
        if self.serper_enabled and self.serper.api_key and candidate_count() < self.recovery_min_hits:
            sp = self.serper.search_all(clean_query, target_domains, limit_per_domain, exact_query=True)
            _merge_grouped(grouped, sp, domains, limit_per_domain, self.other_limit)

        self.log(
            "HYBRID SEARCH RESULT: " + " | ".join(f"{d}={len(grouped.get(d, []))}" for d in domains)
            + f" | other_ua={len(grouped.get('__other__', []))}"
        )
        return grouped

    def verify_page(self, url):
        return self.firecrawl.scrape_product(url) if self.firecrawl.enabled else None
