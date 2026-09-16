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
    storage_gb: frozenset[int] = field(default_factory=frozenset)
    ram_gb: frozenset[int] = field(default_factory=frozenset)
    sizes: frozenset[str] = field(default_factory=frozenset)
    colors: frozenset[str] = field(default_factory=frozenset)


# Generic entity vocabulary.  It describes classes, never brands/models/SKUs.
_ENTITY_PATTERNS = {
    "smartphone": r"\b(?:смартфон|smartphone|мобільн(?:ий|ого) телефон|мобильн(?:ый|ого) телефон)\b",
    "monitor": r"\b(?:монітор|монитор|monitor)\b",
    "headphones": r"\b(?:навушники|наушники|headphones|earbuds|airpods)\b",
    "television": r"\b(?:телевізор|телевизор|television|\btv\b)\b",
    "laptop": r"\b(?:ноутбук|laptop)\b",
    "tablet": r"\b(?:планшет|tablet)\b",
    "ssd": r"\b(?:ssd|твердотільн\w+ накопичувач|твердотельн\w+ накопитель)\b",
    "hdd": r"\b(?:hdd|жорстк\w+ диск|жестк\w+ диск)\b",
    "tire": r"\b(?:шина|шини|шины|tyre|tire)\b",
    "clothing": r"\b(?:футболка|сорочка|рубашка|куртка|штани|брюки|сукня|платье|hoodie|t-shirt)\b",
    "perfume": r"\b(?:парфум|парфюм|туалетн\w+ вод|eau de|perfume)\b",
}

# Generic non-product entities.  These are semantic classes, not one-off product patches.
_PART_PATTERNS = {
    "spare_part": r"\b(?:шлейф|flex cable|запчаст|spare part|дисплейн\w+ модул|display module|тачскрин|touchscreen|сенсор|матриц[аы]|материнск\w+ плат|motherboard|задн\w+ кришк|задн\w+ крышк)\b",
    "accessory": r"\b(?:чохол|чехол|бампер|захисн\w+ скло|защитн\w+ стекло|захисн\w+ плівк|защитн\w+ пленк|ремінець|ремешок|адаптер|перехідник|переходник|usb hub|хаб)\b",
}

_COLOR_WORDS = {
    "black","white","blue","green","red","yellow","violet","purple","pink","gold","silver","gray","grey","orange","brown",
    "чорний","чорна","білий","біла","синій","синя","блакитний","блакитна","зелений","зелена","червоний","червона","жовтий","жовта","фіолетовий","фіолетова","рожевий","рожева","золотий","срібний","сірий",
    "черный","черная","белый","белая","синий","синяя","голубой","голубая","зеленый","зеленая","красный","красная","желтый","желтая","фиолетовый","фиолетовая","розовый","розовая","золотой","серебристый","серый",
}


def entity_type(text: str) -> str | None:
    t = norm(text)
    for entity, pattern in _PART_PATTERNS.items():
        if re.search(pattern, t, re.I):
            return entity
    for entity, pattern in _ENTITY_PATTERNS.items():
        if re.search(pattern, t, re.I):
            return entity
    return None


def _memory(text: str) -> tuple[set[int], set[int]]:
    raw = str(text or "").casefold(); ram: set[int] = set(); storage: set[int] = set()
    for a, b in re.findall(r"(?<!\d)(\d{1,2})\s*[/+]\s*(\d{2,4})\s*(?:gb|гб)?\b", raw, re.I):
        ram.add(int(a)); storage.add(int(b))
    for value, unit in re.findall(r"(?<!\d)(\d{2,4})\s*(gb|гб|tb|тб)\b", raw, re.I):
        n = int(value) * (1024 if unit.casefold() in {"tb", "тб"} else 1)
        if n >= 32: storage.add(n)
    return ram, storage


def _sizes(text: str) -> set[str]:
    raw = str(text or "").casefold(); out = set()
    for value in re.findall(r"(?<!\d)(\d{1,3}(?:[.,]\d+)?)\s*(?:inch|inches|\")", raw, re.I): out.add(value.replace(",", ".") + "in")
    for value, unit in re.findall(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(mm|мм|cm|см|ml|мл|kg|кг)\b", raw, re.I): out.add(value.replace(",", ".") + unit.casefold())
    return out


def _colors(text: str) -> set[str]:
    tokens = set(norm(text).split())
    return tokens & _COLOR_WORDS


def signature(text: str) -> ProductSignature:
    ram, storage = _memory(text)
    return ProductSignature(entity=entity_type(text), storage_gb=frozenset(storage), ram_gb=frozenset(ram), sizes=frozenset(_sizes(text)), colors=frozenset(_colors(text)))


def variant_conflicts(expected_text: str, candidate_text: str) -> list[str]:
    """Return only explicit contradictions. Missing candidate data is never a conflict.

    Variant dimensions are enforced only when the expected/source product states them.
    Color is intentionally not a conflict dimension yet: marketplace colour variants are
    normally useful competing cards unless a future input column marks colour as strict.
    """
    expected, candidate = signature(expected_text), signature(candidate_text)
    out: list[str] = []
    if expected.entity and candidate.entity:
        if candidate.entity in {"spare_part", "accessory"} and expected.entity not in {"spare_part", "accessory"}:
            out.append(f"entity mismatch: expected {expected.entity}, got {candidate.entity}")
        elif expected.entity not in {"spare_part", "accessory"} and candidate.entity not in {"spare_part", "accessory"} and expected.entity != candidate.entity:
            out.append(f"entity mismatch: expected {expected.entity}, got {candidate.entity}")
    if expected.storage_gb and candidate.storage_gb and expected.storage_gb.isdisjoint(candidate.storage_gb):
        out.append(f"storage mismatch: expected {sorted(expected.storage_gb)}GB, got {sorted(candidate.storage_gb)}GB")
    if expected.ram_gb and candidate.ram_gb and expected.ram_gb.isdisjoint(candidate.ram_gb):
        out.append(f"RAM mismatch: expected {sorted(expected.ram_gb)}GB, got {sorted(candidate.ram_gb)}GB")
    if expected.sizes and candidate.sizes and expected.sizes.isdisjoint(candidate.sizes):
        out.append(f"size/volume mismatch: expected {sorted(expected.sizes)}, got {sorted(candidate.sizes)}")
    return out
