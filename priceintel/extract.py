import json, re
from bs4 import BeautifulSoup

PRICE_RE = re.compile(r'(?<!\d)(\d{1,3}(?:[\s\u00a0.,]\d{3})+|\d{3,7})(?:[.,]\d{1,2})?\s*(?:грн|₴|uah)', re.I)


def _num(v):
    if v is None:
        return None
    s = re.sub(r"[^0-9.,]", "", str(v)).replace(",", ".")
    if s.count(".") > 1:
        s = s.replace(".", "")
    try:
        n = float(s)
        return n if n > 0 else None
    except Exception:
        return None


def _meta(soup, selectors):
    for sel, attr in selectors:
        tag = soup.select_one(sel)
        if tag:
            val = tag.get(attr)
            if val:
                return val
    return None


def _walk_json(value):
    stack = [value]
    while stack:
        obj = stack.pop()
        yield obj
        if isinstance(obj, dict):
            stack.extend(obj.values())
        elif isinstance(obj, list):
            stack.extend(obj)


def _jsonld_product(soup):
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.get_text() or ""
        try:
            data = json.loads(raw)
        except Exception:
            continue
        for obj in _walk_json(data):
            if not isinstance(obj, dict):
                continue
            typ = obj.get("@type", "")
            types = [str(x).lower() for x in typ] if isinstance(typ, list) else [str(typ).lower()]
            if "product" not in types:
                continue
            title = obj.get("name") or ""
            description = obj.get("description") or ""
            sku = obj.get("sku") or obj.get("mpn") or ""
            offers = obj.get("offers") or {}
            offer_list = offers if isinstance(offers, list) else [offers]
            prices = []
            availability = ""
            for offer in offer_list:
                if not isinstance(offer, dict):
                    continue
                p = _num(offer.get("price") or offer.get("lowPrice") or offer.get("highPrice"))
                if p:
                    prices.append(p)
                availability = availability or str(offer.get("availability") or "")
            if prices:
                return {"title": title, "description": description, "sku": sku,
                        "price": min(prices), "availability": availability}
    return None


def _embedded_product(soup):
    """Best-effort parser for JS application state used by modern marketplaces.

    This is deliberately conservative: only price-like keys near product/model/name
    data are considered. It is a fallback after JSON-LD/meta and avoids generic
    installment numbers whenever possible.
    """
    title = ""
    description = ""
    price_candidates = []
    for tag in soup.find_all("script"):
        raw = tag.string or tag.get_text() or ""
        if len(raw) < 40:
            continue
        low = raw.lower()
        if not any(k in low for k in ('product', 'offer', 'price', 'sku', 'mpn')):
            continue
        # Common serialized fields in Next/Nuxt/Redux state.
        for pat in (
            r'"(?:price|currentPrice|current_price|salePrice|sale_price|finalPrice|final_price)"\s*:\s*"?([0-9][0-9\s.,]{2,12})',
            r'"price"\s*:\s*\{[^{}]{0,300}?"(?:value|amount)"\s*:\s*"?([0-9][0-9\s.,]{2,12})',
        ):
            for m in re.finditer(pat, raw, re.I):
                p = _num(m.group(1))
                if p and 20 <= p <= 10000000:
                    price_candidates.append(p)
        if not title:
            m = re.search(r'"(?:name|title|productName|product_name)"\s*:\s*"([^"\\]{4,300})"', raw, re.I)
            if m:
                title = m.group(1)
        if not description:
            m = re.search(r'"description"\s*:\s*"([^"\\]{10,1000})"', raw, re.I)
            if m:
                description = m.group(1)
    if price_candidates:
        # Main product price tends to repeat in app state; installment values tend
        # to occur fewer times. Prefer the most frequent value, then the larger one.
        from collections import Counter
        counts = Counter(round(x, 2) for x in price_candidates)
        price = sorted(counts, key=lambda x: (counts[x], x), reverse=True)[0]
        return {"title": title, "description": description, "price": price}
    return None




