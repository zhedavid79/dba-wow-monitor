from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

STRATEGY=Path('results/wow_strategy_latest.json')
COMPLETE=Path('results/wow_a3_latest.json')
PARTS=Path('results/z20_parts_latest.json')
DONORS=Path('results/z20_donors_latest.json')
RETAIL=Path('results/retail_prices_latest.json')
CACHE=Path('results/t1_cache_v20.json')
REPORTS=(
    Path('results/wow_self_build_report.md'),
    Path('results/wow_self_build_report_v20.md'),
    Path('results/wow_platform_first_report.md'),
    Path('results/wow_a3_report.md'),
)

DEFECT=re.compile(r'\b(?:delvist\s+defekt|defekt|virker\s+ikke|fungerer\s+ikke|ustabil|artefakt(?:er)?|artifact(?:s)?|til\s+dele|reservedele|fryser|crash(?:er)?|genstarter|slukker|overopheder)\b|\bfejl(?:er)?\s+(?:under|ved|på)\b',re.I)
BAD_RAM=re.compile(r'\b(?:so[- ]?dimm|sodimm|rdimm|lrdimm|registered|server\s*ram|kingston\s+fury\s+impact|kf548s38ibk2(?:-\d+)?)\b',re.I)
SELF_BUILD_ROUTES={'PLATFORM_FIRST_AM5','HYBRID_USED_NEW','USED_BUILD'}
MAX_RETAIL_AGE=20*60
MAX_CACHE_AGE=35*60


def iso(v: str) -> datetime:
    d=datetime.fromisoformat(str(v).replace('Z','+00:00'))
    if d.tzinfo is None: d=d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def age_seconds(v: str) -> float:
    return (datetime.now(timezone.utc)-iso(v)).total_seconds()


def used_component_ok(x: dict) -> None:
    assert x.get('listing_id'), 'USED component missing listing_id'
    assert x.get('url') and str(x.get('listing_id')) in str(x.get('url')), 'USED component URL/identity mismatch'
    assert x.get('functional_defect') is False, 'USED component function not explicitly verified'
    assert str(x.get('listing_id'))!='11596289', 'known accessory false-positive leaked'
    assert not DEFECT.search(str(x.get('name') or '')), 'functional defect language leaked into buyable USED component'


