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
    for value in re.findall(r"(?<!\d)(\d{1,3}(?:[.,]\d+)?)\s*(?:inch|inches|\")",raw,re.I):out.add(value.replace(",",".")+"in")
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
        if re.search(r"[a-zа-яіїє]",c,re.I) and re.search(r"\d",c):out.add(c)
    return out

def signature(text:str)->ProductSignature:
    ram,storage=_memory(text);return ProductSignature(entity=entity_type(text),core_tokens=frozenset(_core_tokens(text)),storage_gb=frozenset(storage),ram_gb=frozenset(ram),sizes=frozenset(_sizes(text)),colors=frozenset(_colors(text)))

def _short_family(tokens:frozenset[str])->set[str]:return {t for t in tokens if len(t)<=8 and re.search(r"[a-zа-яіїє]",t,re.I) and re.search(r"\d",t)}

def named_generations(text:str)->dict[str,int]:
    t=norm(text);out={};words=t.split()
    skip={"gb","гб","tb","тб","hz","гц","mm","мм","cm","см","ml","мл","usb","type","wifi","lte","розмір","размер","size"}
    units={"gb","гб","tb","тб","hz","гц","mm","мм","cm","см","ml","мл","kg","кг","w","вт","inch","inches","дюйм","дюйма","дюймов","дюйми","дюймів"}
    for i in range(len(words)-1):
        family=re.sub(r"[^a-zа-яіїє]","",words[i],flags=re.I);next_raw=words[i+1];nxt=re.sub(r"[^0-9]","",next_raw)
        if not family or family in skip or not nxt:continue
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
