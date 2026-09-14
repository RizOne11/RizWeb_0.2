import os
import urllib.parse
import requests


class SerperSearch:
    """
    One Serper / Google query per product.
    Returns organic URLs and groups them by marketplace domain locally.
    """
    ENDPOINT = "https://google.serper.dev/search"

    def __init__(self, api_key=None, logger=None, gl="ua", hl="uk", num=50):
        self.api_key = api_key or os.getenv("SERPER_API_KEY", "").strip()
        self.log = logger or (lambda msg: None)
        self.gl = gl
        self.hl = hl
        self.num = int(num)
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
        host = host[4:] if host.startswith("www.") else host
        for domain in domains:
            d = domain.lower()
            if host == d or host.endswith("." + d):
                return domain
        return None

    def search_all(self, query, domains, limit_per_domain=5):
        if not self.api_key:
            raise RuntimeError(
                "SERPER_API_KEY is not configured. Add it in Render -> Environment."
            )

        site_clause = " OR ".join(f"site:{d}" for d in domains)
        full_query = f"{query} ({site_clause})"
        payload = {
            "q": full_query,
            "gl": self.gl,
            "hl": self.hl,
            "num": self.num,
        }

        self.log(f"SERPER QUERY: {full_query}")
        try:
            r = self.s.post(self.ENDPOINT, json=payload, timeout=35)
        except Exception as e:
            self.log(f"SERPER ERROR {type(e).__name__}: {e}")
            return {d: [] for d in domains}

        self.log(
            f"SERPER HTTP {r.status_code} "
            f"content-type={r.headers.get('content-type','')} len={len(r.content)}"
        )

        if r.status_code == 401:
            raise RuntimeError("Serper rejected the API key (HTTP 401).")
        if r.status_code == 403:
            raise RuntimeError("Serper access forbidden (HTTP 403). Check API key/account.")
        if r.status_code == 429:
            raise RuntimeError("Serper rate limit or credits exhausted (HTTP 429).")
        if r.status_code >= 400:
            self.log(f"SERPER BODY: {r.text[:500]}")
            return {d: [] for d in domains}

        try:
            data = r.json()
        except Exception as e:
            self.log(f"SERPER JSON ERROR {type(e).__name__}: {e}")
            return {d: [] for d in domains}

        organic = data.get("organic") or []
        self.log(f"SERPER ORGANIC: {len(organic)} result(s)")

        grouped = {d: [] for d in domains}
        seen = set()

        for item in organic:
            url = item.get("link") or ""
            domain = self._market_domain(url, domains)
            if not domain or url in seen:
                continue
            if len(grouped[domain]) >= limit_per_domain:
                continue
            seen.add(url)
            grouped[domain].append({
                "title": item.get("title") or "",
                "url": url,
                "snippet": item.get("snippet") or "",
                "position": item.get("position"),
            })

        for domain in domains:
            self.log(f"SERPER {domain}: {len(grouped[domain])} hit(s)")
        return grouped