def main() -> None:
    for p in (STRATEGY,COMPLETE,PARTS,DONORS,RETAIL,CACHE,*REPORTS):
        assert p.exists(),f'Missing V20 publication input: {p}'

    s=json.loads(STRATEGY.read_text(encoding='utf-8'))
    c=json.loads(COMPLETE.read_text(encoding='utf-8'))
    p=json.loads(PARTS.read_text(encoding='utf-8'))
    q=json.loads(DONORS.read_text(encoding='utf-8'))
    retail=json.loads(RETAIL.read_text(encoding='utf-8'))
    cache=json.loads(CACHE.read_text(encoding='utf-8'))

    # Primary DBA evidence gates.
    assert s.get('gate_passed') is True
    assert s.get('model_version')=='DBA-WOW-SELF-BUILD-FIRST-V20'
    assert s.get('strategy_mode')=='V20_GPU_FIT_RAM_RETAIL_CACHE_BID'
    assert s.get('functional_defect_policy')=='HARD_EXCLUDE'
    assert s.get('primary_decision')=='BUILD_AN_UPGRADEABLE_PC; COMPLETE_PCS_ARE_SECONDARY_MARKET_REFERENCES'
    assert c.get('gate_passed') is True and c.get('price_binding_regression',{}).get('ok') is True
    assert (c.get('coverage',{}).get('discovery') or {}).get('complete') is True
    assert (c.get('coverage',{}).get('t1') or {}).get('complete') is True
    assert p.get('gate_passed') is True and q.get('gate_passed') is True

    # Same-run T1 cache is an optimization only. It must account exactly for the
    # component T1 work and may never be used stale to bypass network verification.
    assert cache.get('model')=='V20_SAME_RUN_T1_CACHE'
    ca=age_seconds(cache['generated_at']); assert 0<=ca<=MAX_CACHE_AGE,f'T1 cache stale: {ca:.0f}s'
    t1=(p.get('coverage') or {}).get('t1') or {}
    assert t1.get('complete') is True
    assert t1.get('same_run_cache_model')=='V20_SAME_RUN_T1_CACHE'
    hits=int(t1.get('same_run_cache_hits') or 0); network=int(t1.get('network_fetches') or 0); completed=int(t1.get('candidate_completed') or 0)
    assert hits+network==completed, f'cache/network accounting mismatch: {hits}+{network}!={completed}'
    assert int(t1.get('candidate_fetch_errors') or 0)==0

    # Retail must be fresh, same-product verified for the stable catalog and must
    # have completed the broader discovery pass. Unproven dynamic leads cannot win.
    assert retail.get('model')=='V20_DYNAMIC_RETAIL_SAME_PRODUCT_GATE'
    assert retail.get('all_catalog_products_verified') is True
    assert retail.get('required_motherboard_gate_passed') is True
    assert retail.get('dynamic_discovery_gate_passed') is True
    rc=retail.get('counts') or {}
    assert int(rc.get('static_total') or 0)>=25
    assert int(rc.get('static_verified') or 0)==int(rc.get('static_total') or 0)
    assert int(rc.get('seed_total') or 0)>=5 and int(rc.get('seed_ok') or 0)==int(rc.get('seed_total') or 0)
    ra=age_seconds(retail['generated_at']); assert 0<=ra<=MAX_RETAIL_AGE,f'V20 retail snapshot stale: {ra:.0f}s'
    for x in retail.get('products') or []:
        assert x.get('verified') is True and int(x.get('price') or 0)>0 and x.get('url')

    cov=s.get('component_market_coverage_v20') or {}
    assert cov.get('passed') is True
    v19cov=cov.get('v19_coverage') or {}
    assert v19cov.get('passed') is True
    cats=v19cov.get('categories') or {}
    assert cats.get('MOTHERBOARD',{}).get('eligible',0)>=6
    assert cats.get('PSU',{}).get('eligible',0)>=4
    assert cats.get('COOLER',{}).get('eligible',0)>=3
    assert cats.get('RAM',{}).get('eligible',0)>=3
    assert cats.get('STORAGE',{}).get('eligible',0)>=3

    pool=s.get('gpu_pool_v20') or {}
    assert pool.get('method')=='STRATIFIED_CHEAPEST_PLUS_PERFORMANCE_PLUS_TARGET_FAMILIES'
    assert int(pool.get('pool_size') or 0)>0
    assert pool.get('integration')
    targets=set(pool.get('target_families') or [])
    assert {'RX 6800 XT','RX 6800','RX 6700 XT','RTX 3060 Ti','RTX 3070'} <= targets

    rec=s.get('recommended_self_build') or {}
    value=s.get('value_foundation_build') or {}
    assert rec and rec.get('route') in SELF_BUILD_ROUTES
    assert rec.get('foundation')=='AM5_B650_B850_MATX_WIFI_4DIMM'
    assert rec.get('upgradeability')=='A'
    assert str(rec.get('performance_class_v20') or '').startswith('SWEET SPOT')
    assert rec.get('z20_fit_v20') in {'VERIFIED','LIKELY','UNKNOWN'}
    assert rec.get('z20_fit_v20')!='NO'
    assert sum(int(x.get('price') or 0) for x in rec.get('components') or [])==int(rec.get('tcwp') or 0)
    assert value and int(value.get('tcwp') or 10**9)<=int(rec.get('tcwp') or 0)

    gi=rec.get('gpu_intelligence_v20') or {}
    assert (gi.get('utility') or {}).get('known') is True
    assert (gi.get('z20_fit_v20') or {}).get('status')==rec.get('z20_fit_v20')
    assert (gi.get('bid') or {}).get('walk_away') is not None
    assert (gi.get('bid') or {}).get('target') is not None

    bids=s.get('bid_market_v20') or {}
    assert bids.get('GPU') and bids.get('CPU') and bids.get('RAM')
    for kind in ('GPU','CPU','RAM'):
        for x in bids[kind]:
            assert x.get('url') and int(x.get('ask') or 0)>0
            assert x.get('action') in {'STRONG_BUY','BUY','FAIR','WAIT','NO_VALUE_MODEL'}
            if x.get('action')!='NO_VALUE_MODEL':
                assert x.get('first_bid') is not None and x.get('target') is not None and x.get('walk_away') is not None

    decisions=rec.get('component_choice_v19') or {}
    assert set(decisions)=={'MOTHERBOARD','PSU','CASE','COOLER','RAM','CPU','GPU','STORAGE'}
    for kind in ('MOTHERBOARD','PSU','CASE','COOLER','RAM','STORAGE'):
        w=(decisions[kind] or {}).get('winner') or {}
        assert w.get('eligible') is True and int(w.get('price') or 0)>0 and w.get('url')
    mb=(decisions['MOTHERBOARD'] or {}).get('winner') or {}
    assert mb.get('socket')=='AM5' and str(mb.get('form_factor')).lower()=='matx'
    assert int(mb.get('dimm_slots') or 0)>=4 and int(mb.get('m2_count') or 0)>=2 and mb.get('wifi')

    # Every published route remains grounded. Dynamic retail candidates are normalized
    # by the V19 snapshot reader to LIVE_RETAIL_SNAPSHOT after same-product verification.
    for r in s.get('ranked') or []:
        comps=r.get('components') or []; assert comps
        assert sum(int(x.get('price') or 0) for x in comps)==int(r.get('tcwp') or 0)
        for x in comps:
            assert x.get('source') in {'USED ASK','NEW RETAIL'} and x.get('url') and int(x.get('price') or 0)>0
            if x.get('source')=='USED ASK': used_component_ok(x)
            else: assert x.get('price_evidence')=='LIVE_RETAIL_SNAPSHOT'
            if x.get('kind')=='RAM' and r.get('route') in SELF_BUILD_ROUTES:
                assert not BAD_RAM.search(str(x.get('name') or ''))

    for r in s.get('complete_pc_reference') or []:
        used=next((x for x in r.get('components') or [] if x.get('source')=='USED ASK'),None)
        assert used; used_component_ok(used)

    ram=[x for x in rec.get('components') or [] if x.get('kind')=='RAM']
    psu=[x for x in rec.get('components') or [] if x.get('kind')=='PSU']
    storage=[x for x in rec.get('components') or [] if x.get('kind')=='STORAGE']
    assert len(ram)==1 and not BAD_RAM.search(str(ram[0].get('name') or ''))
    assert len(psu)==1 and int(psu[0].get('watt') or 0)>=750
    assert len(storage)==1 and int(storage[0].get('capacity_gb') or 0)>=500

    texts=[x.read_text(encoding='utf-8') for x in REPORTS]
    assert len(set(texts))==1,'V20 canonical/legacy/alias reports differ'
    report=texts[0]
    assert report.startswith('# FULDT PÅLIDELIG DBA-PRISRAPPORT — WoW SELF-BUILD FIRST V20')
    assert 'KF548S38IBK2' not in report
    for marker in ('ANBEFALET SELVBYG','Hvorfor hver permanent del vandt','GPU-marked','CPU-marked','V20 — GPU value, Z20-fit og budmodel','V20 — RAM-bud og bridge-kontrol','V20 — dynamisk retail discovery','V20 — shared same-run T1-cache','V20 — GPU discovery-pool','Pris- og evidensregel'):
        assert marker in report,marker
    for x in rec.get('components') or []: assert x['url'] in report

    print(json.dumps({
        'PASS':True,'model':s.get('model_version'),'self_builds':len(s.get('self_build_ranked') or []),'complete_pc_reference':len(s.get('complete_pc_reference') or []),
        'recommended_tcwp':rec.get('tcwp'),'recommended_cpu':rec.get('cpu'),'recommended_gpu':rec.get('gpu'),'recommended_fit':rec.get('z20_fit_v20'),
        'value_tcwp':value.get('tcwp'),'cache_hits':hits,'component_network_fetches':network,'retail_static':f"{rc.get('static_verified')}/{rc.get('static_total')}",'dynamic_admitted':rc.get('dynamic_admitted'),'gpu_pool_size':pool.get('pool_size')
    },ensure_ascii=False))


if __name__=='__main__': main()
