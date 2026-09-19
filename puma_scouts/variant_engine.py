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
    "headphones": r"\b(?:навушники|наушники|гарнітура|гарнитура|headphones|headset|earbuds|airpods)\b",
    "television": r"\b(?:телевізор|телевизор|television|tv)\b",
    "laptop": r"\b(?:ноутбук|laptop)\b",
    "tablet": r"\b(?:планшет|tablet)\b",
    "ssd": r"\b(?:ssd|твердотільн\w+ накопичувач|твердотельн\w+ накопитель)\b",
    "hdd": r"\b(?:hdd|жорстк\w+ диск|жестк\w+ диск)\b",
    "tire": r"\b(?:шина|шини|шины|tyre|tire)\b",
    "clothing": r"\b(?:футболка|сорочка|рубашка|куртка|штани|брюки|сукня|платье|hoodie|t-shirt|кросівки|кроссовки|взуття|обувь|shoes|sneakers)\b",
    "perfume": r"\b(?:парфум|парфюм|туалетн\w+ вод|eau de|perfume)\b",
}

_PART_PATTERNS = {
    "spare_part": r"\b(?:шлейф|flex cable|запчаст\w*|spare part|дисплейн\w+ модул\w*|дисплей\s+(?:модул\w*|для\b)|display\s+(?:module|replacement|for\b)|екран\s+(?:модул\w*|для\b)|экран\s+(?:модул\w*|для\b)|screen\s+(?:module|replacement|for\b)|тачскрин\w*|touchscreen\s+(?:module|replacement|for\b)|сенсор\s+(?:для\b|модул\w*)|матриц[аы]\s+(?:для\b|модул\w*)|акумулятор\s+для\b|аккумулятор\s+для\b|battery\s+(?:replacement|for\b)|материнск\w+ плат\w*|motherboard|задн\w+ кришк\w*|задн\w+ крышк\w*)\b",
    "accessory": r"\b(?:чохол\w*|чехол\w*|бампер\w*|захисн\w+ скло|защитн\w+ стекло|захисн\w+ плівк\w*|защитн\w+ пленк\w*|гідрогел\w*|гидрогел\w*|ремінець\w*|ремешок\w*|адаптер\w*|перехідник\w*|переходник\w*|usb hub|хаб)\b",
    "component": r"\b(?:лів(?:ий|а)|прав(?:ий|а)|лев(?:ый|ая)|прав(?:ый|ая)|left|right)\s+(?:навушник\w*|наушник\w*|earbud\w*)\b|\b(?:no[- ]?box|без\s+(?:кейса|футляра|зарядн\w+ кейса))\b",
}

_COLOR_GROUPS = {
    "black":{"black","чорний","чорна","черный","черная"},
    "white":{"white","білий","біла","белый","белая"},
    "blue":{"blue","синій","синя","блакитний","блакитна","синий","синяя","голубой","голубая"},
    "green":{"green","зелений","зелена","зеленый","зеленая"},
    "red":{"red","червоний","червона","красный","красная"},
    "yellow":{"yellow","жовтий","жовта","желтый","желтая"},
    "violet":{"violet","purple","фіолетовий","фіолетова","фиолетовый","фиолетовая"},
    "pink":{"pink","рожевий","рожева","розовый","розовая"},
    "gold":{"gold","золотий","золотой"},
    "silver":{"silver","срібний","сріблястий","серебристый","серебряный"},
    "gray":{"gray","grey","сірий","сіра","серый","серая"},
    "orange":{"orange","помаранчевий","помаранчева","оранжевый","оранжевая"},
    "brown":{"brown","коричневий","коричнева","коричневый","коричневая"},
    "beige":{"beige","бежевий","бежева","бежевый","бежевая"},
}
_COLOR_WORDS=set().union(*_COLOR_GROUPS.values())
_STOP = {"смартфон","smartphone","монітор","монитор","monitor","навушники","наушники","гарнітура","гарнитура","headphones","headset","earbuds","телевізор","телевизор","ноутбук","laptop","планшет","tablet","apple","samsung","xiaomi","redmi","galaxy","pro","plus","max","gen","generation","with","case","gb","гб","5g","lte","2k","4k","ips","hdr10","usb","type","charging","magsafe"}|_COLOR_WORDS


