from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


def norm(value: Any) -> str:
    text = str(value or "").casefold()
    text = re.sub(r"[^\w./+\-\"]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


@dataclass(frozen=True)
class ProductSignature:
    entity: str | None = None
    core_tokens: frozenset[str] = field(default_factory=frozenset)
    storage_gb: frozenset[int] = field(default_factory=frozenset)
    ram_gb: frozenset[int] = field(default_factory=frozenset)
    sizes: frozenset[str] = field(default_factory=frozenset)
    colors: frozenset[str] = field(default_factory=frozenset)


_ENTITY_PATTERNS = {
    "smartphone": r"\b(?:смартфон|smartphone|мобільн(?:ий|ого) телефон|мобильн(?:ый|ого) телефон)\b",
    "monitor": r"\b(?:монітор|монитор|monitor)\b",
    "headphones": r"\b(?:навушники|наушники|headphones|earbuds|airpods)\b",
    "television": r"\b(?:телевізор|телевизор|television|tv)\b",
    "laptop": r"\b(?:ноутбук|laptop)\b",
    "tablet": r"\b(?:планшет|tablet)\b",
    "ssd": r"\b(?:ssd|твердотільн\w+ накопичувач|твердотельн\w+ накопитель)\b",
    "hdd": r"\b(?:hdd|жорстк\w+ диск|жестк\w+ диск)\b",
    "tire": r"\b(?:шина|шини|шины|tyre|tire)\b",
    "clothing": r"\b(?:футболка|сорочка|рубашка|куртка|штани|брюки|сукня|платье|hoodie|t-shirt)\b",
    "perfume": r"\b(?:парфум|парфюм|туалетн\w+ вод|eau de|perfume)\b",
}

# Semantic classes, deliberately brand/model agnostic.
_PART_PATTERNS = {
    "spare_part": r"\b(?:шлейф|flex cable|запчаст\w*|spare part|дисплей\w*|display(?: module)?|екран\w*|экран\w*|screen module|тачскрин\w*|touchscreen|сенсор\w*|матриц[аы]|акумулятор\w*|аккумулятор\w*|battery|материнск\w+ плат\w*|motherboard|задн\w+ кришк\w*|задн\w+ крышк\w*)\b",
    "accessory": r"\b(?:чохол\w*|чехол\w*|бампер\w*|захисн\w+ скло|защитн\w+ стекло|захисн\w+ плівк\w*|защитн\w+ пленк\w*|гідрогел\w*|гидрогел\w*|ремінець\w*|ремешок\w*|адаптер\w*|перехідник\w*|переходник\w*|usb hub|хаб)\b",
}

_COLOR_WORDS = {"black","white","blue","green","red","yellow","violet","purple","pink","gold","silver","gray","grey","orange","brown","чорний","чорна","білий","біла","синій","синя","блакитний","блакитна","зелений","зелена","червоний","червона","жовтий","жовта","фіолетовий","фіолетова","рожевий","рожева","золотий","срібний","сірий","черный","черная","белый","белая","синий","синяя","голубой","голубая","зеленый","зеленая","красный","красная","желтый","желтая","фиолетовый","фиолетовая","розовый","розовая","золотой","серебристый","серый"}

_STOP = {"смартфон","smartphone","монітор","монитор","monitor","навушники","наушники","headphones","earbuds","телевізор","телевизор","ноутбук","laptop","планшет","tablet","apple","samsung","xiaomi","redmi","pro","plus","max","gen","generation","with","case","black","white","чорний","черный","білий","белый","gb","гб","5g","2k","ips","hdr10","usb","type","charging","magsafe"}


def entity_type(text: str) -> str | None:
    t = norm(text)
    for entity, pattern in _PART_PATTERNS.items():
        if re.search(pattern, t, re.I): return entity
    for entity, pattern in _ENTITY_PATTERNS.items():
        if re.search(pattern, t, re.I): return entity
    return None


def _memory(text: str) -> tuple[set[int], set[int]]:
    raw=str(text or "").casefold();ram=set();storage=set()
    for a,b in re.findall(r"(?<!\d)(\d{1,2})\s*[/+]\s*(\d{2,4})\s*(?:gb|гб)?\b",raw,re.I): ram.add(int(a));storage.add(int(b))
    for value,unit in re.findall(r"(?<!\d)(\d{2,4})\s*(gb|гб|tb|тб)\b",raw,re.I):
        n=int(value)*(1024 if unit.casefold() in {"tb","тб"} else 1)
        if n>=32:storage.add(n)
    return ram,storage


def _sizes(text:str)->set[str]:
    raw=str(text or "").casefold();out=set()
    for value in re.findall(r"(?<!\d)(\d{1,3}(?:[.,]\d+)?)\s*(?:inch|inches|\")",raw,re.I):out.add(value.replace(",",".")+"in")
    for value,unit in re.findall(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(mm|мм|cm|см|ml|мл|kg|кг)\b",raw,re.I):out.add(value.replace(",",".")+unit.casefold())
    return out


def _core_tokens(text:str)->set[str]:
    # Core = discriminating family/model-like tokens from the human product name.
    # No brand catalogue or product-specific rule table is used.
    out=set()
    for token in norm(text).split():
        c=re.sub(r"[^a-zа-яіїє0-9]","",token,re.I)
        if not c or c in _STOP or c in _COLOR_WORDS:continue
        if re.fullmatch(r"20\d{2}",c) or re.fullmatch(r"\d+(?:hz|гц)?",c):continue
        # Mixed alpha-numeric family tokens (A55, A27Q) are strongest generic core evidence.
        if re.search(r"[a-zа-яіїє]",c,re.I) and re.search(r"\d",c):out.add(c)
    return out


def signature(text:str)->ProductSignature:
    ram,storage=_memory(text)
    return ProductSignature(entity=entity_type(text),core_tokens=frozenset(_core_tokens(text)),storage_gb=frozenset(storage),ram_gb=frozenset(ram),sizes=frozenset(_sizes(text)),colors=frozenset(set(norm(text).split())&_COLOR_WORDS))


def identity_conflicts(expected_text:str,candidate_text:str)->list[str]:
    expected,candidate=signature(expected_text),signature(candidate_text);out=[]
    if expected.entity and candidate.entity and expected.entity!=candidate.entity:
        out.append(f"entity mismatch: expected {expected.entity}, got {candidate.entity}")
    # If both sides explicitly expose family/model-like core tokens, different cores contradict.
    # Missing candidate core remains unknown, not false.
    if expected.core_tokens and candidate.core_tokens and expected.core_tokens.isdisjoint(candidate.core_tokens):
        out.append(f"product core mismatch: expected {sorted(expected.core_tokens)}, got {sorted(candidate.core_tokens)}")
    return out


def variant_conflicts(expected_text:str,candidate_text:str)->list[str]:
    expected,candidate=signature(expected_text),signature(candidate_text);out=identity_conflicts(expected_text,candidate_text)
    if expected.storage_gb and candidate.storage_gb and expected.storage_gb.isdisjoint(candidate.storage_gb):out.append(f"storage mismatch: expected {sorted(expected.storage_gb)}GB, got {sorted(candidate.storage_gb)}GB")
    if expected.ram_gb and candidate.ram_gb and expected.ram_gb.isdisjoint(candidate.ram_gb):out.append(f"RAM mismatch: expected {sorted(expected.ram_gb)}GB, got {sorted(candidate.ram_gb)}GB")
    if expected.sizes and candidate.sizes and expected.sizes.isdisjoint(candidate.sizes):out.append(f"size/volume mismatch: expected {sorted(expected.sizes)}, got {sorted(candidate.sizes)}")
    return list(dict.fromkeys(out))
