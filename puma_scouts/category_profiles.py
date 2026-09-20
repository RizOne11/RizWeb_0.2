from __future__ import annotations

import re
from dataclasses import dataclass, field

from puma_scouts.models import ProductMission
from puma_scouts.lingua import fold_homoglyphs

GENERIC = "generic"
COMPUTER_VARIANT = "computer_variant"
CONSUMABLE_MULTIPACK = "consumable_multipack"
CABLE_LENGTH_VARIANT = "cable_length_variant"
ENERGY_POWER = "energy_power"
WEARABLE_MODEL_VARIANT = "wearable_model_variant"
APPAREL_SIZE_VARIANT = "apparel_size_variant"


@dataclass(frozen=True)
class CategoryAssessment:
    profile: str = GENERIC
    conflicts: tuple[str, ...] = field(default_factory=tuple)
    missing_critical: tuple[str, ...] = field(default_factory=tuple)


def _norm(value: object) -> str:
    return re.sub(r"\s+", " ", fold_homoglyphs(value)).strip()


def _source_text(mission: ProductMission) -> str:
    keys = {"name", "title", "product_name", "назва", "наименование", "description", "category", "type"}
    values = [
        str(value) for key, value in mission.source_data.items()
        if str(key).casefold() in keys and str(value or "").strip()
    ]
    return " ".join(values) if values else " ".join(str(v) for v in mission.source_data.values())


def _pack_quantity(text: str) -> int | None:
    raw = _norm(text)
    for pattern in (
        r"(?<!\d)(\d{1,3})\s*(?:шт\.?|штук\w*|pcs\.?|pieces\b)",
        r"\b(?:упаковк\w*|пачк\w*|набор\w*|набір\w*|комплект\w*|pack)\s*(?:из|з|of)?\s*(\d{1,3})\b",
    ):
        match = re.search(pattern, raw, re.I)
        if match:
            return int(match.group(1))
    return None


def _lengths_m(text: str) -> set[float]:
    raw = _norm(text)
    out = {
        float(value.replace(",", "."))
        for value in re.findall(r"(?<![a-zа-яіїє0-9])(\d+(?:[.,]\d+)?)\s*(?:м|m|метр\w*)(?![a-zа-яіїє])", raw, re.I)
    }
    out |= {
        float(value.replace(",", "."))
        for value in re.findall(r"[a-z0-9]+[-_/](\d+(?:[.,]\d+)?)m\b", raw, re.I)
    }
    return {value for value in out if 0 < value <= 1000}


_APPAREL_RE = re.compile(
    r"\b(?:"
    r"куртк\w*|шорт\w*|купальник\w*|бель[еёя]\w*|пижам\w*|піжам\w*|"
    r"футболк\w*|толстовк\w*|худ[иі]\w*|джинс\w*|брюк\w*|штан\w*|"
    r"термобель\w*|термобілизн\w*|кепк\w*|шапк\w*|сукн\w*|плать\w*|"
    r"ботинк\w*|черевик\w*|бутс\w*|шиповк\w*|кроссовк\w*|кросівк\w*|"
    r"туфл\w*|сандал\w*|clothing|shirt|t-?shirt|hoodie|jacket|shorts|"
    r"swimsuit|lingerie|pajamas?|pyjamas?|jeans|pants|shoes?|sneakers?|boots?"
    r")\b",
    re.I,
)
_FOOTWEAR_RE = re.compile(
    r"\b(?:ботинк\w*|черевик\w*|бутс\w*|шиповк\w*|кроссовк\w*|кросівк\w*|"
    r"туфл\w*|сандал\w*|shoes?|sneakers?|boots?)\b",
    re.I,
)
_ALPHA_SIZE_RE = re.compile(
    r"(?<![a-zа-яіїєґ0-9])(?:5xl|4xl|3xl|2xl|xxxl|xxl|xl|l|m|s|xs|xxs|xxxs)(?![a-zа-яіїєґ0-9])",
    re.I,
)
_BRA_SIZE_RE = re.compile(
    r"(?<!\d)(?:60|65|70|75|80|85|90|95|100|105|110)\s*[/ -]?\s*(?:aa|a|b|c|d|e|f|g)(?![a-z])",
    re.I,
)


