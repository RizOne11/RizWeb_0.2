from __future__ import annotations
import asyncio
from collections import Counter
from typing import Any,Callable
from openpyxl import Workbook,load_workbook
from .models import ProductMission,Verdict

def _text(v:Any)->str:return "" if v is None else str(v).strip()
def read_missions(path:str,limit:int|None=None)->list[ProductMission]:
    wb=load_workbook(path,data_only=True,read_only=True); ws=wb.active
    aliases={"article":{"артикул","article","sku","код"},"name":{"назва","название","name","товар","product"},"brand":{"бренд","brand","виробник"},"model":{"модель","model"}}
    header=0; cols={}
    for r in range(1,min(ws.max_row,30)+1):
        vals={_text(ws.cell(r,c).value).lower():c for c in range(1,ws.max_column+1)}; found={k:next((vals[n] for n in names if n in vals),0) for k,names in aliases.items()}
        if found["name"] or (found["article"] and sum(bool(x) for x in found.values())>=2):header,cols=r,found;break
    if not header:raise ValueError("Потрібна колонка Назва/Name; Артикул, Бренд і Модель можуть бути окремими колонками")
    out=[]
    for r in range(header+1,ws.max_row+1):
        data={k:_text(ws.cell(r,c).value) if c else "" for k,c in cols.items()}
        if not any(data.values()):continue
        source={k:data[k] for k in ("name","brand","model") if data[k]}; out.append(ProductMission(article=data["article"] or f"ROW-{r}",source_data=source))
        if limit and len(out)>=limit:break
    return out
def scouts(selected:list[str]|None=None):
    from .scouts.catalog import HotlineScout,PromScout
    from .scouts.epicentr import EpicentrScout
    from .scouts.web_shops import WebShopsScout
    all_scouts={"epicentr":EpicentrScout(timeout=15,max_candidates_per_query=12),"prom":PromScout(timeout=15,max_candidates_per_query=12),"hotline":HotlineScout(timeout=15,max_candidates_per_query=12),"web_shops":WebShopsScout(timeout=15,max_candidates_per_query=20,max_per_domain=2)}
    wanted=set(selected or all_scouts);return [s for k,s in all_scouts.items() if k in wanted]
async def scan(mission:ProductMission,selected:list[str]|None=None)->list[dict[str,Any]]:
    rows=[]
    for scout in scouts(selected):
        report=await scout.scan(mission)
        for item in report.offers:
            if item.verdict!=Verdict.PASS:continue
            o=item.offer; rows.append({"article":mission.article,"name":mission.source_data.get("name",""),"brand":mission.source_data.get("brand",""),"model":mission.source_data.get("model",""),"source":scout.marketplace.value,"price":float(o.price) if o.price is not None else None,"currency":o.currency,"availability":o.availability or "","found_title":o.title,"url":str(o.url),"match":round(item.score,3),"domain":o.attributes.get("source_domain","") or str(o.url).split('/')[2],"health":report.health.value})
    # Collapse localized/mirrored independent-shop cards: same domain + price + same physical mission.
    dedup={}
    for x in rows:
        key=(x["article"],x["source"],x["domain"],x["price"]) if x["source"]=="web_shops" else (x["article"],x["source"],x["url"])
        dedup.setdefault(key,x)
    return list(dedup.values())
def save(rows:list[dict[str,Any]],output:str)->None:
    wb=Workbook();ws=wb.active;ws.title="Offers";ws.append(["Артикул","Назва","Бренд","Модель","Джерело","Ціна","Валюта","Наявність","Знайдена назва","URL","Match","Домен","Health"])
    for x in rows:ws.append([x[k] for k in ("article","name","brand","model","source","price","currency","availability","found_title","url","match","domain","health")])
    ws.freeze_panes="A2";ws.auto_filter.ref=ws.dimensions
    summary=wb.create_sheet("Price summary");summary.append(["Артикул","Назва","Джерело","Ціна","Карток"]);groups=Counter((x["article"],x["name"],x["source"],x["price"]) for x in rows if x["price"] is not None)
    for key,count in sorted(groups.items(),key=lambda z:(z[0][0],z[0][2],z[0][3])):summary.append([*key,count])
    summary.freeze_panes="A2";summary.auto_filter.ref=summary.dimensions;wb.save(output)
async def run(input_path:str,output_path:str,limit:int|None=None,selected:list[str]|None=None,progress_cb:Callable|None=None)->dict[str,Any]:
    missions=read_missions(input_path,limit);rows=[]
    if not missions:raise ValueError("У Excel не знайдено товарів")
    for i,m in enumerate(missions,1):
        if progress_cb:progress_cb(i-1,len(missions),m.source_data.get("name",m.article),"Шукаємо реальні пропозиції…")
        rows.extend(await scan(m,selected))
    save(rows,output_path)
    if progress_cb:progress_cb(len(missions),len(missions),"Готово","Формуємо звіт…")
    return {"products":len(missions),"offers":len(rows),"sources":len({x['source'] for x in rows})}
def run_sync(input_path:str,output_path:str,**kwargs):return asyncio.run(run(input_path,output_path,**kwargs))
