from __future__ import annotations
import html as html_lib,re
from urllib.parse import quote_plus,urljoin,urlsplit,urlunsplit
import httpx
from puma_scouts.models import Marketplace,Offer,ProductMission,ScanHealth,ScanReport,Verdict
from puma_scouts.query import generate_queries
from puma_scouts.scouts.base import MarketplaceScout
from puma_scouts.scouts.catalog import _clean,_jsonld_products,_price
from puma_scouts.validator import validate_offer
def _canonical(u):p=urlsplit(u);return urlunsplit(("https",p.netloc.lower(),p.path,"",""))
def _is_product(u):p=urlsplit(u);return p.netloc.lower().removeprefix("www.")=="epicentrk.ua" and bool(re.search(r"/(?:ua/)?(?:shop|shop-mplc)/[^?#]+\.html$",p.path,re.I))
class EpicentrScout(MarketplaceScout):
    marketplace=Marketplace.EPICENTR
    def __init__(self,*,timeout=15,max_candidates_per_query=30):self.timeout=timeout;self.max_candidates_per_query=max_candidates_per_query;self.headers={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128 Safari/537.36","Accept-Language":"uk-UA,uk;q=0.9,ru;q=0.7,en;q=0.5"}
    async def generate_queries(self,m):
        article=m.article.casefold().strip();return [q for q in generate_queries(m) if q and q.casefold()!=article and article not in q.casefold() and not re.fullmatch(r"(?:19|20)\d{2}",q)][:12]
    async def _get(self,c,u):r=await c.get(u,headers=self.headers,follow_redirects=True);r.raise_for_status();return r.text
    async def _urls(self,c,q):
        found={}
        for su in (f"https://epicentrk.ua/ua/search/?q={quote_plus(q)}",f"https://epicentrk.ua/ua/search/?search={quote_plus(q)}"):
            try:page=await self._get(c,su)
            except httpx.HTTPError:continue
            decoded=html_lib.unescape(page).replace("\\/","/")
            for href in re.findall(r'href=["\']([^"\']+)["\']',decoded,re.I):
                u=urljoin(su,href)
                if _is_product(u):found.setdefault(_canonical(u),None)
            if found:break
        return list(found)[:self.max_candidates_per_query]
    def _offer(self,m,u,page,q):
        products=_jsonld_products(page)
        if not products:return None
        p=products[0];title=_clean(p.get("name"));offers=p.get("offers");offers=offers[0] if isinstance(offers,list) and offers else offers;amount=availability=seller=None;attrs={"source":"epicentr-product-page"}
        for k in ("sku","mpn","gtin","gtin13","model"):
            if p.get(k):attrs[k]=p[k]
        b=p.get("brand");attrs["brand"]=b.get("name") if isinstance(b,dict) else b
        if isinstance(offers,dict):
            amount=_price(offers.get("price") or offers.get("lowPrice"));availability=_clean(offers.get("availability")) or None;s=offers.get("seller");seller=_clean(s.get("name")) if isinstance(s,dict) else None
        if not title:return None
        return Offer(article=m.article,marketplace=self.marketplace,marketplace_product_id=_clean(p.get("sku")) or None,seller_name=seller,title=title,price=amount,availability=availability,url=_canonical(u),attributes=attrs,query_used=q,discovery_method="epicentr-search->product-page")
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