def _apparel_sizes(text: str) -> set[str]:
    raw = _norm(text)
    if not _APPAREL_RE.search(raw):
        return set()

    out = {match.group(0).casefold().replace(" ", "") for match in _ALPHA_SIZE_RE.finditer(raw)}
    out |= {
        re.sub(r"[\s/-]+", "", match.group(0).casefold())
        for match in _BRA_SIZE_RE.finditer(raw)
    }

    # Numeric sizes need stronger context than XS/M/XL. Footwear commonly
    # publishes a bare EU size ("... 43 Red"), while garment numbers are only
    # trusted when explicitly labelled. Never take suffixes from SKU/model codes
    # such as (186Pj-35) as a size.
    if _FOOTWEAR_RE.search(raw):
        for value in re.findall(r"(?<![\w/_-])(\d{2})(?![\w/_-])", raw):
            if 34 <= int(value) <= 50:
                out.add(value)
    for value in re.findall(
        r"\b(?:розмір|размер|size)\s*[:#-]?\s*(\d{2})(?!\d)",
        raw,
        re.I,
    ):
        if 34 <= int(value) <= 64:
            out.add(value)

    return out


def classify_category(mission: ProductMission) -> str:
    text = _norm(_source_text(mission))
    if re.search(r"\b(?:ноутбук|laptop|комп(?:ьютер|'ютер)|desktop|thinkpad|optiplex|latitude)\b", text, re.I):
        return COMPUTER_VARIANT
    if _APPAREL_RE.search(text) and _apparel_sizes(text):
        return APPAREL_SIZE_VARIANT
    quantity = _pack_quantity(text)
    if quantity and quantity > 1 and re.search(r"\b(?:газов\w*\s+балл?он\w*|балл?он\w*\s+газов\w*|балон\w*\s+газов\w*)\b", text, re.I):
        return CONSUMABLE_MULTIPACK
    if re.search(r"\b(?:кабель|кабел[ья]|cable|шнур|cord|шланг|hose)\b", text, re.I) and _lengths_m(text):
        return CABLE_LENGTH_VARIANT
    if re.search(r"\b(?:инвертор|інвертор|inverter|generator|генератор|павербанк|повербанк|powerbank|power bank|power station)\b", text, re.I):
        return ENERGY_POWER
    if re.search(r"\b(?:смарт[-\s]?часы|смарт[-\s]?годинник\w*|smartwatch|smart watch)\b", text, re.I):
        return WEARABLE_MODEL_VARIANT
    return GENERIC


def _cpu(text: str) -> set[str]:
    raw = _norm(text)
    out = set()
    for family, number, suffix in re.findall(r"\b(i[3579])[-\s]?(\d{4,5})([a-z]{0,3})\b", raw, re.I):
        out.add((family + number + suffix).casefold())
    for family, number, suffix in re.findall(r"\b(ryzen\s*[3579])[-\s]?(\d{4,5})([a-z]{0,3})\b", raw, re.I):
        out.add(re.sub(r"\s+", "", family + number + suffix).casefold())
    return out


def _slash_specs(text: str) -> list[tuple[int, int]]:
    raw = _norm(text)
    out = []
    pattern = r"/\s*(\d{1,3})\s*/\s*(\d{2,4}|\d+(?:[.,]\d+)?)\s*(tb|тб|gb|гб)?\s*(?:ssd|hdd|nvme)"
    for ram, storage, unit in re.findall(pattern, raw, re.I):
        value = float(storage.replace(",", "."))
        storage_gb = int(round(value * 1024)) if unit.casefold() in {"tb", "тб"} else int(round(value))
        out.append((int(ram), storage_gb))
    return out


def _ram(text: str) -> set[int]:
    raw = _norm(text)
    out = {ram for ram, _ in _slash_specs(raw)}
    for pattern in (
        r"\b(?:ram|озу)\s*[:=-]?\s*(\d{1,3})\s*(?:gb|гб)\b",
        r"\b(?:ddr[345]?)\s*(\d{1,3})\s*(?:gb|гб)\b",
        r"\b(\d{1,3})\s*(?:gb|гб)\s*(?:ram|озу|ddr[345]?)\b",
    ):
        out |= {int(v) for v in re.findall(pattern, raw, re.I)}
    return {v for v in out if 1 <= v <= 256}


