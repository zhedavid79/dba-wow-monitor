from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import dba_component_optimizer_v19 as core
import dba_component_market_v19 as market
import dba_self_build_v20 as v20
import dba_self_build_v20_authoritative as auth20

RETAIL=Path('results/retail_prices_latest.json')
STRATEGY=Path('results/wow_strategy_latest.json')
ORIGINAL_SNAPSHOT=core._snapshot_candidates
ORIGINAL_NEW32=v20.best_new_32gb_price


def offer_index()->dict[str,dict]:
    doc=json.loads(RETAIL.read_text(encoding='utf-8'))
    return {str(p.get('sku')):(p.get('retail_offer_v22') or {}) for p in doc.get('products') or [] if p.get('sku')}


def delivered_snapshot_candidates(kind:str)->list[dict]:
    idx=offer_index();rows=[]
    for c in deepcopy(core.RETAIL_CANDIDATES.get(kind) or []):
        offer=idx.get(str(c.get('sku') or '')) or {};delivered=int(offer.get('delivered_price_dkk') or 0);buy_url=str(offer.get('buy_url') or '');seller=str(offer.get('seller') or '')
        if offer.get('delivered_price_verified') is not True or delivered<=0 or not buy_url or not seller:continue
        item=offer.get('item_price_dkk');shipping=offer.get('shipping_dkk');method=str(offer.get('delivered_price_method') or '')
        if method=='ITEM_PLUS_EXACT_SHIPPING':
            if item is None or shipping is None or delivered!=int(item)+int(shipping):continue
        elif method!='PRISJAGT_PRICE_INCL_DELIVERY':
            continue
        c.update({'price':delivered,'delivered_price_dkk':delivered,'item_price_dkk':item,'shipping_dkk':shipping,'delivered_price_method_v22':method,'seller':seller,'comparison_url':c.get('url'),'url':buy_url,'deal_type_v22':offer.get('deal_type'),'normal_price_dkk_v22':offer.get('normal_price_dkk'),'market_reference_delivered_dkk_v22':offer.get('market_reference_delivered_dkk'),'price_evidence':'LIVE_DELIVERED_RETAIL_OFFER_V22','availability':'IN_STOCK_DELIVERED_PRICE_VERIFIED','retail_offer_verified_v22':True})
        rows.append(c)
    return rows


def best_new_32gb_delivered(retail:dict)->int|None:
    vals=[]
    for p in retail.get('products') or []:
        name=str(p.get('name') or '').lower();cap=int(p.get('capacity_gb') or 0)
        if cap<32 and not ('32gb' in name and 'ddr5' in name):continue
        o=p.get('retail_offer_v22') or {}
        if o.get('delivered_price_verified') is True and int(o.get('delivered_price_dkk') or 0)>0:vals.append(int(o['delivered_price_dkk']))
    return min(vals) if vals else None


def validate_selected(data:dict)->dict:
    rec=data.get('recommended_self_build') or {};new=[c for c in rec.get('components') or [] if c.get('source')=='NEW RETAIL'];assert new,'V22 selected no NEW RETAIL components'
    for c in new:
        assert c.get('retail_offer_verified_v22') is True,f"V22 selected unverified delivered retail: {c.get('name')}"
        assert c.get('price_evidence')=='LIVE_DELIVERED_RETAIL_OFFER_V22' and c.get('seller') and c.get('url')
        method=str(c.get('delivered_price_method_v22') or '')
        assert method in {'PRISJAGT_PRICE_INCL_DELIVERY','ITEM_PLUS_EXACT_SHIPPING'}
        if method=='ITEM_PLUS_EXACT_SHIPPING':assert int(c.get('price') or 0)==int(c.get('item_price_dkk') or 0)+int(c.get('shipping_dkk') or 0)
    return {'selected_new_count':len(new),'selected_delivered_total':sum(int(c.get('price') or 0) for c in new),'selected_item_total_known':sum(int(c.get('item_price_dkk') or 0) for c in new if c.get('item_price_dkk') is not None),'selected_shipping_total_known':sum(int(c.get('shipping_dkk') or 0) for c in new if c.get('shipping_dkk') is not None),'delivery_inclusive_count':sum(1 for c in new if c.get('delivered_price_method_v22')=='PRISJAGT_PRICE_INCL_DELIVERY')}


def main()->None:
    retail=json.loads(RETAIL.read_text(encoding='utf-8'));gate=retail.get('offer_gate_v22') or {}
    assert gate.get('model')=='V22_STORE_LEVEL_DELIVERED_PRICE_AND_DEALS' and int(gate.get('delivered_price_verified') or 0)>0
    core._snapshot_candidates=delivered_snapshot_candidates;v20.best_new_32gb_price=best_new_32gb_delivered
    try:auth20.main()
    finally:
        core._snapshot_candidates=ORIGINAL_SNAPSHOT;v20.best_new_32gb_price=ORIGINAL_NEW32
    data=json.loads(STRATEGY.read_text(encoding='utf-8'));stats=validate_selected(data);coverage=((data.get('component_market_coverage_v20') or {}).get('v19_coverage') or {})
    assert coverage.get('passed') is True,'V22 delivered-price candidate coverage below minimums'
    data['offer_optimizer_v22']={'active':True,'price_basis':'DELIVERED_PRICE_DKK','selection_rule':'New candidates are compared only after same-product identity, concrete retailer, stock and an authoritative delivery-inclusive total are proven. Pareto and rational-premium scoring use delivered price. A slightly more expensive new component may win only when capped project-relevant feature value justifies the delivered-price premium.','delivery_methods':['PRISJAGT_PRICE_INCL_DELIVERY','ITEM_PLUS_EXACT_SHIPPING'],'unknown_delivery_policy':'FAIL_CLOSED_AS_LEAD_NOT_BUY_READY','retail_offer_gate':gate,**stats}
    data['procurement_core_version']='V22_DELIVERED_RETAIL_DEAL_OPTIMIZER';STRATEGY.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    rec=data.get('recommended_self_build') or {}
    print(json.dumps({'V22_SELF_BUILD':True,'recommended_tcwp':rec.get('tcwp'),'cpu':rec.get('cpu'),'gpu':rec.get('gpu'),'selected_new_count':stats['selected_new_count'],'selected_new_delivered_total':stats['selected_delivered_total'],'coverage':coverage.get('passed')},ensure_ascii=False))


if __name__=='__main__':main()
