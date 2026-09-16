from __future__ import annotations
import asyncio,html as html_lib,json,re
from decimal import Decimal,InvalidOperation
from typing import Any
from urllib.parse import quote_plus,urljoin,urlsplit,urlunsplit
import httpx
from bs4 import BeautifulSoup
from puma_scouts.models import Marketplace,Offer,ProductMission,ScanHealth,ScanReport,Verdict
from puma_scouts.query import generate_queries
from puma_scouts.scouts.base import MarketplaceScout
from puma_scouts.validator import validate_offer
_EPICENTR_HOSTS={"epicentrk.ua","www.epicentrk.ua"};_PRODUCT_PATH_RE=re.compile(r"/(?:ua/)?(?:shop|shop-mplc)/[^?#]+\.html$",re.I)
def _clean(v:Any)->str:return re.sub(r"\s+"," ",html_lib.unescape(str(v or ""))).strip()
def _canonical_url(u:str)->str:p=urlsplit(u);return urlunsplit(("https",p.netloc.lower(),p.path,"",""))
def _is_product_url(u:str)->bool:p=urlsplit(u);return p.netloc.lower() in _EPICENTR_HOSTS and bool(_PRODUCT_PATH_RE.search(p.path))
def _decimal_price(v:Any)->Decimal|None:
    if v in (None,""):return None
    t=re.sub(r"[^0-9.]","",_clean(v).replace("\u00a0","").replace(" ","").replace(",","."))
    try:r=Decimal(t);return r if r>0 else None
    except (InvalidOperation,ValueError):return None
def _jsonld_products(html:str)->list[dict[str,Any]]:
    products=[];pattern=r'<script\b[^>]*\btype\s*=\s*["\']application/ld\+json["\'][^>]*>(.*?)</script\s*>'
    for raw in re.findall(pattern,html,flags=re.I|re.S):
        payload=None
        for candidate in (raw.strip(),html_lib.unescape(raw).strip()):
            try:payload=json.loads(candidate);break
            except (json.JSONDecodeError,TypeError):continue
        if payload is None:continue
        for item in payload if isinstance(payload,list) else [payload]:
            if not isinstance(item,dict):continue
            if str(item.get("@type","")).casefold()=="product":products.append(item)
            graph=item.get("@graph")
            if isinstance(graph,list):products.extend(x for x in graph if isinstance(x,dict) and str(x.get("@type","")).casefold()=="product")
    return products
def _meta(html:str,key:str)->str|None:
    soup=BeautifulSoup(html,"html.parser");tag=soup.find("meta",attrs={"property":key}) or soup.find("meta",attrs={"name":key});return _clean(tag.get("content")) if tag and tag.get("content") else None
def _extract_embedded_price(html:str)->Decimal|None:
    soup=BeautifulSoup(html,"html.parser")
    # Prefer machine-readable current-price attributes before broad text fallbacks.
    for tag in soup.select('[itemprop="price"], [data-price], meta[property="product:price:amount"], meta[property="og:price:amount"]'):
        for attr in ("content","value","data-price"):
            p=_decimal_price(tag.get(attr))
            if p and p>=10:return p
    patterns=(
        r'"(?:price|currentPrice|finalPrice|priceValue|productPrice|salePrice|actualPrice)"\s*:\s*(?:"|\{[^{}]{0,160}?"(?:value|amount)"\s*:\s*")?([0-9][0-9\s.,]{1,15})',
        r'(?:data-price|itemprop=["\']price["\'])[^>]{0,160}?(?:content|value|data-price)?\s*=\s*["\']([0-9][0-9\s.,]{1,15})',
        r'(?:Ціна|Цена)\s*:?\s*(?:</?[^>]+>\s*){0,6}([0-9][0-9\s]{2,10})\s*(?:₴|грн)',
        r'([0-9][0-9\s]{2,10})\s*(?:₴|грн)(?:\s*/\s*(?:шт\.?|од\.?))?'
    )
    for pattern in patterns:
        for m in re.finditer(pattern,html,flags=re.I|re.S):
            p=_decimal_price(m.group(1))
            if p and p>=10:return p
    return None
