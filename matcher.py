import re
from rapidfuzz.fuzz import token_set_ratio

STOP = {
    "купити", "купить", "ціна", "цена", "україна", "украина", "доставка",
    "товар", "новий", "новый", "магазин", "офіційний", "официальный",
}


def norm(s: str) -> str:
    s = (s or "").lower().replace("’", "'")
    s = re.sub(r"[^a-zа-яіїєґ0-9+._-]+", " ", s, flags=re.I)
    return " ".join(t for t in s.split() if t not in STOP)


def compact(s: str) -> str:
    return re.sub(r"[^a-zа-яіїєґ0-9]+", "", (s or "").lower(), flags=re.I)


def build_query(row) -> str:
    brand = row.get("Производитель", "")
    sku = row.get("Артикул", "")
    name = row.get("Название", "")
    if sku and len(str(sku)) >= 4:
        return f'"{sku}" {brand}'.strip()
    return " ".join(x for x in [brand, name] if x)[:180]


def score_match(row, candidate_title: str, candidate_url: str = "") -> float:
    """Matcher v2.

    Exact SKU/article in title or URL is decisive. Otherwise combine title similarity
    with brand/model signals. This is intentionally conservative to avoid accepting
    unrelated products that happen to share generic words.
    """
    name = norm(row.get("Название", ""))
    title = norm(candidate_title)
    sku_raw = str(row.get("Артикул", "") or "").strip()
    brand = norm(row.get("Производитель", ""))

    sku_c = compact(sku_raw)
    haystack_c = compact((candidate_title or "") + " " + (candidate_url or ""))

    if sku_c and len(sku_c) >= 4 and sku_c in haystack_c:
        return 100.0

    if not title:
        return 0.0

    base = float(token_set_ratio(name, title)) if name else 0.0

    if brand and brand in title:
        base += 8

    # Reward distinctive alphanumeric model tokens from the source title.
    source_tokens = [t for t in norm(row.get("Название", "")).split() if any(c.isdigit() for c in t) and len(t) >= 4]
    title_c = compact(candidate_title)
    matched_models = sum(1 for t in source_tokens[:5] if compact(t) and compact(t) in title_c)
    base += min(18, matched_models * 9)

    return min(100.0, base)
