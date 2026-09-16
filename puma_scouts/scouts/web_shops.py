from __future__ import annotations
import html as html_lib
from collections import defaultdict
from urllib.parse import parse_qs,quote_plus,unquote,urljoin,urlsplit
import httpx
from bs4 import BeautifulSoup
from puma_scouts.models import Marketplace,Offer,ProductMission,ScanHealth,ScanReport,Verdict
from puma_scouts.query import generate_queries
from puma_scouts.scouts.catalog import _canonical,_jsonld_products,_clean,_price
from puma_scouts.scouts.base import MarketplaceScout
from puma_scouts.validator import validate_offer
class WebShopsScout(MarketplaceScout):
    marketplace=Marketplace.WEB_SHOPS
    blocked_domains=("prom.ua","epicentrk.ua","hotline.ua","rozetka.com.ua","zakupka.com","allo.ua","comfy.ua","foxtrot.com.ua","kasta.ua","google.com","bing.com","duckduckgo.com","brave.com","yandex.ru","yandex.com","youtube.com","facebook.com","instagram.com","tiktok.com")
    def __init__(self,*,timeout=15,max_candidates_per_query=20,max_per_domain=2):self.timeout=timeout;self.max_candidates_per_query=max_candidates_per_query;self.max_per_domain=max_per_domain;self.headers={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128 Safari/537.36","Accept-Language":"uk-UA,uk;q=0.9,ru;q=0.7,en;q=0.5"}
    async def generate_queries(self,m):
        a=m.article.casefold().strip();out=[]
        for q in generate_queries(m):
            q=q.strip()
            if not q or q.casefold()==a or (a and a in q.casefold()):continue
            if q not in out:out.append(q)
        return [f"{q} купити грн" for q in out[:5]]
    def _blocked(self,h):h=h.casefold().removeprefix("www.");return any(h==x or h.endswith("."+x) for x in self.blocked_domains)
    def _unwrap(self,href,base):
        u=urljoin(base,html_lib.unescape(href));p=urlsplit(u)
        if "duckduckgo.com" in p.netloc and p.path.startswith("/l/"):
            w=parse_qs(p.query).get("uddg",[]);u=unquote(w[0]) if w else u
        return u
    def _links(self,page,base):
        out=[];per=defaultdict(int)
        for a in BeautifulSoup(page,"html.parser").find_all("a",href=True):
            u=self._unwrap(a["href"],base);p=urlsplit(u);h=p.netloc.casefold().removeprefix("www.")
            if p.scheme not in ("http","https") or not h or self._blocked(h) or not p.path or p.path=="/":continue
            text=(a.get_text(" ",strip=True)+" "+u).casefold();uaish=h.endswith(".ua") or any(x in text for x in ("купити","ціна","грн","uah","україн"))
            if not uaish or per[h]>=self.max_per_domain:continue
            c=_canonical(u)
            if c not in out:out.append(c);per[h]+=1
            if len(out)>=self.max_candidates_per_query:break
        return out
    async def _get(self,c,u):r=await c.get(u,headers=self.headers,follow_redirects=True);r.raise_for_status();return r.text
    async def _urls(self,c,q):
        found=[]
        for su in (f"https://html.duckduckgo.com/html/?q={quote_plus(q)}",f"https://www.bing.com/search?q={quote_plus(q)}&count=30&setlang=uk",f"https://search.brave.com/search?q={quote_plus(q)}&source=web"):
            try:page=await self._get(c,su)
            except httpx.HTTPError:continue
            for u in self._links(page,su):
                if u not in found:found.append(u)
                if len(found)>=self.max_candidates_per_query:return found
        return found
    def _offer(self,m,u,page,q):
        ps=_jsonld_products(page)
        if not ps:return None
        p=ps[0];title=_clean(p.get("name"));offers=p.get("offers");offers=offers[0] if isinstance(offers,list) and offers else offers;amount=availability=None
        if isinstance(offers,dict):amount=_price(offers.get("price") or offers.get("lowPrice"));availability=_clean(offers.get("availability")) or None
        if not title or amount is None:return None
        h=urlsplit(u).netloc.casefold().removeprefix("www.");attrs={"source":"web-shop-jsonld","source_domain":h}
        for k in ("sku","mpn","gtin","gtin13","model"):
            if p.get(k):attrs[k]=p[k]
        b=p.get("brand");attrs["brand"]=b.get("name") if isinstance(b,dict) else b
        return Offer(article=m.article,marketplace=self.marketplace,marketplace_product_id=_clean(p.get("sku")) or None,title=title,price=amount,availability=availability,url=_canonical(u),attributes=attrs,query_used=q,discovery_method="free-web-search->shop-jsonld")
    async def discover(self,m,q):
        out=[]
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            for u in await self._urls(c,q):
                try:o=self._offer(m,u,await self._get(c,u),q)
                except httpx.HTTPError:continue
                if o:out.append(o)
        return out
    async def scan(self,m):
        queries=await self.generate_queries(m);unique={};errors=[];seen=0
        for q in queries:
            try:offers=await self.discover(m,q)
            except Exception as e:errors.append(str(e));continue
            seen+=len(offers)
            for o in offers:unique.setdefault(str(o.url),o)
        validated=[validate_offer(m,o) for o in unique.values()];passes=[x for x in validated if x.verdict==Verdict.PASS];conflicts=[x for x in validated if x.verdict==Verdict.CONFLICT]
        health=ScanHealth.FOUND if passes and not errors else ScanHealth.PARTIAL if passes or conflicts else ScanHealth.ACCESS_LIMITED if errors and not validated else ScanHealth.NOT_FOUND
        return ScanReport(article=m.article,marketplace=self.marketplace,health=health,queries_generated=len(queries),pages_scanned=len(unique),candidates_seen=seen,candidates_collected=len(unique),duplicates_removed=max(0,seen-len(unique)),search_rounds=len(queries),errors=errors,offers=validated)
