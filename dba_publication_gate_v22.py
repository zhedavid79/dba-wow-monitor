from __future__ import annotations

import json
from pathlib import Path

STRATEGY=Path('results/wow_strategy_latest.json')
PLAN=Path('results/procurement_plan_v22.json')
OFFERS=Path('results/retail_offers_v22.json')
AVAIL=Path('results/retail_availability_v22.json')
COMPLETE=Path('results/wow_a3_latest.json')
REPORTS=(Path('results/wow_self_build_report_v22.md'),Path('results/wow_self_build_report.md'),Path('results/wow_platform_first_report.md'),Path('results/wow_a3_report.md'))
ISSUES=Path('dba_known_listing_issues_v21.json')
REQUIRED={'MOTHERBOARD','PSU','CASE','COOLER','RAM','CPU','GPU','STORAGE'}


def main()->None:
    for f in (STRATEGY,PLAN,OFFERS,AVAIL,COMPLETE,ISSUES,*REPORTS):assert f.exists(),f'Missing V22 publication input: {f}'
    s=json.loads(STRATEGY.read_text(encoding='utf-8'));p=json.loads(PLAN.read_text(encoding='utf-8'));o=json.loads(OFFERS.read_text(encoding='utf-8'));a=json.loads(AVAIL.read_text(encoding='utf-8'));c=json.loads(COMPLETE.read_text(encoding='utf-8'));issues=json.loads(ISSUES.read_text(encoding='utf-8'))
    assert s.get('gate_passed') is True and s.get('model_version')=='DBA-WOW-SELF-BUILD-FIRST-V20'
    assert s.get('procurement_version')=='V22' and s.get('procurement_core_version')=='V22_DELIVERED_RETAIL_DEAL_OPTIMIZER'
    opt=s.get('offer_optimizer_v22') or {};assert opt.get('active') is True and opt.get('price_basis')=='DELIVERED_PRICE_DKK'
    assert p.get('version')=='V22' and o.get('model')=='V22_STORE_LEVEL_DELIVERED_PRICE_AND_DEALS' and a.get('model')=='V22_SELECTED_DELIVERED_RETAIL_AVAILABILITY'
    assert int(o.get('products_total') or 0)>0 and int(o.get('delivered_price_verified') or 0)>0

    rec=s.get('recommended_self_build') or {};h=p.get('headline') or {};assert rec and int(h.get('ask_total') or 0)==int(rec.get('tcwp') or 0)
    assert set(x.get('kind') for x in p.get('actions') or [])==REQUIRED
    assert 0<int(h.get('first_bid_total') or 0)<=int(h.get('target_total') or 0)<=int(h.get('walk_away_total') or 0)
    fit=(p.get('z20_fit_authoritative') or {}).get('status');assert fit in {'VERIFIED','UNKNOWN','NO'} and h.get('z20_fit')==fit
    if fit!='VERIFIED':
        assert h.get('ready_to_buy_complete_build_today') is False
        assert any(x.get('kind')=='GPU_FIT' and x.get('procurement_action')=='VERIFY_FIT' for x in p.get('blockers') or []),'UNKNOWN/NO fit lacks explicit blocker'
    if h.get('ready_to_buy_complete_build_today') is True:assert fit=='VERIFIED' and not p.get('blockers')

    new=[x for x in rec.get('components') or [] if x.get('source')=='NEW RETAIL'];assert new
    assert len(new)==int(a.get('selected_total') or 0)==int(a.get('concrete_in_stock') or 0)==int(a.get('t1_revalidated') or 0)
    assert not a.get('failures'),'Selected retail T1 has failures'
    avail_by_sku={str(r.get('sku') or ''):r for r in a.get('rows') or [] if r.get('sku')}
    offer_by_sku={str(r.get('sku') or ''):r for r in o.get('rows') or [] if r.get('sku')}
    for x in new:
        assert x.get('price_evidence')=='LIVE_DELIVERED_RETAIL_OFFER_V22'
        assert x.get('retail_offer_verified_v22') is True and x.get('seller') and x.get('url')
        assert x.get('availability')=='IN_STOCK_DELIVERED_PRICE_VERIFIED'
        assert x.get('delivered_price_method_v22') in {'PRISJAGT_PRICE_INCL_DELIVERY','ITEM_PLUS_EXACT_SHIPPING'}
        assert int(x.get('price') or 0)==int(x.get('delivered_price_dkk') or 0)>0
        if x.get('delivered_price_method_v22')=='ITEM_PLUS_EXACT_SHIPPING':assert int(x['price'])==int(x.get('item_price_dkk') or 0)+int(x.get('shipping_dkk') or 0)

        sku=str(x.get('sku') or '')
        rr=offer_by_sku.get(sku) or {};best=rr.get('best_delivered_offer') or {}
        assert rr.get('delivered_price_verified') is True and best.get('price_sanity_ok') is True,'Selected retail offer did not pass V22 same-page price-floor sanity'
        floor=int(rr.get('same_page_lowest_price_dkk') or best.get('same_page_lowest_price_dkk') or 0);dp=int(rr.get('delivered_price_dkk') or 0)
        assert floor>0 and dp>0
        tolerance=max(5,int(round(floor*.01)))
        assert dp+tolerance>=floor,f'Selected delivered price below same-page current price floor: {dp}/{floor}'
        assert str(best.get('price_sanity_method') or '').startswith('AT_OR_ABOVE_SAME_PAGE_PRICE_FLOOR')
        price_line=str(best.get('displayed_price_line') or '').lower()
        assert not any(t in price_line for t in ('pr. md','pr md','/md','månedlig','afbetaling','delbetaling','finansiering','per month')),'Financing amount leaked into authoritative retail price'

        ar=avail_by_sku.get(sku) or {}
        assert ar.get('t1_revalidated') is True,'Selected retail offer lacks immediate T1 revalidation'
        assert ar.get('price_verified') is True and ar.get('same_offer_url_verified') is True
        assert int(ar.get('current_price') or 0)==int(x.get('price') or 0)
        assert str(ar.get('current_url') or '')==str(x.get('url') or '')
        assert ar.get('availability_status')=='IN_STOCK_DELIVERED_PRICE_T1_REVALIDATED'

    for x in p.get('actions') or []:
        if x.get('source')=='NEW RETAIL':
            assert x.get('procurement_action')=='BUY_NOW' and x.get('actionable_now') is True
            store=x.get('store_offer') or {};assert store.get('seller') and store.get('url') and int(store.get('delivered_price_dkk') or 0)==int(x.get('ask') or 0)
        elif x.get('source')=='USED ASK':
            assert x.get('procurement_action') in {'BUY_NOW','BID','WAIT','VERIFY_VALUE'}

    active={str(k) for k,v in (issues.get('listings') or {}).items() if v.get('severity')=='HARD_EXCLUDE' and v.get('cleared') is not True}
    decision=c.get('decision_summary') or {};assert str(decision.get('buy_now_listing_id') or '') not in active
    assert all(str(r.get('listing_id') or '') not in active for r in c.get('ranked') or [])
    assert '7969913' in active and str(decision.get('buy_now_listing_id') or '')!='7969913'
    for r in s.get('complete_pc_reference') or []:
        ids={str(x.get('listing_id')) for x in r.get('components') or [] if x.get('listing_id')};assert not (ids & active)

    raw=int(p.get('raw_count') or 0);unique=int(p.get('unique_count') or 0);assert raw>=unique>0
    sigs=set()
    for r in p.get('unique_self_builds') or []:
        sig=tuple((x.get('kind'),x.get('listing_id') or x.get('sku') or x.get('url') or x.get('name')) for x in r.get('components') or []);assert sig not in sigs; sigs.add(sig)

    texts=[x.read_text(encoding='utf-8') for x in REPORTS];assert len(set(texts))==1,'V22 canonical/aliases differ';report=texts[0]
    assert report.startswith('# FULDT PÅLIDELIG DBA-PRISRAPPORT — WoW SELF-BUILD FIRST V22')
    for marker in ('Hvad skal jeg gøre i dag?','Nye dele — tilbud, butik og leveret pris','Andre kvalificerede nye tilbud fundet','KØBSKLAR-gate','Historiske hard exclusions','Selvbyg-ranking — unikke BOM','Hvorfor hoved-GPU'):
        assert marker.lower() in report.lower(),marker
    assert 'Z20 LIKELY' not in report
    expected_ready='JA' if h.get('ready_to_buy_complete_build_today') else 'NEJ'
    assert f'**Kan hele buildet købes rationelt i dag? {expected_ready}**' in report,'Top procurement headline disagrees with authoritative V22 readiness'
    assert f'**Hele buildet KØBSKLAR nu: {expected_ready}**' in report,'KØBSKLAR gate disagrees with authoritative V22 readiness'
    if fit!='VERIFIED':
        assert '**Kan hele buildet købes rationelt i dag? JA**' not in report,'UNKNOWN/NO fit leaked a buy-ready JA headline'
        assert '**Hele buildet KØBSKLAR nu: JA**' not in report,'UNKNOWN/NO fit leaked a KØBSKLAR JA gate'
    for x in new:assert x.get('url') in report
    print(json.dumps({'PASS':True,'publication_gate':'V22','ask_total':h.get('ask_total'),'target_total':h.get('target_total'),'walk_away_total':h.get('walk_away_total'),'fit':fit,'ready_today':h.get('ready_to_buy_complete_build_today'),'raw_routes':raw,'unique_routes':unique,'retail_products':o.get('products_total'),'retail_delivered_verified':o.get('delivered_price_verified'),'deal_candidates':o.get('deal_candidates'),'selected_new':len(new),'selected_retail_t1':a.get('t1_revalidated'),'upstream_buy_now':decision.get('buy_now_listing_id')},ensure_ascii=False))


if __name__=='__main__':main()
