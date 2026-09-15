import argparse, json, os, time
import requests
from priceintel.io import read_catalog, write_csv
from priceintel.matcher import build_query, score_match
from priceintel.search import DDGSearch
from priceintel.extract import extract_product
from priceintel.cache import Cache
from priceintel.analyze import stats

def main():
    ap=argparse.ArgumentParser(description="Price Intelligence MVP")
    ap.add_argument("input_csv")
    ap.add_argument("--output", default="market_analysis.csv")
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--config", default=os.path.join(os.path.dirname(__file__),"config.json"))
    args=ap.parse_args()
    cfg=json.load(open(args.config,encoding="utf-8"))
    rows=read_catalog(args.input_csv)[:args.limit]
    searcher=DDGSearch(cfg['user_agent'],cfg['request_delay_seconds'])
    sess=requests.Session(); sess.headers.update({"User-Agent":cfg['user_agent'],"Accept-Language":"uk-UA,uk;q=0.9,en;q=0.7"})
    cache=Cache(os.path.join(os.path.dirname(args.output) or ".","priceintel_cache.sqlite"))
    results=[]
    offer_rows=[]
    for i,row in enumerate(rows,1):
        q=build_query(row); accepted=[]
        print(f"[{i}/{len(rows)}] {row.get('Название') or row.get('Артикул')} | {q}")
        for mp in cfg['marketplaces']:
            try: hits=searcher.search(q,mp['domain'],cfg['max_results_per_marketplace'])
            except Exception as e:
                print(" search error",mp['name'],e); continue
            for hit in hits:
                url=hit['url']; html=cache.get(url)
                if html is None:
                    try:
                        time.sleep(cfg['request_delay_seconds'])
                        rr=sess.get(url,timeout=20,allow_redirects=True); rr.raise_for_status(); html=rr.text; cache.put(url,html)
                    except Exception as e: continue
                prod=extract_product(html,url)
                match=score_match(row, prod['title'] or hit['title'])
                if match >= cfg['match_threshold'] and prod.get('price'):
                    prod.update({"marketplace":mp['name'],"match_score":round(match,1)})
                    accepted.append(prod)
                    offer_rows.append({"Код товара":row['Код товара'],"Артикул":row['Артикул'],"Маркетплейс":mp['name'],"Название конкурента":prod['title'],"Цена конкурента":prod['price'],"Match %":round(match,1),"URL":prod['url']})
        st=stats(accepted,row.get('Цена'))
        results.append({**row,"Поисковый запрос":q,"Мин. рынка":st['min_price'],"Медиана рынка":st['median'],"Средняя рынка":round(st['avg'],2) if st['avg'] else None,"Макс. рынка":st['max_price'],"Предложений":st['offers_count'],"Разница с медианой %":round(st['delta_median_pct'],2) if st['delta_median_pct'] is not None else None,"Price Score":st['price_score'],"Вердикт":st['verdict']})
    fields=list(results[0].keys()) if results else []
    write_csv(args.output,results,fields)
    detail=os.path.splitext(args.output)[0]+"_offers.csv"
    if offer_rows: write_csv(detail,offer_rows,list(offer_rows[0].keys()))
    print("Saved:",args.output,"and",detail)

if __name__=="__main__": main()
