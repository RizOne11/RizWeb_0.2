from priceintel.matcher import score_match, build_query
from priceintel.extract import extract_product
from priceintel.analyze import stats

def run():
    row={"Название":"Гарнітура JBL C50HI Red (JBLC50HIRED)","Артикул":"JBLC50HIRED","Производитель":"JBL","Цена":334}
    assert "JBLC50HIRED" in build_query(row)
    assert score_match(row,"Навушники JBL C50HI Red JBLC50HIRED") > 90
    html='''<html><head><title>JBL C50HI Red</title><script type="application/ld+json">{"@type":"Product","name":"JBL C50HI Red JBLC50HIRED","offers":{"@type":"Offer","price":"319","priceCurrency":"UAH"}}</script></head></html>'''
    p=extract_product(html,"https://example.com/x")
    assert p['price']==319
    s=stats([{"price":319},{"price":349},{"price":339}],334)
    assert s['median']==339
    print('OK',s)
if __name__=='__main__': run()
