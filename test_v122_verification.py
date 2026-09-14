from priceintel.matcher import classify_match
from priceintel.runner import _post_verify_price_outliers


def test_numeric_supplier_sku_is_not_global_identity():
    row = {
        'Название': 'Комплект наушники с кейсом Marshall Major IV Bluetooth Black (1005773)',
        'Производитель': 'Marshall',
        'Артикул': '11676',
        'Параметры': [{'name':'Цвет','value':'Black'}],
    }
    unrelated = classify_match(row, 'Бюстгальтер Lanny Mode 11676', 'https://shop.ua/lanny-mode-11676')
    assert unrelated['status'] != 'EXACT'


def test_colour_alias_black_ukrainian_not_conflict():
    row = {
        'Название': 'Marshall Major IV Bluetooth Black',
        'Производитель': 'Marshall',
        'Артикул': '11676',
        'Параметры': [{'name':'Цвет','value':'Black'}],
    }
    same = classify_match(row, 'Навушники Marshall Major IV Bluetooth чорний')
    assert same['status'] in {'EXACT','HIGH'}
    assert 'CONFLICT' not in same['status']


def test_real_colour_conflict_is_rejected():
    row = {
        'Название': 'Marshall Major IV Bluetooth Black',
        'Производитель': 'Marshall',
        'Артикул': '11676',
        'Параметры': [{'name':'Цвет','value':'Black'}],
    }
    other = classify_match(row, 'Навушники Marshall Major IV Bluetooth Brown')
    assert other['status'] == 'CONFLICT'


def test_consensus_price_outlier_excluded():
    market = [
        {'price': 434, 'url':'a', 'marketplace':'Rozetka'},
        {'price': 349, 'url':'b', 'marketplace':'Prom'},
        {'price': 299, 'url':'c', 'marketplace':'Epicentr'},
    ]
    other = [
        {'price': 1999, 'url':'d', 'host':'bad.ua', 'marketplace':'Інші магазини'},
        {'price': 299, 'url':'e', 'host':'good.ua', 'marketplace':'Інші магазини'},
    ]
    audits = [{'URL':x['url'], 'Статус цены':'ПІДТВЕРДЖЕНА', 'Причина проверки':''} for x in market+other]
    cfg = {'price_consensus_verification_enabled':True, 'price_consensus_ratio_limit':3.0, 'price_consensus_min_peer_refs':2}
    km, ko, sm, so = _post_verify_price_outliers(market, other, 334, audits, cfg, lambda x: None)
    assert [x['price'] for x in so] == [1999]
    assert all(x['price'] != 1999 for x in ko)
    assert next(x for x in audits if x['URL']=='d')['Статус цены'] == '⚠️ АНОМАЛЬНА ЦІНА'
