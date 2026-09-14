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

        self.s = requests.Session()
        self.s.headers.update({
            "X-API-KEY": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

    def _market_domain(self, url, domains):
        try:
            host = urllib.parse.urlparse(url).netloc.lower().split(":")[0]
        except Exception:
            return None
        if host.startswith("www."):
            host = host[4:]
        for domain in domains:
            d = domain.lower().strip()
            if host == d or host.endswith("." + d):
                return domain
        return None

    def _extract_identifier(self, query):
        q = " ".join(str(query or "").split()).strip()
        m = re.search(r'["“”]([^"“”]+)["“”]', q)
        if m:
            identifier = m.group(1).strip()
        else:
            identifier = q.split()[0].strip() if q else ""
        return identifier.strip('\'"“”`') or q

    def _cache_key(self, simple_query, domains):
        return "serper:v061:" + simple_query.lower() + ":" + ",".join(sorted(d.lower() for d in domains))

    def _request(self, simple_query, domains):
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
            self.log(f"SERPER ERROR {type(e).__name__}: {e}")
            return None

        self.log(f"SERPER HTTP {r.status_code} content-type={r.headers.get('content-type','')} len={len(r.content)}")
        if r.status_code == 401:
            raise RuntimeError("Serper rejected the API key (HTTP 401).")
        if r.status_code == 403:
            raise RuntimeError("Serper access forbidden (HTTP 403). Check API key/account.")
        if r.status_code == 429:
            raise RuntimeError("Serper rate limit or credits exhausted (HTTP 429).")
        if r.status_code >= 400:
            self.log(f"SERPER BODY: {r.text[:500]}")
            return None

        try:
            data = r.json()
        except Exception as e:
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
            raise RuntimeError("SERPER_API_KEY is not configured. Add it in Render -> Environment.")

        simple_query = " ".join(str(query or "").split()).strip() if exact_query else self._extract_identifier(query)
        data = self._request(simple_query, domains)
        if not data:
            return {d: [] for d in domains}

        organic = data.get("organic") or []
        shopping = data.get("shopping") or []
        self.log(f"SERPER RESULTS: organic={len(organic)} shopping={len(shopping)}")

        grouped = {d: [] for d in domains}
        seen = set()

        for source, items in (("organic", organic), ("shopping", shopping)):
            for item in items:
                url = item.get("link") or ""
                domain = self._market_domain(url, domains)
                if not domain or not url or url in seen:
                    continue
                if len(grouped[domain]) >= limit_per_domain:
                    continue

                title = item.get("title") or ""
                snippet = item.get("snippet") or item.get("source") or ""
                price_hint = (
                    _price_num(item.get("price"))
                    or _price_num(item.get("extracted_price"))
                    or _price_from_text(snippet)
                    or _price_from_text(title)
                )

                seen.add(url)
                grouped[domain].append({
                    "title": title,
                    "url": url,
                    "snippet": snippet,
                    "position": item.get("position"),
                    "source": source,
                    "price_hint": price_hint,
                })

        total_selected = sum(len(v) for v in grouped.values())
        self.log(f"SERPER MARKETPLACE HITS TOTAL: {total_selected}")
        for domain in domains:
            self.log(f"SERPER {domain}: {len(grouped[domain])} hit(s)")

        if organic and total_selected == 0:
            sample_hosts = []
            for item in organic[:10]:
                try:
                    host = urllib.parse.urlparse(item.get("link") or "").netloc.lower()
                except Exception:
                    host = ""
                if host and host not in sample_hosts:
                    sample_hosts.append(host)
            self.log(f"SERPER NON-TARGET HOSTS SAMPLE: {sample_hosts[:8]}")

        return grouped