def entity_type(text: str) -> str | None:
    t = norm(text)
    for entity, pattern in _PART_PATTERNS.items():
        if re.search(pattern, t, re.I): return entity
    for entity, pattern in _ENTITY_PATTERNS.items():
        if re.search(pattern, t, re.I): return entity
    return None


def _colors(text:str)->set[str]:
    words=set(norm(text).split());return {canonical for canonical,aliases in _COLOR_GROUPS.items() if words & aliases}

def _memory(text: str) -> tuple[set[int], set[int]]:
    raw=str(text or "").casefold();ram=set();storage=set()
    for a,b in re.findall(r"(?<!\d)(\d{1,2})\s*[/+]\s*(\d{2,4})\s*(?:gb|гб)?\b",raw,re.I): ram.add(int(a));storage.add(int(b))
    for value,unit in re.findall(r"(?<!\d)(\d{1,4})\s*(gb|гб|tb|тб)\b",raw,re.I):
        n=int(value)*(1024 if unit.casefold() in {"tb","тб"} else 1)
        if n>=32:storage.add(n)
    return ram,storage


def _display_diagonal(text:str)->str|None:
    raw=str(text or "").casefold();m=re.search(r"\b(2[0-9]|3[0-9]|4[0-9]|5[0-9]|6[0-9]|7[0-9]|8[0-9]|9[0-9]|1[0-2][0-9])\s*(?:дюйм\w*|inch(?:es)?|\")?\s*$",raw,re.I);return "diag:"+m.group(1) if m else None

