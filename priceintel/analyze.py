import statistics

def stats(offers, own_price):
    prices=[o['price'] for o in offers if o.get('price') and o['price']>0]
    if not prices:
        return dict(min_price=None, median=None, avg=None, max_price=None, offers_count=0, delta_median_pct=None, price_score=0, verdict="⚪ НЕ ЗНАЙДЕНО")
    med=statistics.median(prices); avg=sum(prices)/len(prices)
    delta=((own_price-med)/med*100) if own_price and med else None
    # Score: 100 if >=15% below median, 50 at median, 0 if >=20% above median
    if delta is None: score=0
    elif delta <= -15: score=100
    elif delta >= 20: score=0
    elif delta <= 0: score=50 + (-delta/15)*50
    else: score=50 - (delta/20)*50
    score=round(max(0,min(100,score)))
    verdict = "🔥 РЕКЛАМУВАТИ" if score>=85 else "🟢 ПЕРСПЕКТИВНИЙ" if score>=65 else "🟡 ТЕСТУВАТИ" if score>=40 else "🔴 НЕ РЕКЛАМУВАТИ"
    return dict(min_price=min(prices),median=med,avg=avg,max_price=max(prices),offers_count=len(prices),delta_median_pct=delta,price_score=score,verdict=verdict)
