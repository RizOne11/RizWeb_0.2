from __future__ import annotations

import re
from typing import Iterable


# Ported from the proven priceintel matcher. Marketplace titles frequently use
# a sub-brand/family token even when the supplier feed stores the parent brand.
BRAND_ALIASES = {
    "xiaomi": {"xiaomi", "redmi", "poco", "mi"},
    "huawei": {"huawei", "honor"},
    "samsung": {"samsung", "galaxy"},
}


def brand_aliases(brand: str | None) -> set[str]:
    value = re.sub(r"[^0-9a-zа-яіїєґ]+", "", str(brand or "").casefold(), flags=re.I)
    if not value:
        return set()
    for canonical, aliases in BRAND_ALIASES.items():
        compact_aliases = {
            re.sub(r"[^0-9a-zа-яіїєґ]+", "", alias.casefold(), flags=re.I)
            for alias in aliases | {canonical}
        }
        if value in compact_aliases:
            return aliases | {canonical}
    return {str(brand or "").strip()} if str(brand or "").strip() else set()


# This is the RU/UA equivalence table that the older priceintel matcher used to
# stop identical products losing score merely because the supplier title was
# Russian and the marketplace title was Ukrainian.
UA_TO_RU = {
    "монітор": "монитор",
    "багатофункціональний": "многофункциональный",
    "багатофункціональною": "многофункциональной",
    "підставка": "подставка",
    "підставкою": "подставкой",
    "ігровий": "игровой",
    "ігрова": "игровая",
    "навушники": "наушники",
    "клавіатура": "клавиатура",
    "миша": "мышь",
    "екран": "экран",
    "зарядний": "зарядное",
    "пристрій": "устройство",
    "чохол": "чехол",
    "відеокарта": "видеокарта",
    "процесор": "процессор",
    "пам'ять": "память",
    "жорсткий": "жесткий",
    "диск": "диск",
    "живлення": "питание",
    "мікрофон": "микрофон",
    "гарнітура": "гарнитура",
    "роз'єм": "разъем",
    "функція": "функция",
    "новий": "новый",
    "оригінал": "оригинал",
    "гарантія": "гарантия",
    "чорний": "черный",
    "білий": "белый",
    "сірий": "серый",
    "синій": "синий",
    "зелений": "зеленый",
    "жовтий": "желтый",
    "рожевий": "розовый",
    "срібний": "серебристый",
    "золотий": "золотой",
    "червоний": "красный",
    # Useful category words that were implicit in the old matching flow and
    # materially improve article-free discovery on Ukrainian storefronts.
    "обігрівач": "обогреватель",
    "керамічний": "керамический",
    "бездротовий": "беспроводной",
    "бездротові": "беспроводные",
    "генератор": "генератор",
    "інверторний": "инверторный",
    "комплект": "комплект",
    "набір": "набор",
}

# Reverse only one-to-one terms. Model/brand/numeric tokens are untouched.
RU_TO_UA = {}
for ua, ru in UA_TO_RU.items():
    RU_TO_UA.setdefault(ru, ua)


_WORD_RE = re.compile(r"[A-Za-zА-Яа-яІіЇїЄєҐґ']+", re.UNICODE)


def _replace_words(text: str, mapping: dict[str, str]) -> str:
    changed = False

    def repl(match: re.Match[str]) -> str:
        nonlocal changed
        word = match.group(0)
        replacement = mapping.get(word.casefold())
        if not replacement or replacement == word.casefold():
            return word
        changed = True
        return replacement

    result = _WORD_RE.sub(repl, str(text or ""))
    return result if changed else str(text or "")


def query_language_variants(text: str) -> list[str]:
    """Return original plus RU↔UA lexical query variants.

    This is deliberately a deterministic dictionary transform, not machine
    translation: it cannot mutate model codes, brands, dimensions or SKU-like
    identifiers and therefore is safe for identity-sensitive discovery.
    """
    original = re.sub(r"\s+", " ", str(text or "")).strip()
    if not original:
        return []

    out = [original]
    for mapping in (UA_TO_RU, RU_TO_UA):
        variant = re.sub(r"\s+", " ", _replace_words(original, mapping)).strip()
        if variant and variant.casefold() not in {x.casefold() for x in out}:
            out.append(variant)
    return out


def fold_ru_ua_tokens(text: str) -> str:
    """Canonicalise Ukrainian lexical equivalents to the legacy RU token form."""
    return re.sub(r"\s+", " ", _replace_words(str(text or ""), UA_TO_RU)).strip()
