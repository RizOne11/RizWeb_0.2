from __future__ import annotations
import asyncio,csv,re,statistics,xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any,Callable
from openpyxl import Workbook,load_workbook
from .models import IdentityConfidence,ProductMission,Verdict

def _text(v:Any)->str:return "" if v is None else str(v).strip()
ALIASES={"article":{"артикул","article","sku","код","vendorcode","vendor_code"},"name":{"назва","название","name","товар","product","title"},"brand":{"бренд","brand","виробник","vendor"},"model":{"модель","model","mpn"},"own_price":{"ціна","цена","price","price_uah","вартість","стоимость"}}
def _mission(data:dict[str,Any],fallback:str)->ProductMission|None:
    norm={str(k).strip().lower():_text(v) for k,v in data.items()};picked={k:next((norm[a] for a in names if norm.get(a)),"") for k,names in ALIASES.items()}
    if not picked["name"]:return None
    source={k:picked[k] for k in ("name","brand","model","own_price") if picked[k]};return ProductMission(article=picked["article"] or fallback,source_data=source)
def _read_xlsx(path:str,limit=None):
    wb=load_workbook(path,data_only=True,read_only=True);ws=wb.active;header=0;cols={}
    for r in range(1,min(ws.max_row,30)+1):
        vals={_text(ws.cell(r,c).value).lower():c for c in range(1,ws.max_column+1)};found={k:next((vals[n] for n in names if n in vals),0) for k,names in ALIASES.items()}
        if found["name"] or (found["article"] and sum(bool(x) for x in found.values())>=2):header,cols=r,found;break
    if not header:raise ValueError("Потрібна колонка Назва/Name; Артикул, Бренд і Модель можуть бути окремими колонками")
    out=[]
    for r in range(header+1,ws.max_row+1):
        data={k:_text(ws.cell(r,c).value) if c else "" for k,c in cols.items()};m=_mission(data,f"ROW-{r}")
        if m:out.append(m)
        if limit and len(out)>=limit:break
    return out
def _read_csv(path:str,limit=None):
    raw=Path(path).read_bytes();text=None
    for enc in ("utf-8-sig","utf-8","cp1251"):
        try:text=raw.decode(enc);break
        except UnicodeDecodeError:pass
    if text is None:raise ValueError("Не вдалося визначити кодування CSV")
    try:dialect=csv.Sniffer().sniff(text[:8192],delimiters=",;\t|")
    except csv.Error:dialect=csv.excel;dialect.delimiter=";"
    out=[]
    for i,row in enumerate(csv.DictReader(text.splitlines(),dialect=dialect),2):
        m=_mission(row,f"ROW-{i}")
        if m:out.append(m)
        if limit and len(out)>=limit:break
    return out
def _tag(el):return el.tag.rsplit('}',1)[-1].lower()
def _read_xml(path:str,limit=None):
    root=ET.parse(path).getroot();out=[]
    for i,e in enumerate([e for e in root.iter() if _tag(e) in {"offer","product","item"}],1):
        data={_tag(c):_text(c.text) for c in e.iter() if c is not e and _text(c.text)}
        for k,v in e.attrib.items():data.setdefault(k.lower(),v)
        m=_mission(data,f"ROW-{i}")
        if m:out.append(m)
        if limit and len(out)>=limit:break
    return out
def read_missions(path:str,limit:int|None=None)->list[ProductMission]:
    ext=Path(path).suffix.lower()
    if ext==".xlsx":out=_read_xlsx(path,limit)
    elif ext==".csv":out=_read_csv(path,limit)
    elif ext in {".yml",".xml"}:out=_read_xml(path,limit)
    else:raise ValueError("Підтримуються XLSX, CSV, YML та XML")
    if not out:raise ValueError("У файлі не знайдено товарів із назвою")
    return out

