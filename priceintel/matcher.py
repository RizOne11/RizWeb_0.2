import re
from rapidfuzz.fuzz import token_set_ratio

STOP = {
    "купити", "купить", "ціна", "цена", "україна", "украина", "доставка",
    "товар", "новий", "новый", "магазин", "офіційний", "официальный",
}

# Canonical colour groups prevent false conflicts such as black vs чорний.
COLOR_ALIASES = {
    "black": "black", "чорний": "black", "черный": "black",
    "white": "white", "білий": "white", "белый": "white",
    "blue": "blue", "синій": "blue", "синий": "blue",
    "red": "red", "червоний": "red", "красный": "red",
    "green": "green", "зелений": "green", "зеленый": "green",
    "gray": "gray", "grey": "gray", "сірий": "gray", "серый": "gray",
    "silver": "silver", "срібний": "silver", "серебристый": "silver",
    "gold": "gold", "золотий": "gold",
    "pink": "pink", "рожевий": "pink", "розовый": "pink",
    "purple": "purple", "фіолетовий": "purple", "фиолетовый": "purple",
    "orange": "orange", "помаранчевий": "orange", "оранжевый": "orange",
    "yellow": "yellow", "жовтий": "yellow", "желтый": "yellow",
    "brown": "brown", "коричневий": "brown",
    "beige": "beige", "бежевий": "beige", "бежевый": "beige",
    "titanium": "titanium", "титан": "titanium",
    "natural": "natural",
}
COLOR_WORDS = set(COLOR_ALIASES)

VARIANT_RE = re.compile(
    r"\b\d+(?:[.,]\d+)?\s?(?:gb|tb|mb|гб|тб|мб|w|kw|вт|квт|mah|мач|ml|мл|l|л|kg|кг|g|гр|mm|мм|cm|см|inch|hz|гц|v|в|\")(?=\s|$|[^A-Za-zА-Яа-яІіЇїЄєҐґ0-9])",
    re.I,
)
MODEL_RE = re.compile(
    r"\b(?=[A-Za-zА-Яа-яІіЇїЄєҐґ0-9._+/-]{4,}\b)(?=[A-Za-zА-Яа-яІіЇїЄєҐґ._+/-]*\d)[A-Za-zА-Яа-яІіЇїЄєҐґ0-9._+/-]+\b",
    re.I,
)


def norm(s: str) -> str:
    s = (s or "").lower().replace("’", "'")
    s = re.sub(r"[^a-zа-яіїєґ0-9+._/-]+", " ", s, flags=re.I)
    return " ".join(t for t in s.split() if t not in STOP)


def compact(s: str) -> str:
    return re.sub(r"[^a-zа-яіїєґ0-9]+", "", (s or "").lower(), flags=re.I)


def _tokens(text):
    return [x.lower() for x in re.findall(r"[A-Za-zА-Яа-яІіЇїЄєҐґ0-9._+/-]+", str(text or ""))]


def _params_text(row):
    params = row.get("Параметры") or []
    out = []
    for p in params:
        if isinstance(p, dict):
            out.extend([str(p.get("name") or ""), str(p.get("value") or "")])
        else:
            out.append(str(p))
    return " ".join(out)


def _canonical_colors(text):
    return sorted({COLOR_ALIASES[t] for t in _tokens(text) if t in COLOR_ALIASES})


UNIT_ALIASES = {
    "гц": "hz", "hz": "hz",
    "вт": "w", "w": "w", "квт": "kw", "kw": "kw",
    "гб": "gb", "gb": "gb", "тб": "tb", "tb": "tb", "мб": "mb", "mb": "mb",
    "мач": "mah", "mah": "mah",
    "мл": "ml", "ml": "ml", "л": "l", "l": "l",
    "кг": "kg", "kg": "kg", "гр": "g", "g": "g",
    "мм": "mm", "mm": "mm", "см": "cm", "cm": "cm",
    "inch": "inch", '"': "inch",
    "в": "v", "v": "v",
}


def _canonical_variant(v):
    raw = re.sub(r"\s+", "", str(v or "").lower()).replace(",", ".")
    m = re.match(r"(\d+(?:\.\d+)?)(.*)", raw)
    if not m:
        return raw
    num, unit = m.group(1), m.group(2)
    return f"{num}{UNIT_ALIASES.get(unit, unit)}"


def _resolution_values(text):
    out = set()
    for a, b in re.findall(r"(?<!\d)(\d{3,4})\s*[xх×]\s*(\d{3,4})(?!\d)", str(text or ""), re.I):
        out.add(f"{int(a)}x{int(b)}")
    return out


def _sku_distinctive(sku: str) -> bool:
    """Supplier SKU can be an internal numeric code, so never trust it blindly.

    A mixed alpha-numeric identifier is more likely to be a real model/MPN, but
    even then it is only corroborating evidence unless title/brand/model agrees.
    """
    c = compact(sku)
    return len(c) >= 6 and bool(re.search(r"[a-zа-яіїєґ]", c, re.I)) and bool(re.search(r"\d", c))




