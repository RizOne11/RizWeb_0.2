import re
from rapidfuzz.fuzz import token_set_ratio

STOP = {"купити","купить","ціна","цена","україна","украина","доставка","товар","новий","новый"}

def norm(s: str) -> str:
    s = (s or "").lower().replace("’", "'")
    s = re.sub(r"[^a-zа-яіїєґ0-9+._-]+", " ", s, flags=re.I)
    return " ".join(t for t in s.split() if t not in STOP)

def build_query(row) -> str:
    brand = row.get("Производитель", "")
    sku = row.get("Артикул", "")
    name = row.get("Название", "")
    if sku and len(sku) >= 4 and not sku.isdigit():
        return f'"{sku}" {brand}'.strip()
    if sku and len(sku) >= 5:
        return f'"{sku}" {brand}'.strip()
    return " ".join(x for x in [brand, name] if x)[:180]

def score_match(row, candidate_title: str) -> float:
    name = norm(row.get("Название", ""))
    title = norm(candidate_title)
    sku = norm(row.get("Артикул", ""))
    brand = norm(row.get("Производитель", ""))
    base = token_set_ratio(name, title)
    if sku and sku in title:
        base += 22
    if brand and brand in title:
        base += 6
    return min(100.0, float(base))