def _sizes(text:str)->set[str]:
    raw=str(text or "").casefold();out=set()
    for value in re.findall(r"(?<!\d)(\d{1,3}(?:[.,]\d+)?)\s*(?:inch|inches|дюйм\w*|\")",raw,re.I):out.add(value.replace(",",".")+"in")
    for value,unit in re.findall(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(mm|мм|cm|см|ml|мл|kg|кг)\b",raw,re.I):out.add(value.replace(",",".")+unit.casefold())
    for value in re.findall(r"\b(?:розмір|размер|size)\s*[:#-]?\s*(\d{1,3}(?:[.,]\d+)?)\b",raw,re.I):out.add("size:"+value.replace(",","."))
    for width,profile,rim in re.findall(r"(?<!\d)(\d{3})\s*/\s*(\d{2})\s*r\s*(\d{2})(?!\d)",raw,re.I):out.add(f"tire:{width}/{profile}r{rim}")
    if entity_type(raw) in {"television","monitor"}:
        d=_display_diagonal(raw)
        if d:out.add(d)
    return out

def _core_tokens(text:str)->set[str]:
    raw=norm(text);out=set()
    for token in raw.split():
        c=re.sub(r"[^a-zа-яіїє0-9]","",token,re.I)
        if not c or c in _STOP or c in _COLOR_WORDS:continue
        if re.fullmatch(r"\d{1,4}(?:gb|гб|tb|тб)",c,re.I):continue
        if re.fullmatch(r"20\d{2}",c) or re.fullmatch(r"\d+(?:hz|гц)?",c):continue
        if re.fullmatch(r"\d+(?:a|v|w|mah|ah|wh|hz|гц|мм|mm|см|cm|мл|ml|кг|kg|вт|квт|ква)",c,re.I):continue
        if re.search(r"[a-zа-яіїє]",c,re.I) and re.search(r"\d",c):out.add(c)

    # Normalize split model families such as "SGN 125" -> "sgn125".
    # This lets the identity gate compare them with compact/hyphenated forms
    # such as "SGR-70" without turning standards/measurements into models.
    ignored_prefixes={"din","iso","iec","en","mah","ah","wh","hz","mm","cm","kg","kw","kva","volt","model"}
    for prefix,number in re.findall(r"\b([a-z]{2,10})\s*[-_/]?\s*(\d{2,5})\b",raw,re.I):
        p=prefix.casefold()
        if p in ignored_prefixes:continue
        out.add(re.sub(r"[^a-z0-9]","",p+number,re.I))
    return out

def signature(text:str)->ProductSignature:
    ram,storage=_memory(text);return ProductSignature(entity=entity_type(text),core_tokens=frozenset(_core_tokens(text)),storage_gb=frozenset(storage),ram_gb=frozenset(ram),sizes=frozenset(_sizes(text)),colors=frozenset(_colors(text)))

def _short_family(tokens:frozenset[str])->set[str]:return {t for t in tokens if len(t)<=8 and re.search(r"[a-zа-яіїє]",t,re.I) and re.search(r"\d",t)}


_MODEL_CODE_STOP_PREFIXES={"din","iso","iec","en","usb","wifi","lte","mah","ah","wh","hz","mm","cm","kg","kw","kva","volt","v","w"}

def _explicit_model_codes(text:str)->set[str]:
    """Extract explicit Latin model identifiers from visible product identity text."""
    raw=norm(text)
    out=set()

    # Compact/hyphenated model tokens: SGR-70, CHT-500, HQ53, TC1N, P27QCB-RA.
    for match in re.finditer(r"(?<!\w)([a-z][a-z0-9]*(?:[-_/][a-z0-9]+)*)(?!\w)",raw,re.I):
        token=match.group(1)
        compact=re.sub(r"[^a-z0-9]","",token.casefold())
        if not (re.search(r"[a-z]",compact) and re.search(r"\d",compact)):
            continue
        prefix=(re.match(r"[a-z]+",compact) or [None])[0]
        if prefix in _MODEL_CODE_STOP_PREFIXES:
            continue
        out.add(compact)

    # Spaced family + number: SGN 125 -> sgn125.
    for prefix,number in re.findall(r"\b([a-z]{2,10})\s+(\d{2,5})\b",raw,re.I):
        p=prefix.casefold()
        if p not in _MODEL_CODE_STOP_PREFIXES:
            out.add(p+number)

    # Some vendors publish a base model ending in a letter plus a numeric
    # variant suffix, e.g. TC1N 5887. Preserve the full pair as material identity.
    for base,suffix in re.findall(r"\b([a-z][a-z0-9]*\d[a-z])\s+(\d{3,6})\b",raw,re.I):
        compact=re.sub(r"[^a-z0-9]","",base.casefold())
        prefix=(re.match(r"[a-z]+",compact) or [None])[0]
        if prefix not in _MODEL_CODE_STOP_PREFIXES:
            out.add(compact+suffix)
    return out


def explicit_model_agreement(expected_text:str,candidate_text:str)->set[str]:
    """Return exact explicit model identifiers shared by source and candidate."""
    return _explicit_model_codes(expected_text) & _explicit_model_codes(candidate_text)


def _explicit_model_conflict(expected_text:str,candidate_text:str)->str|None:
    expected=_explicit_model_codes(expected_text)
    candidate=_explicit_model_codes(candidate_text)
    if not expected or not candidate:
        return None

    # Lock vendor suffixes such as TC1N 5887 vs TC1N 2247/2230.
    def compounds(codes:set[str])->dict[str,set[str]]:
        grouped={}
        for code in codes:
            m=re.fullmatch(r"([a-z][a-z0-9]*\d[a-z])(\d{3,6})",code,re.I)
            if m:
                grouped.setdefault(m.group(1),set()).add(code)
        return grouped

    eg,cg=compounds(expected),compounds(candidate)
    for base in set(eg)&set(cg):
        if eg[base].isdisjoint(cg[base]):
            return f"model variant mismatch: expected {sorted(eg[base])}, got {sorted(cg[base])}"

    # If both sides explicitly name model codes and none agree, this is a
    # material model-family conflict even when generic description overlaps.
    if expected.isdisjoint(candidate):
        return f"model family mismatch: expected {sorted(expected)}, got {sorted(candidate)}"
    return None


def _structured_numeric_codes(text: str) -> set[str]:
    """Extract compact public SKU-like numeric codes, avoiding year/date noise."""
    return {m.casefold() for m in re.findall(r"(?<!\d)\d{2,3}-\d{3,5}(?!\d)", str(text or ""))}


def _parenthetical_variant_codes(text: str) -> set[str]:
    """Extract code-like variant markers published in parentheses.

    Keep true product identifiers such as (49), (002-279), (TC1N 5887) and
    reject years, quantities and measurement notes.
    """
    out = set()
    units = re.compile(
        r"\b(?:шт|штук|pcs|pieces|pack|уп|упак|mm|мм|cm|см|ml|мл|kg|кг|gb|гб|tb|тб|w|вт|v|в|hz|гц)\b",
        re.I,
    )
    for value in re.findall(r"\(([^()]{1,24})\)", str(text or ""), re.I):
        raw = value.strip().casefold()
        if units.search(raw):
            continue
        compact = re.sub(r"[^a-zа-яіїє0-9]", "", raw, flags=re.I)
        if not compact or not re.search(r"\d", compact) or len(compact) > 20:
            continue
        if re.fullmatch(r"(?:19|20)\d{2}", compact):
            continue
        if re.fullmatch(r"\d{1,3}", compact):
            out.add(compact)
            continue
        if re.fullmatch(r"\d{2,3}\s*-\s*\d{3,5}", raw):
            out.add(compact)
            continue
        if re.search(r"[a-zа-яіїє]", compact, re.I) and len(re.findall(r"\d", compact)) >= 1:
            out.add(compact)
    return out


def _terminal_variant_conflict(expected_text: str, candidate_text: str) -> str | None:
    expected = _parenthetical_variant_codes(expected_text)
    candidate = _parenthetical_variant_codes(candidate_text)
    if expected and candidate and expected.isdisjoint(candidate):
        return f"terminal variant mismatch: expected {sorted(expected)}, got {sorted(candidate)}"
    return None


def _public_code_conflict(expected_text: str, candidate_text: str) -> str | None:
    expected_codes = _structured_numeric_codes(expected_text)
    candidate_codes = _structured_numeric_codes(candidate_text)
    if not expected_codes or not candidate_codes:
        return None
    if expected_codes & candidate_codes:
        return None

    parenthetical_expected = _parenthetical_variant_codes(expected_text)
    for expected in expected_codes:
        expected_compact = re.sub(r"[^a-zа-яіїє0-9]", "", expected, flags=re.I)
        if expected_compact in parenthetical_expected:
            candidate = sorted(candidate_codes)[0]
            return f"public article mismatch: expected {expected}, got {candidate}"

    for expected in expected_codes:
        expected_parts = expected.split("-", 1)
        for candidate in candidate_codes:
            candidate_parts = candidate.split("-", 1)
            if expected_parts[0] == candidate_parts[0] or expected_parts[1] == candidate_parts[1]:
                return f"public article mismatch: expected {expected}, got {candidate}"
    return None


def named_generations(text:str)->dict[str,int]:
    t=norm(text);out={};words=t.split()
    skip={"gb","гб","tb","тб","hz","гц","mm","мм","cm","см","ml","мл","usb","type","wifi","lte","розмір","размер","size"}
    units={"gb","гб","tb","тб","hz","гц","mm","мм","cm","см","ml","мл","kg","кг","w","вт","inch","inches","дюйм","дюйма","дюймов","дюйми","дюймів"}
    for i in range(len(words)-1):
        family=re.sub(r"[^a-zа-яіїє]","",words[i],flags=re.I);next_raw=words[i+1];nxt=re.sub(r"[^0-9]","",next_raw)
        if not family or family in skip or not nxt:continue
        # A mixed model token such as TC1N is an identifier, not "generation 1"
        # of the preceding word (e.g. "Черный TC1N").
        if re.search(r"[a-zа-яіїє]",next_raw,re.I) and re.search(r"\d",next_raw):continue
        # Numbers carrying an explicit dimension marker are sizes, not product generations.
        if '"' in next_raw:continue
        if i+2<len(words) and re.sub(r"[^a-zа-яіїє]","",words[i+2],flags=re.I) in units:continue
        if re.fullmatch(r"\d{1,4}(?:gb|гб|tb|тб|hz|гц|mm|мм|cm|см|ml|мл|kg|кг|w|вт|inch|inches)",next_raw,re.I):continue
        n=int(nxt)
        if 1<=n<=20:out[family]=n
    return out

def generation_confirmation(expected_text:str,candidate_text:str)->tuple[bool,str|None]:
    eg,cg=named_generations(expected_text),named_generations(candidate_text)
    if not eg:return True,None
    common=set(eg)&set(cg)
    for family in common:
        if eg[family]!=cg[family]:return False,f"generation mismatch: {family} expected {eg[family]}, got {cg[family]}"
    if common:return True,None
    return False,"material generation not confirmed"

def identity_conflicts(expected_text:str,candidate_text:str)->list[str]:
    expected,candidate=signature(expected_text),signature(candidate_text);out=[];part_entities={"spare_part","accessory","component"}
    terminal_problem=_terminal_variant_conflict(expected_text,candidate_text)
    if terminal_problem:out.append(terminal_problem)
    public_code_problem=_public_code_conflict(expected_text,candidate_text)
    if public_code_problem:out.append(public_code_problem)
    model_problem=_explicit_model_conflict(expected_text,candidate_text)
    if model_problem:out.append(model_problem)
    if candidate.entity in part_entities and expected.entity not in part_entities:out.append(f"whole-product mismatch: candidate is {candidate.entity}")
    elif expected.entity and candidate.entity and expected.entity!=candidate.entity:out.append(f"entity mismatch: expected {expected.entity}, got {candidate.entity}")
    ef,cf=_short_family(expected.core_tokens),_short_family(candidate.core_tokens)
    if ef and cf and ef.isdisjoint(cf):out.append(f"product family mismatch: expected {sorted(ef)}, got {sorted(cf)}")
    elif expected.core_tokens and candidate.core_tokens and expected.core_tokens.isdisjoint(candidate.core_tokens):out.append(f"product core mismatch: expected {sorted(expected.core_tokens)}, got {sorted(candidate.core_tokens)}")
    eg,cg=named_generations(expected_text),named_generations(candidate_text)
    for family in set(eg)&set(cg):
        if eg[family]!=cg[family]:out.append(f"generation mismatch: {family} expected {eg[family]}, got {cg[family]}")
    return out

def variant_conflicts(expected_text:str,candidate_text:str)->list[str]:
    expected,candidate=signature(expected_text),signature(candidate_text);out=identity_conflicts(expected_text,candidate_text)
    if expected.storage_gb and candidate.storage_gb and expected.storage_gb.isdisjoint(candidate.storage_gb):out.append(f"storage mismatch: expected {sorted(expected.storage_gb)}GB, got {sorted(candidate.storage_gb)}GB")
    if expected.ram_gb and candidate.ram_gb and expected.ram_gb.isdisjoint(candidate.ram_gb):out.append(f"RAM mismatch: expected {sorted(expected.ram_gb)}GB, got {sorted(candidate.ram_gb)}GB")
    expected_sizes=set(expected.sizes);candidate_sizes=set(candidate.sizes)
    if expected.entity in {"television","monitor"}:
        ed=_display_diagonal(expected_text);cd=_display_diagonal(candidate_text)
        if ed:expected_sizes.add(ed)
        if cd:candidate_sizes.add(cd)
    if expected_sizes and candidate_sizes and expected_sizes.isdisjoint(candidate_sizes):out.append(f"size/volume mismatch: expected {sorted(expected_sizes)}, got {sorted(candidate_sizes)}")
    # An explicitly named mission color is a material variant only when the candidate also declares a color.
    # Missing candidate color stays unknown rather than becoming a false conflict.
    if expected.colors and candidate.colors and expected.colors.isdisjoint(candidate.colors):out.append(f"color mismatch: expected {sorted(expected.colors)}, got {sorted(candidate.colors)}")
    return list(dict.fromkeys(out))
