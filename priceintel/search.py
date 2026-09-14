import html as htmlmod, re, time, urllib.parse
import requests
from bs4 import BeautifulSoup

class DDGSearch:
    def __init__(self, user_agent, delay=1.5):
        self.s=requests.Session(); self.s.headers.update({"User-Agent": user_agent})
        self.delay=delay
    def search(self, query, domain, limit=5):
        q=f"site:{domain} {query}"
        url="https://html.duckduckgo.com/html/?"+urllib.parse.urlencode({"q":q})
        time.sleep(self.delay)
        r=self.s.get(url, timeout=20); r.raise_for_status()
        soup=BeautifulSoup(r.text,"html.parser")
        out=[]
        for a in soup.select("a.result__a"):
            href=a.get("href","")
            # DDG redirect -> uddg
            parsed=urllib.parse.urlparse(href)
            qs=urllib.parse.parse_qs(parsed.query)
            if "uddg" in qs: href=qs["uddg"][0]
            href=htmlmod.unescape(href)
            if domain in href:
                out.append({"title":a.get_text(" ",strip=True),"url":href})
            if len(out)>=limit: break
        return out
