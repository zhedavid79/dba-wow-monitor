from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

STRATEGY=Path('results/wow_strategy_latest.json')
PLAN=Path('results/procurement_plan_v22.json')
OFFERS=Path('results/retail_offers_v22.json')
AVAIL=Path('results/retail_availability_v22.json')
COMPLETE=Path('results/wow_a3_latest.json')
REPORTS=(Path('results/wow_self_build_report_v22.md'),Path('results/wow_self_build_report.md'),Path('results/wow_platform_first_report.md'),Path('results/wow_a3_report.md'))
ISSUES=Path('dba_known_listing_issues_v21.json')
REQUIRED={'MOTHERBOARD','PSU','CASE','COOLER','RAM','CPU','GPU','STORAGE'}


def external(url:str)->bool:
    host=urlparse(str(url or '')).netloc.lower()
    return bool(host and 'prisjagt.dk' not in host)


def main()->None:
    for f in (STRATEGY,PLAN,OFFERS,AVAIL,COMPLETE,ISSUES,*REPORTS):
        assert f.exists(),f'Missing V22 publication input: {f}'
    s=json.loads(STRATEGY.read_text(encoding='utf-8'))
    p=json.loads(PLAN.read_text(encoding='utf-8'))
    o=json.loads(OFFERS.read_text(encoding='utf-8'))
    a=json.loads(AVAIL.read_text(encoding='utf-8'))
    c=json.loads(COMPLETE.read_text(encoding='utf-8'))
    issues=json.loads(ISSUES.read_text(encoding='utf-8'))

    assert s.get('gate_passed') is True and s.get('model_version')=='DBA-WOW-SELF-BUILD-FIRST-V20'
    assert s.get('procurement_version')=='V22'
    assert s.get('procurement_core_version')=='V22_DIRECT_RETAILER_FAIL_CLOSED'
    opt=s.get('offer_optimizer_v22') or {}
    assert opt.get('active') is True
    assert opt.get('prisjagt_only_policy')=='REFERENCE_ONLY_NEVER_BUY_READY'
    assert p.get('version')=='V22'
    assert o.get('model')=='V22_STORE_LEVEL_DELIVERED_PRICE_AND_DEALS'
    assert a.get('model')=='V22_SELECTED_RETAIL_DIRECT_OR_REFERENCE_AVAILABILITY'
    assert int(o.get('products_total') or 0)>0

    rec=s.get('recommended_self_build') or {}
    h=p.get('headline') or {}
    assert rec and int(h.get('ask_total') or 0)==int(rec.get('tcwp') or 0)
    assert set(x.get('kind') for x in p.get('actions') or [])==REQUIRED
    assert 0<int(h.get('first_bid_total') or 0)<=int(h.get('target_total') or 0)<=int(h.get('walk_away_total') or 0)

    fit=(p.get('z20_fit_authoritative') or {}).get('status')
    assert fit in {'VERIFIED','UNKNOWN','NO'} and h.get('z20_fit')==fit
    if fit!='VERIFIED':
        assert h.get('ready_to_buy_complete_build_today') is False
        assert any(x.get('kind')=='GPU_FIT' and x.get('procurement_action')=='VERIFY_FIT' for x in p.get('blockers') or [])

    new=[x for x in rec.get('components') or [] if x.get('source')=='NEW RETAIL']
    assert new
    assert len(new)==int(a.get('selected_total') or 0)
    assert int(a.get('identity_verified') or 0)==len(new)
    assert not a.get('failures'),'Selected retail verification has failures'

    actions_by_kind={str(x.get('kind')):x for x in p.get('actions') or []}
    avail_by_sku={str(r.get('sku') or ''):r for r in a.get('rows') or [] if r.get('sku')}
    direct_count=0
    reference_count=0
    for x in new:
        sku=str(x.get('sku') or '')
        ar=avail_by_sku.get(sku) or {}
        act=actions_by_kind.get(str(x.get('kind'))) or {}
        direct=x.get('retail_offer_verified_v22') is True
        if direct:
            direct_count+=1
            assert x.get('external_url_resolved_v22') is True
            assert x.get('price_evidence')=='LIVE_DIRECT_RETAILER_DELIVERED_OFFER_V22'
            assert x.get('availability')=='IN_STOCK_DIRECT_RETAILER_VERIFIED'
            assert x.get('seller') and external(str(x.get('url') or ''))
            assert act.get('procurement_action')=='BUY_NOW' and act.get('actionable_now') is True
            store=act.get('store_offer') or {}
            assert external(str(store.get('url') or ''))
            assert ar.get('direct_expected') is True
            assert ar.get('t1_revalidated') is True and ar.get('external_retailer_resolved') is True
            assert ar.get('availability_status')=='IN_STOCK_DIRECT_RETAILER_T1_REVALIDATED'
        else:
            reference_count+=1
            assert x.get('external_url_resolved_v22') is False
            assert x.get('price_evidence')=='LIVE_RETAIL_COMPARISON_REFERENCE_V22'
            assert x.get('availability')=='PRICE_REFERENCE_ONLY_CHECK_STORE'
            assert act.get('procurement_action')=='CHECK_STORE' and act.get('actionable_now') is False
            assert not act.get('store_offer')
            assert ar.get('direct_expected') is False
            assert ar.get('reference_revalidated') is True
            assert ar.get('t1_revalidated') is False
            assert ar.get('availability_status')=='PRICE_REFERENCE_ONLY_CHECK_STORE'

    assert direct_count==int((p.get('retail_offers_v22') or {}).get('direct_buy_ready_selected') or 0)
    assert reference_count==int((p.get('retail_offers_v22') or {}).get('reference_only_selected') or 0)
    if reference_count:
        assert h.get('ready_to_buy_complete_build_today') is False
        assert h.get('authoritative_purchase_total') is None
        assert h.get('ask_total_is_reference_only') is True
        assert any(x.get('kind')=='RETAIL_DIRECT_VERIFY' for x in p.get('blockers') or [])
    else:
        assert h.get('authoritative_purchase_total')==h.get('ask_total')

    if h.get('ready_to_buy_complete_build_today') is True:
        assert fit=='VERIFIED' and not p.get('blockers') and reference_count==0

    for x in p.get('actions') or []:
        if x.get('source')=='USED ASK':
            assert x.get('procurement_action') in {'BUY_NOW','BID','WAIT','VERIFY_VALUE'}

    active={str(k) for k,v in (issues.get('listings') or {}).items() if v.get('severity')=='HARD_EXCLUDE' and v.get('cleared') is not True}
    decision=c.get('decision_summary') or {}
    assert str(decision.get('buy_now_listing_id') or '') not in active
    assert all(str(r.get('listing_id') or '') not in active for r in c.get('ranked') or [])
    assert '7969913' in active and str(decision.get('buy_now_listing_id') or '')!='7969913'
    for r in s.get('complete_pc_reference') or []:
        ids={str(x.get('listing_id')) for x in r.get('components') or [] if x.get('listing_id')}
        assert not (ids & active)

    raw=int(p.get('raw_count') or 0);unique=int(p.get('unique_count') or 0)
    assert raw>=unique>0
    sigs=set()
    for r in p.get('unique_self_builds') or []:
        sig=tuple((x.get('kind'),x.get('listing_id') or x.get('sku') or x.get('url') or x.get('name')) for x in r.get('components') or [])
        assert sig not in sigs
        sigs.add(sig)

    texts=[x.read_text(encoding='utf-8') for x in REPORTS]
    assert len(set(texts))==1,'V22 canonical/aliases differ'
    report=texts[0]
    assert report.startswith('# FULDT PÅLIDELIG DBA-PRISRAPPORT — WoW SELF-BUILD FIRST V22')
    for marker in ('Hvad skal jeg gøre i dag?','Nye dele — tilbud, butik og leveret pris','Andre kvalificerede nye tilbud fundet','KØBSKLAR-gate','Historiske hard exclusions','Selvbyg-ranking — unikke BOM','Hvorfor hoved-GPU'):
        assert marker.lower() in report.lower(),marker
    assert 'Z20 LIKELY' not in report
    expected_ready='JA' if h.get('ready_to_buy_complete_build_today') else 'NEJ'
    assert f'**Kan hele buildet købes rationelt i dag? {expected_ready}**' in report
    assert f'**Hele buildet KØBSKLAR nu: {expected_ready}**' in report
    if reference_count:
        assert '**TJEK BUTIK**' in report
        assert 'ingen samlet autoritativ købsklar pris' in report.lower()
    if fit!='VERIFIED' or reference_count:
        assert '**Kan hele buildet købes rationelt i dag? JA**' not in report
        assert '**Hele buildet KØBSKLAR nu: JA**' not in report

    print(json.dumps({
        'PASS':True,
        'publication_gate':'V22_DIRECT_RETAILER_FAIL_CLOSED',
        'ask_total_reference':h.get('ask_total'),
        'authoritative_purchase_total':h.get('authoritative_purchase_total'),
        'fit':fit,
        'ready_today':h.get('ready_to_buy_complete_build_today'),
        'direct_buy_ready_new':direct_count,
        'reference_only_new':reference_count,
        'raw_routes':raw,
        'unique_routes':unique,
        'upstream_buy_now':decision.get('buy_now_listing_id'),
    },ensure_ascii=False))


if __name__=='__main__':
    main()
