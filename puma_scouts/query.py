from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from puma_scouts.models import ProductMission

_ID_KEYS = ("ean", "gtin", "mpn", "model", "vendorcode", "vendor_code", "sku", "code")
_NAME_KEYS = ("name", "title", "название", "назва")
_BRAND_KEYS = ("brand", "vendor", "бренд", "производитель", "виробник")


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _compact(value: Any) -> str:
    return re.sub(r"[^0-9A-Za-zА-Яа-яІіЇїЄєҐґ]", "", str(value or "")).casefold()


def _first(data: dict[str, Any], keys: Iterable[str]) -> str | None:
    lowered = {str(k).lower(): v for k, v in data.items()}
    for key in keys:
        value = _clean(lowered.get(key))
        if value:
            return value
    return None


def _identifier_pattern(value: str) -> re.Pattern[str] | None:
    parts = re.findall(r"[0-9A-Za-zА-Яа-яІіЇїЄєҐґ]+", str(value or ""), re.I)
    if not parts:
        return None
    joined = r"[\s._/+:-]*".join(re.escape(part) for part in parts)
    return re.compile(rf"(?<!\w){joined}(?!\w)", re.I)


def identifier_in_text(identifier: str, text: str) -> bool:
    """Boundary-aware identifier match tolerant of common SKU separators."""
    pattern = _identifier_pattern(identifier)
    return bool(pattern and pattern.search(str(text or "")))


def article_is_published(mission: ProductMission) -> bool:
    """Whether the row article is visibly present in public identity data.

    This is validation metadata only. It must never make the supplier article a
    Discovery query. Discovery identifies the physical product from descriptive
    fields and explicit external identifiers such as MPN/EAN/GTIN/model.
    """
    article = _clean(mission.article)
    if len(_compact(article)) < 4:
        return False
    data = {str(k).lower(): v for k, v in mission.source_data.items()}
    name = _first(data, _NAME_KEYS)
    if name and identifier_in_text(article, name):
        return True
    for key in _ID_KEYS:
        value = _clean(data.get(key))
        if value and _compact(value) == _compact(article):
            return True
    return False


def _without_identifier(text: str, identifier: str) -> str:
    pattern = _identifier_pattern(identifier)
    if not pattern:
        return _clean(text)
    value = pattern.sub(" ", str(text or ""))
    value = re.sub(r"\(\s*\)|\[\s*\]|\{\s*\}", " ", value)
    return _clean(value)


def extract_identifiers(mission: ProductMission) -> list[str]:
    """Return external product identifiers, explicitly excluding row article."""
    data = {str(k).lower(): v for k, v in mission.source_data.items()}
    found = []
    article_compact = _compact(mission.article)

    for key in _ID_KEYS:
        value = _clean(data.get(key))
        if value and _compact(value) != article_compact and value not in found:
            found.append(value)

    corpus = " ".join(_clean(v) for v in mission.source_data.values() if isinstance(v, (str, int)))
    for token in re.findall(r"\b(?=[A-ZА-ЯІЇЄ0-9-]{4,}\b)(?=[A-ZА-ЯІЇЄ0-9-]*\d)[A-ZА-ЯІЇЄ0-9-]+\b", corpus.upper()):
        if _compact(token) != article_compact and token not in found:
            found.append(token)
    return found[:12]


def generate_queries(mission: ProductMission) -> list[str]:
    """Build Discovery queries without ever using the supplier row article.

    `mission.article` is a row/mission anchor. We strip it from descriptive text
    even when the supplier printed it inside the product name. Search is driven
    by name/brand plus independent external identifiers (MPN/EAN/GTIN/model/etc.).
    """
    data = mission.source_data
    name = _first(data, _NAME_KEYS)
    brand = _first(data, _BRAND_KEYS)
    identifiers = extract_identifiers(mission)
    queries: list[str] = []

    def add(value: Any) -> None:
        value = _clean(value)
        if mission.article and identifier_in_text(mission.article, value):
            value = _without_identifier(value, mission.article)
        if not value:
            return
        folded = value.casefold()
        if folded not in {q.casefold() for q in queries}:
            queries.append(value)

    # The descriptive name remains useful; only the supplier article is removed.
    add(name)

    # Independent product identifiers are valid Discovery signals. The row
    # article itself has already been excluded by extract_identifiers().
    for identifier in identifiers[:6]:
        add(identifier)
        if brand:
            add(f"{brand} {identifier}")

    if brand and name:
        add(" ".join([brand, *name.split()[:7]]))

    return queries[:12]
