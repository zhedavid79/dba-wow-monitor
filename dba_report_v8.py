from __future__ import annotations

import dba_report_v7 as v7

v6 = v7.v6

# More robust live schema gate: use relevance-ranked searches instead of PRICE_ASC,
# so low-price placeholder/junk ads cannot crowd out valid PCs from the first page.
def schema_gate(session):
    attempts = []
    for q in ('rtx 3070 gaming pc','gaming pc rtx 4060','hp omen gaming','lenovo legion gaming'):
        try:
            data = v6.getj(session, v6.SEARCH_API, {'q':q})
        except Exception as e:
            attempts.append({'query':q,'error':str(e)})
            continue
        for d in (data.get('docs') or []):
            lid = str(d.get('id') or d.get('listingId') or d.get('itemId') or '')
            title0 = str(d.get('heading') or d.get('title') or '')
            p0 = v6.amount(d.get('price'))
            if not lid or not title0 or p0 is None or not (500 <= p0 <= v6.MAX_PRICE):
                continue
            try:
                item = (v6.getj(session, v6.ITEM_URL.format(id=lid)).get('itemData') or {})
            except Exception as e:
                attempts.append({'query':q,'listing_id':lid,'error':str(e)})
                continue
            p1 = v6.amount(item.get('price'))
            title1 = str(item.get('title') or '')
            if p1 is None or not (500 <= p1 <= v6.MAX_PRICE):
                continue
            if bool(item.get('disposed')) or not title1:
                continue
            return {'ok':True,'query':q,'listing_id':lid,'search_price':p0,'item_price':p1,'title':title1}
    raise SystemExit('PRICE DATA GATE FAILED — no plausible current live same-object listing could be verified; attempts='+str(attempts[-5:]))

v6.schema_gate = schema_gate

if __name__ == '__main__':
    v6.main()