def _model_token_is_spec(token):
    """Reject technical-spec tokens that only look like model identifiers."""
    t = str(token or "").strip().lower()
    c = compact(t)
    if not c:
        return True
    if re.fullmatch(r"\d{3,4}[xх×]\d{3,4}", t, re.I):
        return True
    if re.fullmatch(r"\d+(?:\.\d+)?(?:k|hz|гц|w|вт|gb|гб|tb|тб|mah|мач|v|в)", t, re.I):
        return True
    if re.fullmatch(r"hdr\d+", c, re.I):
        return True
    if re.fullmatch(r"dci-?p3", t, re.I) or c in {"dcip3", "srgb", "adobergb", "freesync", "gsync"}:
        return True
    # Common certification / feature codes are not product identities.
    if c.startswith("tuv") or c.startswith("vesa"):
        return True
    return False

def build_fingerprint(row):
    title = str(row.get("Название") or "")
    brand = str(row.get("Производитель") or "")
    sku = str(row.get("Артикул") or "").strip()
    source = f"{title} {_params_text(row)}"
    model_tokens = []
    sku_c = compact(sku)
    seen = set()
    for t in MODEL_RE.findall(source):
        c = compact(t)
        if _model_token_is_spec(t):
            continue
        if len(c) >= 4 and c != sku_c and c not in seen:
            seen.add(c)
            model_tokens.append(t)
    variants = []
    for v in VARIANT_RE.findall(source):
        nv = _canonical_variant(v)
        if nv not in variants:
            variants.append(nv)
    colors = _canonical_colors(source)
    return {
        "sku": sku,
        "brand": brand,
        "title": title,
        "models": model_tokens[:12],
        "variants": variants[:12],
        "colors": colors,
    }


def build_query(row) -> str:
    brand = row.get("Производитель", "")
    sku = row.get("Артикул", "")
    name = row.get("Название", "")
    if sku and len(str(sku)) >= 4:
        return f'"{sku}" {brand}'.strip()
    return " ".join(x for x in [brand, name] if x)[:180]


def classify_match(row, candidate_title: str, candidate_url: str = "", candidate_text: str = ""):
    fp = build_fingerprint(row)
    hay = " ".join([candidate_title or "", candidate_url or "", candidate_text or ""])
    hay_c = compact(hay)
    sku_c = compact(fp["sku"])
    brand_c = compact(fp["brand"])
    source_name = norm(fp["title"])
    candidate_name = norm(candidate_title)
    base = float(token_set_ratio(source_name, candidate_name)) if candidate_title else 0.0

    supplier_sku_hit = bool(sku_c and len(sku_c) >= 4 and sku_c in hay_c)
    sku_distinctive = _sku_distinctive(fp["sku"])
    brand_present = bool(brand_c and brand_c in hay_c)
    brand_required = bool(brand_c)
    matched_models = [m for m in fp["models"] if compact(m) in hay_c]

    conflicts = []
    cand_variants = {_canonical_variant(v) for v in VARIANT_RE.findall(hay)}
    for src in fp["variants"]:
        unit = re.sub(r"[0-9.,]", "", src)
        same_unit = {v for v in cand_variants if re.sub(r"[0-9.,]", "", v) == unit}
        if same_unit and src not in same_unit:
            conflicts.append(f"variant:{src}!={','.join(sorted(same_unit))}")

    src_res = _resolution_values(fp["title"] + " " + _params_text(row))
    cand_res = _resolution_values(hay)
    if src_res and cand_res and not (src_res & cand_res):
        conflicts.append(f"resolution:{'/'.join(sorted(src_res))}!={'/'.join(sorted(cand_res))}")

    cand_colors = set(_canonical_colors(hay))
    if fp["colors"] and cand_colors and not (set(fp["colors"]) & cand_colors):
        conflicts.append(f"color:{'/'.join(fp['colors'])}!={'/'.join(sorted(cand_colors))}")

    # Explicit variant conflict always wins.
    if conflicts:
        return {
            "score": min(base, 89.0),
            "status": "CONFLICT",
            "reason": "; ".join(conflicts),
            "sku_exact": supplier_sku_hit,
        }

    # Supplier article is immutable internally, but it is NOT guaranteed to be a
    # globally unique manufacturer code. Numeric supplier IDs such as "11676"
    # can appear on unrelated shops/products. Therefore SKU is corroboration,
    # never a standalone EXACT gate.
    sku_bonus = 0
    if supplier_sku_hit:
        sku_bonus = 16 if sku_distinctive else 7

    brand_bonus = 8 if brand_present else 0
    model_bonus = min(20, len(matched_models) * 10)
    score = min(99.0, base + brand_bonus + model_bonus + sku_bonus)

    strong_identity = (
        base >= 94
        or (brand_present and base >= 86)
        or (brand_present and matched_models and base >= 78)
        or (sku_distinctive and supplier_sku_hit and (brand_present or base >= 84 or matched_models))
    )

    if strong_identity and score >= 95:
        status = "EXACT"
    elif score >= 90:
        status = "HIGH"
    else:
        status = "POSSIBLE"

    # Missing a known brand plus weak title/model evidence cannot be EXACT even
    # when a generic supplier code happens to be present.
    if brand_required and not brand_present and base < 90 and not matched_models:
        status = "POSSIBLE"
        score = min(score, 89.0)

    reason = (
        f"title={base:.1f}; models={len(matched_models)}; brand={brand_present}; "
        f"supplier_sku_hit={supplier_sku_hit}; sku_distinctive={sku_distinctive}"
    )
    return {"score": score, "status": status, "reason": reason, "sku_exact": supplier_sku_hit}


def score_match(row, candidate_title: str, candidate_url: str = "") -> float:
    return float(classify_match(row, candidate_title, candidate_url).get("score", 0.0))
