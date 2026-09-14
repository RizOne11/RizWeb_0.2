import re
from rapidfuzz.fuzz import token_set_ratio

STOP = {
    "купити", "купить", "ціна", "цена", "україна", "украина", "доставка",
    "товар", "новий", "новый", "магазин", "офіційний", "официальный",
}
COLOR_WORDS = {
    "black","white","blue","red","green","gray","grey","silver","gold","pink","purple","orange","yellow","brown","beige","titanium","natural",
    "чорний","черный","білий","белый","синій","синий","червоний","красный","зелений","зеленый","сірий","серый","срібний","серебристый","золотий","розовый","рожевий","фіолетовий","фиолетовый","помаранчевий","оранжевый","жовтий","желтый","коричневий","бежевий","бежевый","титан",
}
VARIANT_RE = re.compile(r"\b\d+(?:[.,]\d+)?\s?(?:gb|tb|mb|гб|тб|мб|w|kw|вт|квт|mah|мач|ml|мл|l|л|kg|кг|g|гр|mm|мм|cm|см|inch|\")\b", re.I)
MODEL_RE = re.compile(r"\b(?=[A-Za-zА-Яа-яІіЇїЄєҐґ0-9._+/-]{4,}\b)(?=[A-Za-zА-Яа-яІіЇїЄєҐґ._+/-]*\d)[A-Za-zА-Яа-яІіЇїЄєҐґ0-9._+/-]+\b", re.I)


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


def build_fingerprint(row):
    title = str(row.get("Название") or "")
    brand = str(row.get("Производитель") or "")
    sku = str(row.get("Артикул") or "").strip()
    source = f"{title} {_params_text(row)}"
    model_tokens = []
    for t in MODEL_RE.findall(source):
        c = compact(t)
        if len(c) >= 4 and c != compact(sku) and c not in {compact(x) for x in model_tokens}:
            model_tokens.append(t)
    variants = []
    for v in VARIANT_RE.findall(source):
        nv = re.sub(r"\s+", "", v.lower()).replace(",", ".")
        if nv not in variants:
            variants.append(nv)
    colors = sorted({t for t in _tokens(source) if t in COLOR_WORDS})
    return {"sku": sku, "brand": brand, "title": title, "models": model_tokens[:12], "variants": variants[:12], "colors": colors}


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
    hay_norm, hay_c = norm(hay), compact(hay)
    sku_c = compact(fp["sku"])
    brand_c = compact(fp["brand"])
    source_name = norm(fp["title"])
    base = float(token_set_ratio(source_name, norm(candidate_title))) if candidate_title else 0.0

    sku_exact = bool(sku_c and len(sku_c) >= 4 and sku_c in hay_c)
    brand_ok = not brand_c or brand_c in hay_c
    matched_models = [m for m in fp["models"] if compact(m) in hay_c]

    conflicts = []
    cand_variants = {re.sub(r"\s+", "", v.lower()).replace(",", ".") for v in VARIANT_RE.findall(hay)}
    for src in fp["variants"]:
        unit = re.sub(r"[0-9.,]", "", src)
        same_unit = {v for v in cand_variants if re.sub(r"[0-9.,]", "", v) == unit}
        if same_unit and src not in same_unit:
            conflicts.append(f"variant:{src}!={','.join(sorted(same_unit))}")
    cand_colors = {t for t in _tokens(hay) if t in COLOR_WORDS}
    if fp["colors"] and cand_colors and not (set(fp["colors"]) & cand_colors):
        conflicts.append(f"color:{'/'.join(fp['colors'])}!={'/'.join(sorted(cand_colors))}")

    # An exact supplier/model identifier is decisive, but an explicit variant conflict
    # always wins: same series with another memory/power/color is NOT the same product.
    if conflicts:
        return {"score": min(base, 89.0), "status": "CONFLICT", "reason": "; ".join(conflicts), "sku_exact": sku_exact}
    if sku_exact:
        return {"score": 100.0, "status": "EXACT", "reason": "exact SKU/model identifier", "sku_exact": True}

    score = base + (8 if brand_ok and brand_c else 0) + min(18, len(matched_models) * 9)
    score = min(99.0, score)
    # Without exact SKU we require strong title/model evidence. Missing variant data is
    # allowed only as HIGH/POSSIBLE, never silently promoted to EXACT.
    if score >= 95 and (matched_models or base >= 96):
        status = "EXACT"
    elif score >= 90:
        status = "HIGH"
    else:
        status = "POSSIBLE"
    return {"score": score, "status": status, "reason": f"title={base:.1f}; models={len(matched_models)}; brand={brand_ok}", "sku_exact": False}


def score_match(row, candidate_title: str, candidate_url: str = "") -> float:
    return float(classify_match(row, candidate_title, candidate_url).get("score", 0.0))