def scouts(selected:list[str]|None=None):
    from .scouts.catalog import HotlineScout,PromScout
    from .scouts.epicentr import EpicentrScout
    from .scouts.web_shops import WebShopsScout
    all_scouts={"epicentr":EpicentrScout(timeout=8,max_candidates_per_query=10),"prom":PromScout(timeout=8,max_candidates_per_query=10),"hotline":HotlineScout(timeout=8,max_candidates_per_query=10),"web_shops":WebShopsScout(timeout=8,max_candidates_per_query=12,max_per_domain=2)}
    wanted=set(selected or all_scouts);return [s for k,s in all_scouts.items() if k in wanted]
async def _scan_source(scout,mission:ProductMission,wall_timeout:float=75.0):
    try:return scout,await asyncio.wait_for(scout.scan(mission),timeout=wall_timeout)
    except (asyncio.TimeoutError,Exception):return scout,None
def _title_signature(title:str)->str:
    t=title.casefold();t=re.sub(r"\([^)]*\)$","",t);t=re.sub(r"\b(?:монітор|монитор)\b"," ",t);return re.sub(r"[^a-zа-яіїєґ0-9]+"," ",t).strip()
def _prom_identity(x):return (x["article"],x["source"],x["price"],_title_signature(x["found_title"]))
async def scan(mission:ProductMission,selected:list[str]|None=None)->list[dict[str,Any]]:
    rows=[];results=await asyncio.gather(*[_scan_source(s,mission) for s in scouts(selected)])
    for scout,report in results:
        if report is None:continue
        for item in report.offers:
            if item.verdict!=Verdict.PASS or item.identity_confidence not in {None,IdentityConfidence.CONFIRMED,IdentityConfidence.PROBABLE}:continue
            o=item.offer;rows.append({"article":mission.article,"name":mission.source_data.get("name",""),"brand":mission.source_data.get("brand",""),"model":mission.source_data.get("model",""),"own_price":mission.source_data.get("own_price",""),"source":scout.marketplace.value,"price":float(o.price) if o.price is not None else None,"currency":o.currency,"availability":o.availability or "","found_title":o.title,"url":str(o.url),"match":round(item.score,3),"identity_confidence":item.identity_confidence.value if item.identity_confidence else "LEGACY_PASS","domain":o.attributes.get("source_domain","") or str(o.url).split('/')[2],"health":report.health.value})
    dedup={}
    for x in rows:
        if x["source"]=="web_shops":key=(x["article"],x["source"],x["domain"],x["price"])
        elif x["source"]=="prom":key=_prom_identity(x)
        else:key=(x["article"],x["source"],x["url"])
        current=dedup.get(key)
        if current is None or x["match"]>current["match"]:dedup[key]=x
    return list(dedup.values())
def _market_summary(offers):
    groups={}
    for x in offers:
        if x.get("price") is None:continue
        groups.setdefault(x["source"],[]).append(x["price"])
    return " | ".join(f"{src}: "+", ".join(f"{price:g} грн"+(f" ×{prices.count(price)}" if prices.count(price)>1 else "") for price in sorted(set(prices))) for src,prices in sorted(groups.items()))
def product_report(missions:list[ProductMission],rows:list[dict[str,Any]])->list[dict[str,Any]]:
    by_article={}
    for x in rows:by_article.setdefault(x["article"],[]).append(x)
    report=[]
    for m in missions:
        offers=by_article.get(m.article,[]);priced=[x["price"] for x in offers if x.get("price") is not None];conf=Counter(x.get("identity_confidence","LEGACY_PASS") for x in offers)
        report.append({"article":m.article,"name":m.source_data.get("name",""),"brand":m.source_data.get("brand",""),"model":m.source_data.get("model",""),"own_price":m.source_data.get("own_price",""),"status":"FOUND" if offers else "NOT_FOUND","marketplaces":_market_summary(offers),"offers":len(offers),"sources":len({x["source"] for x in offers}),"min_price":min(priced) if priced else None,"median_price":statistics.median(priced) if priced else None,"avg_price":round(sum(priced)/len(priced),2) if priced else None,"max_price":max(priced) if priced else None,"confirmed":conf.get("CONFIRMED",0),"probable":conf.get("PROBABLE",0),"offer_rows":offers})
    return report
