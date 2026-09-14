import json, re
from bs4 import BeautifulSoup

PRICE_RE = re.compile(r'(?<!\d)(\d{1,3}(?:[\s\u00a0.,]\d{3})+|\d{3,6})(?:[.,]\d{1,2})?\s*(?:грн|₴|uah)', re.I)

def _num(v):
    if v is None: return None
    s = re.sub(r"[^0-9.,]", "", str(v)).replace(",", ".")
    if s.count(".") > 1: s = s.replace(".", "")
    try: return float(s)
    except: return None

def extract_product(html: str, url: str):
    soup = BeautifulSoup(html, "html.parser")
    title = (soup.title.get_text(" ", strip=True) if soup.title else "")
    # JSON-LD first
    for tag in soup.find_all("script", attrs={"type":"application/ld+json"}):
        try:
            data = json.loads(tag.string or "")
            items = data if isinstance(data, list) else [data]
            stack = list(items)
            while stack:
                obj = stack.pop()
                if isinstance(obj, dict):
                    if str(obj.get("@type", "")).lower() == "product":
                        title = obj.get("name") or title
                        offers = obj.get("offers")
                        if isinstance(offers, list): offers = offers[0] if offers else {}
                        if isinstance(offers, dict):
                            p = _num(offers.get("price") or offers.get("lowPrice"))
                            avail = str(offers.get("availability", ""))
                            if p: return {"title": title, "price": p, "availability": avail, "url": url}
                    stack.extend(v for v in obj.values() if isinstance(v, (dict,list)))
                elif isinstance(obj, list): stack.extend(obj)
        except Exception:
            pass
    # OpenGraph / product meta
    for sel, attr in [
        ('meta[property="product:price:amount"]','content'),
        ('meta[itemprop="price"]','content'),
        ('meta[property="og:price:amount"]','content')]:
        tag=soup.select_one(sel)
        if tag:
            p=_num(tag.get(attr))
            if p: return {"title": title, "price": p, "availability": "", "url": url}
    text=soup.get_text(" ", strip=True)
    m=PRICE_RE.search(text)
    if m:
        p=_num(m.group(1))
        if p: return {"title": title, "price": p, "availability": "", "url": url}
    return {"title": title, "price": None, "availability": "", "url": url}
