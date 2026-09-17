from __future__ import annotations

import re
from typing import Any

from puma_scouts.models import Marketplace, Offer, ProductMission, ValidatedOffer, Verdict
from puma_scouts.query import extract_identifiers
from puma_scouts.variant_engine import variant_conflicts


def _norm(value: Any) -> str:
    text = str(value or "").casefold()
    text = re.sub(r"[^\w]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def _compact(value: Any) -> str:
    return re.sub(r"[^\w]", "", str(value or "").casefold(), flags=re.UNICODE)


def _tokens(value: Any) -> set[str]:
    return {t for t in _norm(value).split() if len(t) >= 3}


def _strong_identifier(value: str) -> bool:
    text = _compact(value)
    if not text or re.fullmatch(r"(?:19|20)\d{2}", text): return False
    if text.isdigit(): return len(text) >= 8
    letters=len(re.findall(r"[a-zа-яіїє]",text,re.I));digits=len(re.findall(r"\d",text))
    return len(text)>=7 and letters>=2 and digits>=2


def _explicit(mission: ProductMission, keys:set[str])->str|None:
    for key,value in mission.source_data.items():
        if str(key).casefold() in keys:
            text=str(value or "").strip()
            if text:return text
    return None


def _model_match(expected:str|None,offer_text:str)->bool:
    if not expected:return False
    if _compact(expected) and _compact(expected) in _compact(offer_text):return True
    parts=[t for t in _norm(expected).split() if t];on=_norm(offer_text)
    return len(parts)>=2 and all(re.search(rf"\b{re.escape(p)}\b",on) for p in parts)


def _brand_match(expected:str|None,offer_text:str)->bool:
    return True if not expected else bool(_compact(expected) and _compact(expected) in _compact(offer_text))


def _brand_conflict(expected:str|None,offer_text:str)->str|None:
    """Reject a clearly different leading brand while preserving marketplace prose.

    This is intentionally dictionary-free. It only fires when the mission has an
    explicit brand, that brand is also present in the offer, and the offer starts
    with another plausible brand token before it. Thus `Logitech ... Apple ...`
    is contradictory, while descriptive prefixes such as `Навушники Apple ...`
    do not invent a foreign-brand conflict.
    """
    if not expected:return None
    n=_norm(offer_text);brand=_norm(expected)
    if not brand or not re.search(rf"\b{re.escape(brand)}\b",n,re.I):return None
    words=n.split();brand_words=brand.split()
    try:
        idx=next(i for i in range(len(words)) if words[i:i+len(brand_words)]==brand_words)
    except StopIteration:
        return None
    if idx<=0:return None
    generic={"смартфон","телефон","монітор","монитор","навушники","наушники","headphones","earbuds","ноутбук","laptop","планшет","tablet","телевізор","телевизор","tv","ssd","hdd","шина","шини","шины","tire","tyre","парфум","парфюм","оригінал","оригинал","новий","новый","new"}
    prefix=[w for w in words[:idx] if len(w)>=3 and w not in generic and not w.isdigit()]
    if len(prefix)==1 and re.fullmatch(r"[a-zа-яіїє][a-zа-яіїє0-9-]{2,24}",prefix[0],re.I):
        return f"brand conflict: foreign leading brand {prefix[0]} before expected {expected}"
    return None


def _condition_conflict(src:str,off:str)->str|None:
    used=r"\b(?:вживан\w*|б\s*у|бу|used|refurbished|refurb|відновлен\w*|восстановлен\w*)\b"
    return "condition mismatch: used/refurbished offer" if re.search(used,_norm(off),re.I) and not re.search(used,_norm(src),re.I) else None


def _authenticity_conflict(src:str,off:str)->str|None:
    clone=r"\b(?:реплік\w*|реплик\w*|копі\w*|копи\w*|аналог\w*|clone|copy|airoha)\b"
    return "authenticity mismatch: explicit replica/clone marker" if re.search(clone,_norm(off),re.I) and not re.search(clone,_norm(src),re.I) else None


def _pack_count(text:str)->int|None:
    n=_norm(text)
    for p in (r"\b(\d{1,3})\s*(?:шт|штук|pcs|pieces)\b",r"\b(?:набор|комплект|упаковка)\s+(?:из\s+)?(\d{1,3})\b"):
        m=re.search(p,n,re.I)
        if m and int(m.group(1))>1:return int(m.group(1))
    return None


def _quantity_conflict(src:str,off:str,strong:bool)->str|None:
    e=_pack_count(src)
    if not e:return None
    a=_pack_count(off)
    if a is not None and a!=e:return f"pack quantity mismatch: expected {e}, got {a}"
    if a is None and not strong:return f"pack quantity not confirmed: expected {e}"
    return None


def _year_refresh_conflicts(src:str,off:str)->list[str]:
    s,o=_norm(src),_norm(off);out=[]
    sy=set(re.findall(r"\b20\d{2}\b",s));oy=set(re.findall(r"\b20\d{2}\b",o))
    if sy and oy and sy.isdisjoint(oy):out.append(f"variant year mismatch: expected {sorted(sy)}, got {sorted(oy)}")
    hz=lambda t:set(re.findall(r"\b(\d{2,3})\s*(?:гц|hz)\b",t,re.I));sh,oh=hz(s),hz(o)
    if sh and oh and sh.isdisjoint(oh):out.append(f"refresh-rate mismatch: expected {sorted(sh)}, got {sorted(oh)}")
    return out


def validate_offer(mission:ProductMission,offer:Offer)->ValidatedOffer:
    source_text=" ".join(str(v) for v in mission.source_data.values())
    offer_text=" ".join([offer.title,*[f"{k} {v}" for k,v in offer.attributes.items()]])
    st,ot=_tokens(source_text),_tokens(offer_text);overlap=len(st&ot)/max(1,len(st))
    ids=extract_identifiers(mission);matched=[i for i in ids if _strong_identifier(i) and _compact(i) and _compact(i) in _compact(offer_text)]
    model=_explicit(mission,{"model","mpn","ean","gtin","gtin13"});mm=_model_match(model,offer_text)
    brand=_explicit(mission,{"brand","manufacturer","vendor"});bm=_brand_match(brand,offer_text)
    strong=bool(matched or mm)
    problems=[]
    for p in (_authenticity_conflict(source_text,offer_text),_condition_conflict(source_text,offer_text),_quantity_conflict(source_text,offer_text,strong),_brand_conflict(brand,offer_text)):
        if p:problems.append(p)
    problems.extend(variant_conflicts(source_text,offer_text))
    problems.extend(_year_refresh_conflicts(source_text,offer_text))
    if brand and not (bm or strong):problems.append(f"brand not confirmed: {brand}")
    conflicts=list(dict.fromkeys(problems));positive=[]
    if matched:positive.append("strong identifier match: "+", ".join(matched[:4]))
    if mm:positive.append("explicit model match: "+str(model))
    if brand and bm:positive.append("brand match: "+brand)
    if brand and not bm and strong:positive.append("brand token absent but exact identity confirmed")
    if overlap>=.35:positive.append(f"source token overlap={overlap:.2f}")
    if conflicts:score=min(.64,.20+overlap);verdict=Verdict.CONFLICT if overlap>=.18 else Verdict.REJECT
    elif model and not mm and offer.marketplace!=Marketplace.PROM:
        if overlap>=.18:score=min(.64,.20+overlap);verdict=Verdict.CONFLICT;conflicts.append(f"expected model not confirmed: {model}")
        else:score=overlap;verdict=Verdict.REJECT
    elif model and not mm and offer.marketplace==Marketplace.PROM:
        if overlap>=.55:score=min(.88,.42+overlap);verdict=Verdict.PASS;positive.append("Prom descriptive identity accepted; model absent")
        elif overlap>=.18:score=min(.64,.20+overlap);verdict=Verdict.CONFLICT;conflicts.append("insufficient Prom descriptive identity")
        else:score=overlap;verdict=Verdict.REJECT
    elif strong:score=min(1.0,.72+.05*len(matched)+(.05 if mm else 0)+.18*overlap);verdict=Verdict.PASS
    elif overlap>=.55:score=min(.79,.35+overlap);verdict=Verdict.PASS
    elif overlap>=.18:score=min(.64,.20+overlap);verdict=Verdict.CONFLICT;conflicts.append("insufficient strong identifier evidence")
    else:score=overlap;verdict=Verdict.REJECT
    return ValidatedOffer(offer=offer,verdict=verdict,score=score,positive_evidence=positive,conflicts=conflicts,rejection_reasons=[] if verdict!=Verdict.REJECT else ["low identity evidence"])
