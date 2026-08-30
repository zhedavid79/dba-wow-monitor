from __future__ import annotations

import dba_report_v6 as v6

# Extend parser for gaming-laptop CPUs. These rules are prepended so exact mobile SKUs
# beat looser desktop/fallback matches from descriptions.
MOBILE_CPU_RULES = [
    (r'\bi9[- ]?14900hx\b','Core i9-14900HX',122),
    (r'\bi9[- ]?13980hx\b','Core i9-13980HX',119),
    (r'\bi9[- ]?13900(?:hx|h)\b','Core i9-13900H/HX',114),
    (r'\bi9[- ]?12900(?:hx|h)\b','Core i9-12900H/HX',104),
    (r'\bi7[- ]?14700hx\b','Core i7-14700HX',114),
    (r'\bi7[- ]?14650hx\b','Core i7-14650HX',111),
    (r'\bi7[- ]?13700hx\b','Core i7-13700HX',105),
    (r'\bi7[- ]?13700h\b','Core i7-13700H',99),
    (r'\bi7[- ]?13650hx\b','Core i7-13650HX',101),
    (r'\bi7[- ]?13620h\b','Core i7-13620H',94),
    (r'\bi7[- ]?12800h\b','Core i7-12800H',93),
    (r'\bi7[- ]?12700h\b','Core i7-12700H',91),
    (r'\bi7[- ]?12650h\b','Core i7-12650H',88),
    (r'\bi7[- ]?11800h\b','Core i7-11800H',76),
    (r'\bi5[- ]?14500hx\b','Core i5-14500HX',101),
    (r'\bi5[- ]?13500h\b','Core i5-13500H',91),
    (r'\bi5[- ]?13450hx\b','Core i5-13450HX',94),
    (r'\bi5[- ]?13420h\b','Core i5-13420H',86),
    (r'\bi5[- ]?12500h\b','Core i5-12500H',83),
    (r'\bi5[- ]?12450h\b','Core i5-12450H',78),
    (r'\bi5[- ]?11400h\b','Core i5-11400H',67),
    (r'\bryzen\s*9\s*7945hx\b|\b7945hx\b','Ryzen 9 7945HX',120),
    (r'\bryzen\s*9\s*7940hs\b|\b7940hs\b','Ryzen 9 7940HS',108),
    (r'\bryzen\s*7\s*8845hs\b|\b8845hs\b','Ryzen 7 8845HS',107),
    (r'\bryzen\s*7\s*7840hs\b|\b7840hs\b','Ryzen 7 7840HS',103),
    (r'\bryzen\s*7\s*7735hs\b|\b7735hs\b','Ryzen 7 7735HS',89),
    (r'\bryzen\s*7\s*6800h\b|\b6800h\b','Ryzen 7 6800H',84),
    (r'\bryzen\s*7\s*5800h\b|\b5800h\b','Ryzen 7 5800H',73),
    (r'\bryzen\s*5\s*7640hs\b|\b7640hs\b','Ryzen 5 7640HS',91),
    (r'\bryzen\s*5\s*6600h\b|\b6600h\b','Ryzen 5 6600H',76),
    (r'\bryzen\s*5\s*5600h\b|\b5600h\b','Ryzen 5 5600H',68),
]
v6.CPU_RULES = MOBILE_CPU_RULES + v6.CPU_RULES

# Strengthen the daily live schema gate: do not accept 1-kr placeholder/junk listings.
# Gate requires a plausible live asking price and same-object identity across search -> item.
def schema_gate(session):
    data = v6.getj(session, v6.SEARCH_API, {'q':'gaming pc','sort':'PRICE_ASC'})
    docs = data.get('docs') or []
    for d in docs:
        lid = str(d.get('id') or d.get('listingId') or d.get('itemId') or '')
        title0 = str(d.get('heading') or d.get('title') or '')
        p0 = v6.amount(d.get('price'))
        if not lid or not title0 or p0 is None or not (500 <= p0 <= v6.MAX_PRICE):
            continue
        item = (v6.getj(session, v6.ITEM_URL.format(id=lid)).get('itemData') or {})
        p1 = v6.amount(item.get('price'))
        title1 = str(item.get('title') or '')
        if p1 is None or not (500 <= p1 <= v6.MAX_PRICE):
            continue
        if bool(item.get('disposed')) or not title1:
            continue
        return {'ok':True,'listing_id':lid,'search_price':p0,'item_price':p1,'title':title1}
    raise SystemExit('PRICE DATA GATE FAILED — no plausible current live same-object listing could be verified')

v6.schema_gate = schema_gate

if __name__ == '__main__':
    v6.main()
