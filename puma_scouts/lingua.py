from __future__ import annotations

import re
import unicodedata
from typing import Iterable


# Canonical identity folding for marketplace/supplier text. It deliberately
# folds only identifier-like mixed-script/alphanumeric tokens, leaving normal
# Cyrillic prose untouched.
_HOMOGLYPH_CYR_TO_LAT = {
    "а": "a",
    "в": "b",
    "е": "e",
    "к": "k",
    "м": "m",
    "н": "h",
    "о": "o",
    "р": "p",
    "с": "c",
    "т": "t",
    "х": "x",
    "у": "y",
    "і": "i",
}
_HOMOGLYPH_LAT_VARIANTS = {
    "a": "aа",
    "b": "bв",
    "e": "eе",
    "k": "kк",
    "m": "mм",
    "h": "hн",
    "o": "oо",
    "p": "pр",
    "c": "cс",
    "t": "tт",
    "x": "xх×",
    "y": "yу",
    "i": "iі",
}
_IDENTITY_TOKEN_RE = re.compile(r"[0-9A-Za-zА-Яа-яІіЇїЄєҐґ]+", re.UNICODE)


def _fold_identity_token(match: re.Match[str]) -> str:
    token = match.group(0).casefold()
    has_latin = bool(re.search(r"[a-z]", token))
    cyrillic = re.findall(r"[а-яіїєґ]", token, re.I)
    has_cyrillic = bool(cyrillic)
    has_digit = bool(re.search(r"\d", token))

    # Mixed Latin/Cyrillic tokens are almost always marketplace homoglyph
    # contamination (EPСС2614, MВS-4708, NІKE). Pure Cyrillic prose stays
    # untouched. Pure-Cyrillic alphanumeric codes are folded only when every
    # Cyrillic letter has an unambiguous visual Latin counterpart.
    should_fold = has_latin and has_cyrillic
    if has_digit and has_cyrillic and all(ch.casefold() in _HOMOGLYPH_CYR_TO_LAT for ch in cyrillic):
        should_fold = True
    if not should_fold:
        return token

    return "".join(_HOMOGLYPH_CYR_TO_LAT.get(ch, ch) for ch in token)


def fold_homoglyphs(value: object) -> str:
    """Return a stable matcher representation for mixed-script identity text.

    Numeric dimensions also use one canonical separator, so 129 х 90,
    129 × 90 and 129x90 compare equally.
    """
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[‐‑‒–—−]", "-", text)
    text = re.sub(r"(?<=\d)\s*[xх×]\s*(?=\d)", "x", text, flags=re.I)
    text = _IDENTITY_TOKEN_RE.sub(_fold_identity_token, text)
    return re.sub(r"\s+", " ", text).strip()


def canonical_compact(value: object) -> str:
    return re.sub(r"[^0-9a-zа-яіїєґ]", "", fold_homoglyphs(value), flags=re.I)


def identity_pattern(value: object) -> re.Pattern[str] | None:
    """Build a boundary-aware raw-text regex from canonical identity text."""
    canonical = fold_homoglyphs(value)
    parts = re.findall(r"[0-9a-zа-яіїєґ]+", canonical, re.I)
    if not parts:
        return None

    def part_pattern(part: str) -> str:
        out: list[str] = []
        for index, char in enumerate(part):
            if (
                char == "x"
                and index > 0
                and index + 1 < len(part)
                and part[index - 1].isdigit()
                and part[index + 1].isdigit()
            ):
                out.append(r"\s*[xх×]\s*")
                continue
            variants = _HOMOGLYPH_LAT_VARIANTS.get(char)
            out.append(f"[{re.escape(variants)}]" if variants else re.escape(char))
        return "".join(out)

    joined = r"[\s._/+:-]*".join(part_pattern(part) for part in parts)
    return re.compile(rf"(?<!\w){joined}(?!\w)", re.I | re.UNICODE)


# Ported from the proven priceintel matcher. Marketplace titles frequently use
# a sub-brand/family token even when the supplier feed stores the parent brand.
BRAND_ALIASES = {
    "xiaomi": {"xiaomi", "redmi", "poco", "mi"},
    "huawei": {"huawei", "honor"},
    "samsung": {"samsung", "galaxy"},
}


def brand_aliases(brand: str | None) -> set[str]:
    value = canonical_compact(brand)
    if not value:
        return set()
    for canonical, aliases in BRAND_ALIASES.items():
        compact_aliases = {
            canonical_compact(alias)
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
    return re.sub(r"\s+", " ", _replace_words(fold_homoglyphs(text), UA_TO_RU)).strip()