def save(rows:list[dict[str,Any]],output:str,missions:list[ProductMission]|None=None)->None:
    missions=missions or [];products=product_report(missions,rows) if missions else [];wb=Workbook();overview=wb.active;overview.title="Результат";overview.append(["Артикул","Назва","Бренд","Модель","Вхідна ціна","Статус","Маркетплейс → ціна","Мін. ринку","Медіана","Середня","Макс. ринку","Карток","Джерел","CONFIRMED","PROBABLE"])
    for p in products:overview.append([p[k] for k in ("article","name","brand","model","own_price","status","marketplaces","min_price","median_price","avg_price","max_price","offers","sources","confirmed","probable")])
    overview.freeze_panes="A2";overview.auto_filter.ref=overview.dimensions
    ws=wb.create_sheet("Пропозиції");keys=("article","name","brand","model","own_price","source","price","currency","availability","found_title","url","match","identity_confidence","domain","health");ws.append(["Артикул","Назва","Бренд","Модель","Вхідна ціна","Джерело","Ціна","Валюта","Наявність","Знайдена назва","URL","Match","Identity Confidence","Домен","Health"]);defaults={"identity_confidence":"LEGACY_PASS","domain":"","health":"","own_price":""}
    for x in rows:ws.append([x.get(k,defaults.get(k,"")) for k in keys])
    ws.freeze_panes="A2";ws.auto_filter.ref=ws.dimensions
    summary=wb.create_sheet("Ціна → картки");summary.append(["Артикул","Назва","Джерело","Ціна","Карток"]);groups=Counter((x["article"],x["name"],x["source"],x["price"]) for x in rows if x.get("price") is not None)
    for key,count in sorted(groups.items(),key=lambda z:(z[0][0],z[0][2],z[0][3])):summary.append([*key,count])
    summary.freeze_panes="A2";summary.auto_filter.ref=summary.dimensions;wb.save(output)
async def run(input_path:str,output_path:str,limit:int|None=None,selected:list[str]|None=None,progress_cb:Callable|None=None)->dict[str,Any]:
    missions=read_missions(input_path,limit);rows=[];semaphore=asyncio.Semaphore(4);completed=0;lock=asyncio.Lock()
    async def one(m):
        nonlocal completed
        async with semaphore:
            if progress_cb:progress_cb(completed,len(missions),m.source_data.get("name",m.article),"Шукаємо реальні пропозиції…")
            found=await scan(m,selected)
            async with lock:
                completed+=1
                if progress_cb:progress_cb(completed,len(missions),m.source_data.get("name",m.article),"Товар перевірено")
            return found
    for found in await asyncio.gather(*[one(m) for m in missions]):rows.extend(found)
    products=product_report(missions,rows);save(rows,output_path,missions)
    if progress_cb:progress_cb(len(missions),len(missions),"Готово","Формуємо звіт…")
    found=sum(1 for p in products if p["status"]=="FOUND");confidence=Counter(x.get('identity_confidence','LEGACY_PASS') for x in rows);web_products=[{k:v for k,v in p.items() if k!="offer_rows"}|{"offers_detail":p["offer_rows"]} for p in products]
    return {"products":len(missions),"offers":len(rows),"found_products":found,"found_pct":round(found/max(1,len(missions))*100,1),"sources":len({x['source'] for x in rows}),"confirmed":confidence.get("CONFIRMED",0),"probable":confidence.get("PROBABLE",0),"product_results":web_products}
def run_sync(input_path:str,output_path:str,**kwargs):return asyncio.run(run(input_path,output_path,**kwargs))
