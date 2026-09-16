from __future__ import annotations
import re
from typing import Any
from puma_scouts.models import Marketplace,Offer,ProductMission,ValidatedOffer,Verdict
from puma_scouts.query import extract_identifiers
def _norm(v:Any)->str:return re.sub(r"\s+"," ",re.sub(r"[^\w]+"," ",str(v or "").casefold(),flags=re.UNICODE)).strip()
def _compact(v:Any)->str:return re.sub(r"[^\w]","",str(v or "").casefold(),flags=re.UNICODE)
def _tokens(v:Any)->set[str]:return {t for t in _norm(v).split() if len(t)>=3}
def _strong(v:str)->bool:
    t=_compact(v)
    if not t or re.fullmatch(r"(?:19|20)\d{2}",t):return False
    if t.isdigit():return len(t)>=8
    return len(t)>=7 and len(re.findall(r"[a-zа-яіїє]",t,re.I))>=2 and len(re.findall(r"\d",t))>=2
def _field(m:ProductMission,names:set[str])->str|None:
    for k,v in m.source_data.items():
        if str(k).casefold() in names and str(v or "").strip():return str(v).strip()
    return None
def validate_offer(mission:ProductMission,offer:Offer)->ValidatedOffer:
    source=" ".join(str(v) for v in mission.source_data.values()); target=" ".join([offer.title,*[f"{k} {v}" for k,v in offer.attributes.items()]])
    st,ot=_tokens(source),_tokens(target); overlap=len(st&ot)/max(1,len(st)); ids=extract_identifiers(mission); matched=[i for i in ids if _strong(i) and _compact(i) in _compact(target)]
    model=_field(mission,{"model","mpn","ean","gtin","gtin13"}); brand=_field(mission,{"brand","manufacturer","vendor"})
    model_match=bool(model and _compact(model) in _compact(target)); brand_match=not brand or _compact(brand) in _compact(target); strong=bool(matched or model_match); positive=[]; conflicts=[]
    if matched:positive.append("strong identifier match: "+", ".join(matched[:4]))
    if model_match:positive.append("explicit model match: "+str(model))
    if brand and brand_match:positive.append("brand match: "+brand)
    if brand and not brand_match and not strong:conflicts.append(f"brand not confirmed: {brand}")
    if overlap>=.35:positive.append(f"source token overlap={overlap:.2f}")
    if conflicts:verdict=Verdict.CONFLICT if overlap>=.18 else Verdict.REJECT; score=min(.64,.20+overlap)
    elif model and not model_match and offer.marketplace==Marketplace.PROM and overlap>=.55:
        verdict=Verdict.PASS; score=min(.88,.42+overlap); positive.append("Prom descriptive identity accepted; model absent")
    elif model and not model_match and offer.marketplace!=Marketplace.PROM:
        verdict=Verdict.CONFLICT if overlap>=.18 else Verdict.REJECT; score=min(.64,.20+overlap) if overlap>=.18 else overlap
        if verdict==Verdict.CONFLICT:conflicts.append(f"expected model not confirmed: {model}")
    elif strong:verdict=Verdict.PASS; score=min(1.0,.72+.05*len(matched)+(.05 if model_match else 0)+.18*overlap)
    elif overlap>=.55:verdict=Verdict.PASS; score=min(.79,.35+overlap)
    elif overlap>=.18:verdict=Verdict.CONFLICT; score=min(.64,.20+overlap); conflicts.append("insufficient strong identifier evidence")
    else:verdict=Verdict.REJECT; score=overlap
    return ValidatedOffer(offer=offer,verdict=verdict,score=score,positive_evidence=positive,conflicts=conflicts,rejection_reasons=[] if verdict!=Verdict.REJECT else ["low identity evidence"])
