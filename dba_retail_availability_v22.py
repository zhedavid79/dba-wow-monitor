from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

STRATEGY=Path('results/wow_strategy_latest.json')
OFFERS=Path('results/retail_offers_v22.json')
OUT=Path('results/retail_availability_v22.json')
COMPAT=Path('results/retail_availability_v21.json')


def main()->None:
    data=json.loads(STRATEGY.read_text(encoding='utf-8'));offers=json.loads(OFFERS.read_text(encoding='utf-8'))
    rec=data.get('recommended_self_build') or {};by_sku={str(r.get('sku')):r for r in offers.get('rows') or [] if r.get('sku')}
    rows=[]
    for c in rec.get('components') or []:
        if c.get('source')!='NEW RETAIL':continue
        sku=str(c.get('sku') or '');r=by_sku.get(sku) or {};best=r.get('best_delivered_offer') or {}
        verified=bool(r.get('delivered_price_verified') and best and int(r.get('delivered_price_dkk') or 0)==int(c.get('price') or 0))
        row={'kind':c.get('kind'),'name':c.get('name'),'url':c.get('url'),'sku':sku,'expected_price':int(c.get('price') or 0),'verified_at':r.get('verified_at'),'identity_verified':r.get('identity_verified') is True,'price_verified':verified,'concrete_in_stock':verified,'availability_status':'IN_STOCK_DELIVERED_PRICE_VERIFIED' if verified else 'DELIVERED_PRICE_UNPROVEN','delivered_price_method':r.get('delivered_price_method'),'item_price_dkk':r.get('item_price_dkk'),'shipping_dkk':r.get('shipping_dkk'),'store_offer':({'price':int(r.get('delivered_price_dkk') or 0),'delivered_price_dkk':int(r.get('delivered_price_dkk') or 0),'item_price_dkk':r.get('item_price_dkk'),'shipping_dkk':r.get('shipping_dkk'),'seller':r.get('seller'),'url':r.get('buy_url'),'availability':'IN_STOCK','deal_type':r.get('deal_type'),'normal_price_dkk':r.get('normal_price_dkk'),'delivered_price_method':r.get('delivered_price_method')} if verified else None)}
        rows.append(row)
    assert rows,'V22 selected no new retail components'
    assert all(r.get('identity_verified') for r in rows),'V22 selected retail identity not verified'
    assert all(r.get('concrete_in_stock') for r in rows),'V22 selected new part lacks delivered-price/stock proof'
    doc={'generated_at':datetime.now(timezone.utc).isoformat(),'model':'V22_SELECTED_DELIVERED_RETAIL_AVAILABILITY','selected_total':len(rows),'identity_verified':sum(1 for x in rows if x.get('identity_verified')),'concrete_in_stock':sum(1 for x in rows if x.get('concrete_in_stock')),'rows':rows}
    OUT.parent.mkdir(parents=True,exist_ok=True);text=json.dumps(doc,ensure_ascii=False,indent=2);OUT.write_text(text,encoding='utf-8');COMPAT.write_text(text,encoding='utf-8')
    print(json.dumps({'V22_RETAIL_AVAILABILITY':True,'selected':len(rows),'all_buy_ready':all(x.get('concrete_in_stock') for x in rows),'delivered_total':sum(int(x.get('expected_price') or 0) for x in rows)},ensure_ascii=False))


if __name__=='__main__':main()
