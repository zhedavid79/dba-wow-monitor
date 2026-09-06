from __future__ import annotations

import json
from pathlib import Path

STRATEGY=Path('results/wow_strategy_latest.json')
PLAN=Path('results/procurement_plan_v21.json')
AVAIL=Path('results/retail_availability_v21.json')
REPORT=Path('results/wow_self_build_report_v21.md')
CANONICAL=Path('results/wow_self_build_report.md')
REQUIRED_KINDS={'MOTHERBOARD','PSU','CASE','COOLER','RAM','CPU','GPU','STORAGE'}


def main()->None:
    d=json.loads(STRATEGY.read_text(encoding='utf-8'));p=json.loads(PLAN.read_text(encoding='utf-8'));a=json.loads(AVAIL.read_text(encoding='utf-8'))
    text=REPORT.read_text(encoding='utf-8');canonical=CANONICAL.read_text(encoding='utf-8')
    assert d.get('gate_passed') is True
    assert d.get('model_version')=='DBA-WOW-SELF-BUILD-FIRST-V20'
    assert d.get('procurement_version')=='V21'
    assert p.get('version')=='V21'
    assert (d.get('component_market_coverage_v20') or {}).get('passed') is True
    h=p.get('headline') or {};rec=d.get('recommended_self_build') or {}
    assert int(h.get('ask_total') or 0)==int(rec.get('tcwp') or 0),'ASK build must equal selected BOM TCWP'
    assert 0<int(h.get('target_total') or 0)<=int(h.get('walk_away_total') or 0),'target/walk-away total ordering invalid'
    assert int(h.get('first_bid_total') or 0)<=int(h.get('target_total') or 0)
    assert set(x.get('kind') for x in p.get('actions') or [])==REQUIRED_KINDS

    for x in p.get('actions') or []:
        assert int(x.get('ask') or 0)>0 and x.get('url')
        pa=x.get('procurement_action')
        assert pa in {'BUY_NOW','BID','WAIT','CHECK_STOCK','VERIFY_VALUE'}
        if x.get('source')=='USED ASK':
            assert x.get('market_action') in {'STRONG_BUY','BUY','FAIR','WAIT','NO_VALUE_MODEL'}
            if x.get('market_action')=='WAIT':assert pa=='WAIT'
            if pa=='BUY_NOW':assert int(x.get('ask'))<=int(x.get('target') or x.get('walk_away'))
        else:
            if x.get('availability_status')!='IN_STOCK_VERIFIED':assert pa=='CHECK_STOCK'
            if pa=='BUY_NOW':assert x.get('store_offer') and x.get('availability_status')=='IN_STOCK_VERIFIED'

    fit=p.get('z20_fit_authoritative') or {}
    assert fit.get('status') in {'VERIFIED','UNKNOWN','NO'}
    assert h.get('z20_fit')==fit.get('status')
    assert 'Z20 LIKELY' not in text,'Legacy LIKELY leaked into V21 user-facing report'
    assert f"Z20 {fit.get('status')}" in text

    raw=int(p.get('raw_count') or 0);unique=int(p.get('unique_count') or 0)
    assert raw>=unique>0
    sigs=[]
    for r in p.get('unique_self_builds') or []:
        sig=tuple((c.get('kind'),c.get('listing_id') or c.get('sku') or c.get('url') or c.get('name')) for c in r.get('components') or [])
        assert sig not in sigs,'Duplicate BOM survived V21 dedupe'
        sigs.append(sig)

    excluded={str(x.get('listing_id')) for x in p.get('historical_exclusions') or []}
    assert '7969913' in excluded,'Known defect history did not fire'
    assert '/item/7969913)' not in text
    for r in d.get('complete_pc_reference') or []:
        ids={str(c.get('listing_id')) for c in r.get('components') or [] if c.get('listing_id')}
        assert '7969913' not in ids

    assert a.get('model')=='V21_SELECTED_RETAIL_AVAILABILITY'
    assert int(a.get('selected_total') or 0)>0
    assert int(a.get('identity_verified') or 0)==int(a.get('selected_total') or 0)
    new_actions=[x for x in p.get('actions') or [] if x.get('source')=='NEW RETAIL']
    assert len(new_actions)==int(a.get('selected_total') or 0)

    ram=next(x for x in p['actions'] if x.get('kind')=='RAM')
    if ram.get('procurement_action')=='WAIT':
        assert 'Køb ikke RAM-kittet til ASK' in text
        assert int(ram.get('ask') or 0)>int(ram.get('walk_away') or 0)

    comps=p.get('gpu_comparison') or []
    assert len(comps)>=2
    assert any(x.get('gpu')==rec.get('gpu') for x in comps)
    assert any(x.get('gpu')=='RTX 2080 Super' for x in comps),'2080 Super head-to-head missing'
    assert any(x.get('gpu')=='RX 6700 XT' for x in comps),'6700 XT head-to-head missing'

    deltas=p.get('price_deltas') or []
    assert set(x.get('kind') for x in deltas)==REQUIRED_KINDS
    assert all(x.get('previous') is not None for x in deltas),'Previous-run price baseline missing'
    assert all(x.get('baseline') is not None for x in deltas),'V19 golden price baseline missing'

    for marker in ('Hvad skal jeg gøre i dag?','ASK-build','Target-build','Walk-away-build','Retail availability','Prisændring siden sidste run','Historiske hard exclusions','Selvbyg-ranking — unikke BOM','Hvorfor hoved-GPU'):
        assert marker.lower() in text.lower(),marker
    assert text==canonical,'Canonical report differs from V21 report'
    print(json.dumps({'PASS':True,'publication_gate':'V21','ask_total':h.get('ask_total'),'target_total':h.get('target_total'),'walk_away_total':h.get('walk_away_total'),'z20_fit':fit.get('status'),'raw_routes':raw,'unique_routes':unique,'excluded':sorted(excluded),'retail_selected':a.get('selected_total'),'retail_in_stock':a.get('concrete_in_stock')},ensure_ascii=False))


if __name__=='__main__':main()
