from __future__ import annotations
import re
from collections.abc import Iterable
from typing import Any
from puma_scouts.models import ProductMission
_ID_KEYS=("ean","gtin","mpn","model","vendorcode","vendor_code","sku","code")
_NAME_KEYS=("name","title","название","назва")
_BRAND_KEYS=("brand","vendor","бренд","производитель","виробник")
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
def generate_queries(mission:ProductMission)->list[str]:
    data=mission.source_data; name=_first(data,_NAME_KEYS); brand=_first(data,_BRAND_KEYS); identifiers=extract_identifiers(mission); queries=[]
    def add(value):
        value=_clean(value)
        if value and value.casefold() not in {q.casefold() for q in queries}:queries.append(value)
    add(name)
    for identifier in identifiers[:6]:
        add(identifier)
        if brand:add(f"{brand} {identifier}")
    if brand and name:add(" ".join([brand,*name.split()[:7]]))
    # Supplier article is deliberately NOT added as a search query. It remains SKU Lock only.
    return queries[:12]