def availability_state(value):
    """Normalize marketplace availability to IN_STOCK / OUT_OF_STOCK / UNKNOWN."""
    text = str(value or "").strip().lower()
    if not text:
        return "UNKNOWN"
    compact = re.sub(r"[^a-zа-яіїєґ0-9]+", " ", text, flags=re.I)
    out_tokens = (
        "outofstock", "out of stock", "soldout", "sold out", "discontinued",
        "немає в наявності", "нет в наличии", "відсутній", "отсутствует",
        "закінчився", "закончился", "не доступен", "недоступний",
    )
    in_tokens = (
        "instock", "in stock", "готово до відправки", "готов к отправке",
        "є в наявності", "есть в наличии", "в наявності", "в наличии",
        "available", "доступний", "доступен",
    )
    if any(x in text or x in compact for x in out_tokens):
        return "OUT_OF_STOCK"
    if any(x in text or x in compact for x in in_tokens):
        return "IN_STOCK"
    return "UNKNOWN"


def is_in_stock(value, unknown_is_in_stock=False):
    state = availability_state(value)
    return state == "IN_STOCK" or (unknown_is_in_stock and state == "UNKNOWN")

def extract_product(html: str, url: str):
    soup = BeautifulSoup(html or "", "html.parser")
    title = _meta(soup, [('meta[property="og:title"]', 'content'), ('meta[name="twitter:title"]', 'content')])
    title = title or (soup.title.get_text(" ", strip=True) if soup.title else "")
    description = _meta(soup, [('meta[property="og:description"]', 'content'), ('meta[name="description"]', 'content')]) or ""

    product = _jsonld_product(soup)
    if product:
        product["title"] = product.get("title") or title
        product["description"] = product.get("description") or description
        product["url"] = url
        product["extract_source"] = "jsonld"
        return product

    for sel, attr in [
        ('meta[property="product:price:amount"]', 'content'),
        ('meta[itemprop="price"]', 'content'),
        ('meta[property="og:price:amount"]', 'content'),
        ('meta[name="product:price:amount"]', 'content'),
    ]:
        tag = soup.select_one(sel)
        if tag:
            p = _num(tag.get(attr))
            if p:
                availability = _meta(soup, [
                    ('meta[property="product:availability"]', 'content'),
                    ('meta[itemprop="availability"]', 'content'),
                    ('link[itemprop="availability"]', 'href'),
                ]) or ""
                return {"title": title, "description": description, "price": p,
                        "availability": availability, "url": url, "extract_source": "meta"}

    embedded = _embedded_product(soup)
    if embedded:
        return {"title": embedded.get("title") or title,
                "description": embedded.get("description") or description,
                "price": embedded.get("price"), "availability": "", "url": url,
                "extract_source": "embedded_json"}

    text = soup.get_text(" ", strip=True)
    availability = _meta(soup, [
        ('meta[property="product:availability"]', 'content'),
        ('meta[itemprop="availability"]', 'content'),
        ('link[itemprop="availability"]', 'href'),
    ]) or ""
    if not availability:
        low_text = text.lower()
        for phrase in ("готово до відправки", "є в наявності", "в наявності", "готов к отправке", "есть в наличии", "в наличии", "немає в наявності", "нет в наличии"):
            if phrase in low_text:
                availability = phrase
                break
    # Last resort only. Skip values explicitly presented as monthly installments.
    candidates = []
    for m in PRICE_RE.finditer(text):
        around = text[max(0, m.start()-40):min(len(text), m.end()+40)].lower()
        if any(x in around for x in ('/міс', 'на місяць', 'в місяць', 'щомісяц', 'платіж')):
            continue
        p = _num(m.group(1))
        if p:
            candidates.append(p)
    if candidates:
        return {"title": title, "description": description, "price": candidates[0],
                "availability": availability, "url": url, "extract_source": "text"}
    return {"title": title, "description": description, "price": None,
            "availability": availability, "url": url, "extract_source": "none"}
