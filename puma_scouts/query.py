from __future__ import annotations
import re
from collections.abc import Iterable
from typing import Any
from puma_scouts.models import ProductMission
_ID_KEYS=("ean","gtin","mpn","model","vendorcode","vendor_code","sku","code")
_NAME_KEYS=("name","title","название","назва")
_BRAND_KEYS=("brand","vendor","бренд","производитель","виробник")
_GENERIC_WORDS={"гарнитура","навушники","наушники","полноразмерные","повнорозмірні","игровые","ігрові","карта","памяти","пам'яті","памяті","обогреватель","обігрівач","керамический","керамічний","на","квм","кв","м","для","usb","aux","black","white","red","blue","green","белый","білий","черный","чорний","красный","червоний"}
def _clean(value:Any)->str:return re.sub(r"\s+"," ",str(value or "")).strip()
def _first(data:dict[str,Any],keys:Iterable[str])->str|None:
    lowered={str(k).lower():v for k,v in data.items()}
    for key in keys:
        value=_clean(lowered.get(key))
        if value:return value
    return None
def extract_identifiers(mission:ProductMission)->list[str]:
    data={str(k).lower():v for k,v in mission.source_data.items()}; found=[]
    for key in _ID_KEYS:
        value=_clean(data.get(key))
        if value and value not in found:found.append(value)
    corpus=" ".join(_clean(v) for v in mission.source_data.values() if isinstance(v,(str,int)))
    for token in re.findall(r"\b(?=[A-ZА-ЯІЇЄ0-9-]{4,}\b)(?=[A-ZА-ЯІЇЄ0-9-]*\d)[A-ZА-ЯІЇЄ0-9-]+\b",corpus.upper()):
        if token not in found:found.append(token)
    return found[:12]
def _identity_tokens(name:str,brand:str|None)->list[str]:
    raw=re.sub(r"[()\[\]{},;]+"," ",name);tokens=[]
    for token in raw.split():
        t=token.strip("-_/+").casefold()
        if not t or t in _GENERIC_WORDS:continue
        if re.fullmatch(r"\d+(?:[.,]\d+)?",t):continue
        if re.fullmatch(r"\d+\s*(?:gb|гб|tb|тб|м2|m2)",t):continue
        if brand and t==brand.casefold():continue
        tokens.append(token.strip(".,:;()[]{}"))
    return tokens
def generate_queries(mission:ProductMission)->list[str]:
    data=mission.source_data;name=_first(data,_NAME_KEYS);brand=_first(data,_BRAND_KEYS);identifiers=extract_identifiers(mission);queries=[]
    def add(value):
        value=_clean(value)
        if value and value.casefold() not in {q.casefold() for q in queries}:queries.append(value)
    if name:
        identity=_identity_tokens(name,brand)
        # Search engines/marketplaces usually perform better on brand + model family than supplier prose.
        if brand and identity:add(" ".join([brand,*identity[:5]]))
        if brand and len(identity)>=2:add(" ".join([brand,*identity[:3]]))
        if identity:add(" ".join(identity[:5]))
    # Strong public product identifiers are useful discovery signals. Supplier article itself is never added.
    for identifier in identifiers[:6]:
        if identifier.casefold()==mission.article.casefold():continue
        if brand:add(f"{brand} {identifier}")
        add(identifier)
    if name:add(name)
    return queries[:12]