def _storage(text: str) -> set[int]:
    raw = _norm(text)
    out = {storage for _, storage in _slash_specs(raw)}
    for value, unit in re.findall(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(tb|тб|gb|гб)?\s*(?:ssd|hdd|nvme)\b", raw, re.I):
        n = float(value.replace(",", "."))
        out.add(int(round(n * 1024)) if unit.casefold() in {"tb", "тб"} else int(round(n)))
    for value, unit in re.findall(r"\b(?:ssd|hdd|nvme)\s*[:=-]?\s*(\d+(?:[.,]\d+)?)\s*(tb|тб|gb|гб)\b", raw, re.I):
        n = float(value.replace(",", "."))
        out.add(int(round(n * 1024)) if unit.casefold() in {"tb", "тб"} else int(round(n)))
    return {v for v in out if 16 <= v <= 16384}


def _form_factor(text: str) -> set[str]:
    raw = _norm(text)
    out = set()
    if re.search(r"\bsff\b|small\s+form\s+factor", raw, re.I):
        out.add("sff")
    if re.search(r"\bmt\b|mini\s+tower", raw, re.I):
        out.add("mt")
    if re.search(r"\bmff\b|micro\s+form\s+factor", raw, re.I):
        out.add("mff")
    return out


def _is_computer_accessory(text: str) -> bool:
    raw = _norm(text)
    markers = (
        "зарядное устройство", "зарядний пристрій", "charger",
        "блок питания", "блок живлення", "power supply",
        "клавиатура", "клавіатура", "keyboard",
        "аккумулятор для", "акумулятор для", "battery for",
        "матрица для", "матриця для", "screen for",
        "док-станция", "док станция", "dock station",
    )
    return any(marker in raw for marker in markers)


def _compare(label: str, expected: set, actual: set) -> tuple[list[str], list[str]]:
    if not expected:
        return [], []
    if not actual:
        return [], [label]
    if expected.isdisjoint(actual):
        return [f"{label} mismatch: expected {sorted(expected)}, got {sorted(actual)}"], []
    return [], []


def _computer_assessment(source: str, candidate: str) -> CategoryAssessment:
    conflicts: list[str] = []
    missing: list[str] = []
    if _is_computer_accessory(candidate) and not _is_computer_accessory(source):
        conflicts.append("category computer_variant: candidate is laptop/computer accessory or component")
    for label, extractor in (("cpu", _cpu), ("RAM", _ram), ("storage", _storage), ("form factor", _form_factor)):
        c, m = _compare(label, extractor(source), extractor(candidate))
        conflicts.extend(c)
        missing.extend(m)
    if bool(re.search(r"\byoga\b", source, re.I)) != bool(re.search(r"\byoga\b", candidate, re.I)):
        if "yoga" in source or "yoga" in candidate:
            conflicts.append("computer subfamily mismatch: Yoga vs non-Yoga")
    return CategoryAssessment(COMPUTER_VARIANT, tuple(dict.fromkeys(conflicts)), tuple(dict.fromkeys(missing)))


def _multipack_assessment(source: str, candidate: str) -> CategoryAssessment:
    expected = _pack_quantity(source)
    actual = _pack_quantity(candidate)
    conflicts: list[str] = []
    missing: list[str] = []
    if expected:
        if actual is None:
            missing.append("pack quantity")
        elif actual != expected:
            conflicts.append(f"pack quantity mismatch: expected {expected}, got {actual}")
    return CategoryAssessment(CONSUMABLE_MULTIPACK, tuple(conflicts), tuple(missing))


def _cable_assessment(source: str, candidate: str) -> CategoryAssessment:
    expected = _lengths_m(source)
    actual = _lengths_m(candidate)
    if expected and actual and expected.isdisjoint(actual):
        return CategoryAssessment(
            CABLE_LENGTH_VARIANT,
            (f"cable length mismatch: expected {sorted(expected)}m, got {sorted(actual)}m",),
            (),
        )
    if expected and not actual:
        return CategoryAssessment(CABLE_LENGTH_VARIANT, (), ("length",))
    return CategoryAssessment(CABLE_LENGTH_VARIANT)


def _apparel_assessment(source: str, candidate: str) -> CategoryAssessment:
    expected = _apparel_sizes(source)
    actual = _apparel_sizes(candidate)
    if expected and actual and expected.isdisjoint(actual):
        return CategoryAssessment(
            APPAREL_SIZE_VARIANT,
            (f"apparel size mismatch: expected {sorted(expected)}, got {sorted(actual)}",),
            (),
        )
    if expected and not actual:
        return CategoryAssessment(APPAREL_SIZE_VARIANT, (), ("apparel size",))
    return CategoryAssessment(APPAREL_SIZE_VARIANT)



def _power_w(text: str) -> set[int]:
    raw = _norm(text)
    out: set[int] = set()
    for value, unit in re.findall(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(квт|kw|вт|w)\b", raw, re.I):
        number = float(value.replace(",", "."))
        watts = int(round(number * 1000)) if unit.casefold() in {"квт", "kw"} else int(round(number))
        if 50 <= watts <= 100000:
            out.add(watts)
    return out


def _voltage_v(text: str) -> set[float]:
    raw = _norm(text)
    out: set[float] = set()
    for value in re.findall(r"(?<!\d)(\d{1,3}(?:[.,]\d+)?)\s*(?:v|в)\b", raw, re.I):
        number = float(value.replace(",", "."))
        if 1 <= number <= 1000:
            out.add(number)
    return out


def _energy_editions(text: str) -> set[str]:
    raw = _norm(text)
    out: set[str] = set()
    for token in ("eco", "pro"):
        if re.search(rf"\b{token}\b", raw, re.I):
            out.add(token)
    return out


def _energy_bundle(text: str) -> bool:
    raw = _norm(text)
    markers = (
        "в сборе", "у зборі", "с аккумулятор", "з акумулятор",
        "аккумулятор", "акумулятор", "с батаре", "з батаре", "battery",
        "автономная система", "автономна система", "система автономная", "система автономна",
        "system with battery", "bundle",
    )
    return any(marker in raw for marker in markers)


def _energy_assessment(source: str, candidate: str) -> CategoryAssessment:
    conflicts: list[str] = []
    missing: list[str] = []

    for label, extractor in (("power", _power_w), ("voltage", _voltage_v), ("energy edition", _energy_editions)):
        c, m = _compare(label, extractor(source), extractor(candidate))
        conflicts.extend(c)
        missing.extend(m)

    if _energy_bundle(candidate) and not _energy_bundle(source):
        conflicts.append("energy bundle mismatch: candidate includes battery/system bundle")

    return CategoryAssessment(
        ENERGY_POWER,
        tuple(dict.fromkeys(conflicts)),
        tuple(dict.fromkeys(missing)),
    )


def _wearable_models(text: str) -> set[str]:
    raw = _norm(text)
    out: set[str] = set()
    for family, model in re.findall(r"\b(magic|tank)\s+([a-z]\d{1,3})\b", raw, re.I):
        out.add((family + model).casefold())
    return out


def _wearable_skus(text: str) -> set[str]:
    raw = _norm(text)
    return {
        token.casefold()
        for token in re.findall(r"\b(k[a-z]{2}\d{4,}[a-z0-9]*)\b", raw, re.I)
    }


def _special_edition(text: str) -> bool:
    return bool(re.search(r"\bspecial\s+edition\b|\bспец(?:иальная|іальна)\s+верс", _norm(text), re.I))


def _wearable_assessment(source: str, candidate: str) -> CategoryAssessment:
    conflicts: list[str] = []
    missing: list[str] = []

    expected_models = _wearable_models(source)
    actual_models = _wearable_models(candidate)
    if expected_models:
        if not actual_models:
            missing.append("wearable model")
        elif expected_models.isdisjoint(actual_models):
            conflicts.append(
                f"wearable model mismatch: expected {sorted(expected_models)}, got {sorted(actual_models)}"
            )

    expected_skus = _wearable_skus(source)
    actual_skus = _wearable_skus(candidate)
    if expected_skus:
        if not actual_skus:
            missing.append("wearable SKU")
        elif expected_skus.isdisjoint(actual_skus):
            conflicts.append(
                f"wearable SKU mismatch: expected {sorted(expected_skus)}, got {sorted(actual_skus)}"
            )

    source_special = _special_edition(source)
    candidate_special = _special_edition(candidate)
    if source_special != candidate_special:
        if candidate_special or actual_skus:
            conflicts.append("wearable edition mismatch: Special Edition vs base/other edition")
        else:
            missing.append("wearable edition")

    return CategoryAssessment(
        WEARABLE_MODEL_VARIANT,
        tuple(dict.fromkeys(conflicts)),
        tuple(dict.fromkeys(missing)),
    )


def assess_category(mission: ProductMission, offer_text: str) -> CategoryAssessment:
    profile = classify_category(mission)
    source = _norm(_source_text(mission))
    candidate = _norm(offer_text)
    if profile == COMPUTER_VARIANT:
        return _computer_assessment(source, candidate)
    if profile == CONSUMABLE_MULTIPACK:
        return _multipack_assessment(source, candidate)
    if profile == CABLE_LENGTH_VARIANT:
        return _cable_assessment(source, candidate)
    if profile == APPAREL_SIZE_VARIANT:
        return _apparel_assessment(source, candidate)
    if profile == ENERGY_POWER:
        return _energy_assessment(source, candidate)
    if profile == WEARABLE_MODEL_VARIANT:
        return _wearable_assessment(source, candidate)
    return CategoryAssessment()
