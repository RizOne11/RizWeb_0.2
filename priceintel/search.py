import html as htmlmod
import re
import time
import urllib.parse
import requests
from bs4 import BeautifulSoup


def _decode_ddg(href: str) -> str:
    href = htmlmod.unescape(href or "")
    parsed = urllib.parse.urlparse(href)
    qs = urllib.parse.parse_qs(parsed.query)
    if "uddg" in qs and qs["uddg"]:
        return qs["uddg"][0]
    return href


class DDGSearch:
    def __init__(self, user_agent, delay=1.5, logger=None):
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": user_agent,
            "Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        })
        self.delay = delay
        self.log = logger or (lambda msg: None)

    def _extract_links(self, text, domain, limit):
        soup = BeautifulSoup(text, "html.parser")
        out, seen = [], set()
        selectors = ["a.result__a", "a.result-link", "li.b_algo h2 a"]
        anchors = []
        for sel in selectors:
            anchors.extend(soup.select(sel))
        if not anchors:
            anchors = soup.find_all("a", href=True)
        for a in anchors:
            href = _decode_ddg(a.get("href", ""))
            if href.startswith("//"):
                href = "https:" + href
            if not href.startswith("http"):
                continue
            host = urllib.parse.urlparse(href).netloc.lower()
            if domain.lower() not in host and domain.lower() not in href.lower():
                continue
            href = href.split("#", 1)[0]
            if href in seen:
                continue
            seen.add(href)
            out.append({"title": a.get_text(" ", strip=True), "url": href})
            if len(out) >= limit:
                break
        return out

    def _request(self, engine, url, domain, limit):
        time.sleep(self.delay)
        try:
            r = self.s.get(url, timeout=25, allow_redirects=True)
            ctype = r.headers.get("content-type", "")
            self.log(f"SEARCH {engine}: HTTP {r.status_code} len={len(r.text)} type={ctype}")
            if r.status_code >= 400:
                return []
            low = r.text[:5000].lower()
            if "captcha" in low or "unusual traffic" in low or "verify you are human" in low:
                self.log(f"SEARCH {engine}: BLOCK/CAPTCHA detected")
            hits = self._extract_links(r.text, domain, limit)
            self.log(f"SEARCH {engine}: {len(hits)} hit(s) for {domain}")
            return hits
        except Exception as e:
            self.log(f"SEARCH {engine}: ERROR {type(e).__name__}: {e}")
            return []

    def search(self, query, domain, limit=5):
        q = f"site:{domain} {query}"
        encoded = urllib.parse.urlencode({"q": q})
        engines = [
            ("DDG-html", "https://html.duckduckgo.com/html/?" + encoded),
            ("DDG-lite", "https://lite.duckduckgo.com/lite/?" + encoded),
            ("Bing", "https://www.bing.com/search?" + encoded),
        ]
        for engine, url in engines:
            self.log(f"SEARCH {engine}: q={q}")
            hits = self._request(engine, url, domain, limit)
            if hits:
                return hits
        return []
