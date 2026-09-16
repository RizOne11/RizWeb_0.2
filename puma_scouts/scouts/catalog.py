from __future__ import annotations
import html as html_lib,json,re
from decimal import Decimal,InvalidOperation
from typing import Any
from urllib.parse import parse_qs,quote_plus,unquote,urljoin,urlsplit,urlunsplit
import httpx
from bs4 import BeautifulSoup
from puma_scouts.models import Marketplace,Offer,ProductMission,ScanHealth,ScanReport,Verdict
from puma_scouts.query import generate_queries
from puma_scouts.scouts.base import MarketplaceScout
from puma_scouts.validator import validate_offer
def _clean(v:Any)->str:return re.sub(r"\s+"," ",html_lib.unescape(str(v or ""))).strip()
def _price(v:Any)->Decimal|None:
    t=re.sub(r"[^0-9.]","",_clean(v).replace("\u00a0","").replace(" ","").replace(",","."))
    try:r=Decimal(t);return r if r>0 else None
    except (InvalidOperation,ValueError):return None
def _canonical(url:str)->str:
    p=urlsplit(url);return urlunsplit(("https",p.netloc.lower(),p.path,"",""))
def _jsonld_products(page:str)->list[dict[str,Any]]:
    soup=BeautifulSoup(page,"html.parser");found=[]
    for tag in soup.find_all("script",attrs={"type":"application/ld+json"}):
        try:payload=json.loads(tag.string or tag.get_text() or "")
        except (json.JSONDecodeError,TypeError):continue
        for item in payload if isinstance(payload,list) else [payload]:
            if not isinstance(item,dict):continue
            if str(item.get("@type","")).casefold()=="product":found.append(item)
            graph=item.get("@graph")
            if isinstance(graph,list):found.extend(x for x in graph if isinstance(x,dict) and str(x.get("@type","")).casefold()=="product")
    return found
class CatalogScout(MarketplaceScout):
    marketplace:Marketplace;host:str;search_templates:tuple[str,...];product_path_hints:tuple[str,...]=();allow_subdomains=False;external_fallback=False
    def __init__(self,*,timeout:float=15,max_candidates_per_query:int=20):self.timeout=timeout;self.max_candidates_per_query=max_candidates_per_query;self.headers={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128 Safari/537.36","Accept-Language":"uk-UA,uk;q=0.9,ru;q=0.7,en;q=0.5"}
    async def generate_queries(self,mission):
        article=mission.article.casefold().strip();out=[]
        for q in generate_queries(mission):
            q=q.strip()
            if not q or q.casefold()==article or (article and article in q.casefold()) or re.fullmatch(r"(?:19|20)\d{2}",q):continue
            if q not in out:out.append(q)
        return out
    def _host_matches(self,h):
        e=self.host.casefold().removeprefix("www.");a=h.casefold().removeprefix("www.");return a==e or (self.allow_subdomains and a.endswith("."+e))
    def _is_candidate(self,url):
        p=urlsplit(url);return self._host_matches(p.netloc) and bool(p.path and p.path!="/") and (not self.product_path_hints or any(h in p.path.casefold() for h in self.product_path_hints))
    async def _get(self,c,u):r=await c.get(u,headers=self.headers,follow_redirects=True);r.raise_for_status();return r.text
    def _links(self,page,base):
        found={}
        for a in BeautifulSoup(page,"html.parser").find_all("a",href=True):
            u=urljoin(base,a["href"])
            if self._is_candidate(u):found.setdefault(_canonical(u),None)
        return list(found)[:self.max_candidates_per_query]
    async def _candidate_urls(self,c,q):
        found={}
        for template in self.search_templates:
            u=template.format(q=quote_plus(q))
            try:page=await self._get(c,u)
            except httpx.HTTPError:continue
            for x in self._links(page,u):found.setdefault(x,None)
            if len(found)>=self.max_candidates_per_query:break
        return list(found)[:self.max_candidates_per_query]
    def _offer(self,m,u,page,q):
        products=_jsonld_products(page)
        if not products:return None
        p=products[0];title=_clean(p.get("name"));offers=p.get("offers");offers=offers[0] if isinstance(offers,list) and offers else offers;amount=availability=seller=None
        attrs={"source":f"{self.marketplace.value}-jsonld"}
        for k in ("sku","mpn","gtin","gtin13","model"):
            if p.get(k):attrs[k]=p[k]
        b=p.get("brand");attrs["brand"]=b.get("name") if isinstance(b,dict) else b
        if isinstance(offers,dict):
            amount=_price(offers.get("price") or offers.get("lowPrice"));availability=_clean(offers.get("availability")) or None;s=offers.get("seller");seller=_clean(s.get("name")) if isinstance(s,dict) else None
        if not title:return None
        return Offer(article=m.article,marketplace=self.marketplace,marketplace_product_id=_clean(p.get("sku")) or None,seller_name=seller,title=title,price=amount,availability=availability,url=_canonical(u),attributes=attrs,query_used=q,discovery_method=f"{self.marketplace.value}-search->jsonld")
    async def discover(self,m,q):
        out=[]
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            for u in await self._candidate_urls(c,q):
                try:o=self._offer(m,u,await self._get(c,u),q)
                except httpx.HTTPError:continue
                if o:out.append(o)
        return out
    async def scan(self,m):
        queries=await self.generate_queries(m);unique={};errors=[];seen=0
        for q in queries:
            try:offers=await self.discover(m,q)
            except Exception as e:errors.append(f"search {q!r}: {type(e).__name__}: {e}");continue
            seen+=len(offers)
            for o in offers:unique.setdefault(str(o.url),o)
        validated=[validate_offer(m,o) for o in unique.values()];passes=[x for x in validated if x.verdict==Verdict.PASS];conflicts=[x for x in validated if x.verdict==Verdict.CONFLICT]
        health=ScanHealth.FOUND if passes and not errors else ScanHealth.PARTIAL if passes or conflicts else ScanHealth.ACCESS_LIMITED if errors and not validated else ScanHealth.NOT_FOUND
        return ScanReport(article=m.article,marketplace=self.marketplace,health=health,queries_generated=len(queries),pages_scanned=len(unique),candidates_seen=seen,candidates_collected=len(unique),duplicates_removed=max(0,seen-len(unique)),search_rounds=len(queries),errors=errors,offers=validated)
class PromScout(CatalogScout):
    marketplace=Marketplace.PROM;host="prom.ua";allow_subdomains=True;product_path_hints=("/p","/m");search_templates=("https://prom.ua/ua/search?search_term={q}","https://prom.ua/ua/search?search_term={q}&sort=score")
class HotlineScout(CatalogScout):
    marketplace=Marketplace.HOTLINE;host="hotline.ua";search_templates=("https://hotline.ua/ua/sr/?q={q}",)