def _offer_from_page(article:str,url:str,html:str,query:str)->Offer|None:
    title=_meta(html,"og:title") or "";price=_decimal_price(_meta(html,"product:price:amount") or _meta(html,"og:price:amount"));availability=None;seller_name=None;attrs={"source":"epicentr-product-page"}
    products=_jsonld_products(html)
    if products:
        product=products[0];title=_clean(product.get("name")) or title
        for key in ("sku","mpn","gtin","gtin13","model"):
            if product.get(key):attrs[key]=product[key]
        brand=product.get("brand");attrs["brand"]=brand.get("name") if isinstance(brand,dict) else brand
        offers=product.get("offers");offers=offers[0] if isinstance(offers,list) and offers else offers
        if isinstance(offers,dict):
            price=price or _decimal_price(offers.get("price") or offers.get("lowPrice"));availability=_clean(offers.get("availability")) or None;seller=offers.get("seller");seller_name=_clean(seller.get("name")) if isinstance(seller,dict) else None
    if not title:
        soup=BeautifulSoup(html,"html.parser");title=_clean(soup.title.string if soup.title else "")
    if not title:return None
    price=price or _extract_embedded_price(html)
    return Offer(article=article,marketplace=Marketplace.EPICENTR,marketplace_product_id=_clean(attrs.get("sku")) or None,seller_name=seller_name,title=title,price=price,availability=availability,url=_canonical_url(url),image_urls=[],attributes=attrs,query_used=query,discovery_method="epicentr-search->product-page")
class EpicentrScout(MarketplaceScout):
    marketplace=Marketplace.EPICENTR
    def __init__(self,*,timeout:float=15.0,max_candidates_per_query:int=30)->None:self.timeout=timeout;self.max_candidates_per_query=max_candidates_per_query;self.headers={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128 Safari/537.36","Accept-Language":"uk-UA,uk;q=0.9,ru;q=0.7,en;q=0.5"}
    async def generate_queries(self,m:ProductMission)->list[str]:
        article=m.article.casefold().strip();useful=[]
        for query in generate_queries(m):
            q=query.strip()
            if not q or q.casefold()==article or re.fullmatch(r"(?:19|20)\d{2}",q) or (article and article in q.casefold()):continue
            if q not in useful:useful.append(q)
        return useful[:4]
    async def _get(self,c:httpx.AsyncClient,u:str)->str:r=await c.get(u,headers=self.headers,follow_redirects=True);r.raise_for_status();return r.text
    async def _candidate_urls(self,c:httpx.AsyncClient,q:str)->list[str]:
        found={};last_error=None
        for su in (f"https://epicentrk.ua/ua/search/?q={quote_plus(q)}",f"https://epicentrk.ua/ua/search/?search={quote_plus(q)}"):
            try:page=await self._get(c,su)
            except httpx.HTTPError as exc:last_error=exc;continue
            decoded=html_lib.unescape(page).replace("\\/","/")
            for href in re.findall(r'href=["\']([^"\']+)["\']',decoded,flags=re.I):
                u=urljoin(su,href)
                if _is_product_url(u):found.setdefault(_canonical_url(u),None)
            for raw in re.findall(r'https?://(?:www\.)?epicentrk\.ua/(?:ua/)?(?:shop|shop-mplc)/[^\s"\'<>]+?\.html',decoded,flags=re.I):
                if _is_product_url(raw):found.setdefault(_canonical_url(raw),None)
            if found:break
        if found:return list(found)[:self.max_candidates_per_query]
        if last_error:raise last_error
        return []
    async def discover(self,m:ProductMission,q:str)->list[Offer]:
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            urls=await self._candidate_urls(c,q)
            async def one(u):
                try:return _offer_from_page(m.article,u,await self._get(c,u),q)
                except (httpx.HTTPError,ValueError,json.JSONDecodeError):return None
            result=await asyncio.gather(*(one(u) for u in urls));return [o for o in result if o]
    async def scan(self,m:ProductMission)->ScanReport:
        queries=await self.generate_queries(m);unique={};errors=[];seen=0
        results=await asyncio.gather(*(self.discover(m,q) for q in queries),return_exceptions=True)
        for q,result in zip(queries,results):
            if isinstance(result,Exception):errors.append(f"search {q!r}: {type(result).__name__}: {result}");continue
            seen+=len(result)
            for o in result:unique.setdefault(str(o.url),o)
        validated=[validate_offer(m,o) for o in unique.values()];passes=[x for x in validated if x.verdict==Verdict.PASS];conflicts=[x for x in validated if x.verdict==Verdict.CONFLICT]
        health=ScanHealth.PARTIAL if passes and errors else ScanHealth.FOUND if passes else ScanHealth.PARTIAL if conflicts else ScanHealth.ACCESS_LIMITED if errors and not validated else ScanHealth.NOT_FOUND
        return ScanReport(article=m.article,marketplace=self.marketplace,health=health,queries_generated=len(queries),pages_scanned=len(unique),candidates_seen=seen,candidates_collected=len(unique),duplicates_removed=max(0,seen-len(unique)),search_rounds=len(queries),errors=errors,offers=validated)
