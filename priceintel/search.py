import os
import re
import urllib.parse
import requests


class SerperSearch:
    """
    Serper search optimized for testing/free accounts.

    Strategy:
    - 1 Serper request per product.
    - Send ONLY the product identifier/SKU as q.
    - No quotes, site:, OR, shopping words, or other operators.
    - Filter returned URLs locally by selected marketplace domains.
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

        if host.startswith("www."):
            host = host[4:]

        for domain in domains:
            d = domain.lower().strip()
            if host == d or host.endswith("." + d):
                return domain

        return None

    def _extract_identifier(self, query):
        """
        runner/build_query currently sends strings like:
            "JBLC50HIRED" JBL
            "676A2AA" HyperX

        For the free-account test we reduce that to:
            JBLC50HIRED
            676A2AA
        """
        q = " ".join(str(query or "").split()).strip()

        # Prefer the first quoted value — this is the SKU/article in our runner.
        m = re.search(r'["“”]([^"“”]+)["“”]', q)
        if m:
            identifier = m.group(1).strip()
        else:
            # Fallback: use only the first token.
            identifier = q.split()[0].strip() if q else ""

        # Remove quote-like punctuation accidentally left around the token.
        identifier = identifier.strip('\'"“”`')

        return identifier or q

    def search_all(self, query, domains, limit_per_domain=5):
        if not self.api_key:
            raise RuntimeError(
                "SERPER_API_KEY is not configured. Add it in Render -> Environment."
            )

        simple_query = self._extract_identifier(query)

        payload = {
            "q": simple_query,
            "gl": self.gl,
            "hl": self.hl,
            "num": self.num,
        }

        self.log(f"SERPER QUERY: {simple_query}")

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
        shopping = data.get("shopping") or []

        self.log(
            f"SERPER RESULTS: organic={len(organic)} shopping={len(shopping)}"
        )

        grouped = {d: [] for d in domains}
        seen = set()

        for item in organic:
            url = item.get("link") or ""
            domain = self._market_domain(url, domains)

            if not domain or not url or url in seen:
                continue

            if len(grouped[domain]) >= limit_per_domain:
                continue

            seen.add(url)
            grouped[domain].append({
                "title": item.get("title") or "",
                "url": url,
                "snippet": item.get("snippet") or "",
                "position": item.get("position"),
                "source": "organic",
            })

        for item in shopping:
            url = item.get("link") or ""
            domain = self._market_domain(url, domains)

            if not domain or not url or url in seen:
                continue

            if len(grouped[domain]) >= limit_per_domain:
                continue

            seen.add(url)
            grouped[domain].append({
                "title": item.get("title") or "",
                "url": url,
                "snippet": item.get("source") or "",
                "position": item.get("position"),
                "source": "shopping",
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
