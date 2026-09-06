from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

STRATEGY=Path('results/wow_strategy_latest.json')
PLAN21=Path('results/procurement_plan_v21.json')
OFFERS=Path('results/retail_offers_v22.json')
OUT=Path('results/procurement_plan_v22.json')


def main()->None:
    data=json.loads(STRATEGY.read_text(encoding='utf-8'));p=json.loads(PLAN21.read_text(encoding='utf-8'));offers=json.loads(OFFERS.read_text(encoding='utf-8'))
    assert (data.get('offer_optimizer_v22') or {}).get('active') is True
    assert p.get('version')=='V21'
    p['version']='V22';p['generated_at']=datetime.now(timezone.utc).isoformat();p['core_model']='DBA-WOW-SELF-BUILD-FIRST-V20 + V22_DELIVERED_RETAIL_DEAL_OPTIMIZER'
    fit=(p.get('z20_fit_authoritative') or {}).get('status','UNKNOWN')
    blockers=[b for b in (p.get('blockers') or []) if b.get('kind')!='GPU_FIT']
    if fit!='VERIFIED':
        blockers.append({'kind':'GPU_FIT','procurement_action':'VERIFY_FIT','actionable_now':False,'reason':'Exact board-partner GPU model/dimensions must be proven before the complete Z20 build is buy-ready. UNKNOWN is retained as a candidate but cannot be called KØBSKLAR.'})
    p['blockers']=blockers
    p.setdefault('headline',{})['ready_to_buy_complete_build_today']=bool(not blockers and fit=='VERIFIED')
    p['headline']['z20_fit']=fit
    by_sku={str(r.get('sku')):r for r in offers.get('rows') or [] if r.get('sku')}
    retail_rows=[]
    for a in p.get('actions') or []:
        if a.get('source')!='NEW RETAIL':continue
        sku=str(a.get('sku') or '');r=by_sku.get(sku) or {};best=r.get('best_delivered_offer') or {}
        assert r.get('delivered_price_verified') is True and best,f"Selected new component lacks V22 delivered offer: {a.get('name')}"
        assert int(a.get('ask') or 0)==int(r.get('delivered_price_dkk') or 0)
        a['procurement_action']='BUY_NOW';a['actionable_now']=True;a['availability_status']='IN_STOCK_DELIVERED_PRICE_VERIFIED'
        a['reason']='Concrete retailer and in-stock delivery-inclusive total verified; this delivered price is the authoritative V22 acquisition cost.'
        a['store_offer']={'seller':r.get('seller'),'url':r.get('buy_url'),'price':r.get('delivered_price_dkk'),'delivered_price_dkk':r.get('delivered_price_dkk'),'item_price_dkk':r.get('item_price_dkk'),'shipping_dkk':r.get('shipping_dkk'),'delivered_price_method':r.get('delivered_price_method'),'deal_type':r.get('deal_type'),'normal_price_dkk':r.get('normal_price_dkk'),'market_reference_delivered_dkk':r.get('market_reference_delivered_dkk')}
        retail_rows.append({'kind':a.get('kind'),'sku':sku,'name':a.get('name'),'seller':r.get('seller'),'buy_url':r.get('buy_url'),'comparison_url':r.get('product_url'),'item_price_dkk':r.get('item_price_dkk'),'shipping_dkk':r.get('shipping_dkk'),'delivered_price_dkk':r.get('delivered_price_dkk'),'delivered_price_method':r.get('delivered_price_method'),'deal_type':r.get('deal_type'),'normal_price_dkk':r.get('normal_price_dkk'),'market_reference_delivered_dkk':r.get('market_reference_delivered_dkk')})
    p['retail_offers_v22']={'model':offers.get('model'),'products_total':offers.get('products_total'),'delivered_price_verified':offers.get('delivered_price_verified'),'deal_candidates':offers.get('deal_candidates'),'selected':retail_rows,'price_basis':'DELIVERED_PRICE_DKK','rule':'Compare normal price, promotions and current store offers on delivered cost. Explicit discount labels are informative only; the lowest effective delivered-cost compatible component wins after the same rational-premium feature logic.'}
    OUT.write_text(json.dumps(p,ensure_ascii=False,indent=2),encoding='utf-8')
    data['procurement_v22']=p;data['procurement_version']='V22';data['z20_fit_authoritative_v22']=p.get('z20_fit_authoritative');STRATEGY.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'V22_PROCUREMENT':True,'ask_total':p['headline'].get('ask_total'),'target_total':p['headline'].get('target_total'),'walk_away_total':p['headline'].get('walk_away_total'),'fit':fit,'ready_today':p['headline'].get('ready_to_buy_complete_build_today'),'blockers':[str(x.get('kind'))+':'+str(x.get('procurement_action')) for x in blockers],'selected_new':len(retail_rows)},ensure_ascii=False))


if __name__=='__main__':main()
