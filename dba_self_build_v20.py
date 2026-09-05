from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import dba_component_market_v19 as v19
import dba_gpu_model_v20 as gpu20

OUT = Path('results/wow_strategy_latest.json')
RETAIL = Path('results/retail_prices_latest.json')
MAX_RETAIL_AGE_SECONDS = 20 * 60


def parse_iso(value: str) -> datetime:
    dt=datetime.fromisoformat(str(value).replace('Z','+00:00'))
    if dt.tzinfo is None: dt=dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def inject_dynamic_candidates(retail: dict) -> dict[str,int]:
    counts={}
    for row in retail.get('dynamic_admitted_products') or []:
        kind=str(row.get('kind') or '')
        if kind not in v19.RETAIL_CANDIDATES: continue
        sku=str(row.get('sku') or '')
        if not sku: continue
        if any(str(x.get('sku'))==sku for x in v19.RETAIL_CANDIDATES[kind]): continue
        x=deepcopy(row); x.pop('kind',None)
        v19.RETAIL_CANDIDATES[kind].append(x)
        counts[kind]=counts.get(kind,0)+1
    return counts


def cheapest_anchor_ask(routes: list[dict], model: str, fallback: int) -> int:
    asks=[]
    for r in routes:
        if str(r.get('gpu') or '') != model: continue
        c=next((x for x in r.get('components') or [] if x.get('kind')=='GPU' and x.get('source')=='USED ASK'),None)
        if c and int(c.get('price') or 0)>0: asks.append(int(c['price']))
    return min(asks) if asks else fallback


def durable_feature_value(route: dict) -> int:
    dec=route.get('component_choice_v19') or {}
    total=0
    for kind in ('MOTHERBOARD','PSU','CASE','COOLER','RAM','STORAGE'):
        w=(dec.get(kind) or {}).get('winner') or {}
        total += int(w.get('feature_value_dkk') or 0)
    return total


def performance_class_v20(route: dict) -> str:
    spec=gpu20.gpu_spec(str(route.get('gpu') or ''))
    cpu=int(route.get('cpu_score') or 0)
    if cpu < 60 or not spec: return 'UNRESOLVED'
    p=float(spec['perf'])
    if p < 0.75: return 'UNDER MINIMUM'
    if p < 1.00: return 'ACCEPTABLE'
    if p < 1.30: return 'SWEET SPOT'
    if p <= 1.55: return 'SWEET SPOT — HIGH HEADROOM'
    return 'OVERKILL'


def apply_gpu_model(route: dict, anchor_ask: int) -> dict:
    r=deepcopy(route)
    intel=gpu20.route_gpu_intelligence(r,anchor_ask=anchor_ask)
    r['gpu_intelligence_v20']=intel
    fit=(intel.get('z20_fit_v20') or {}).get('status') or 'UNKNOWN'
    r['z20_fit_v20']=fit
    r['performance_class_v20']=performance_class_v20(r)
    feature=durable_feature_value(r)
    utility=int((intel.get('utility') or {}).get('utility_dkk') or 0)
    cpu_value=int(r.get('cpu_score') or 0)*6
    fit_penalty={'VERIFIED':0,'LIKELY':40,'UNKNOWN':75,'NO':100000}.get(fit,100)
    r['v20_durable_feature_value_dkk']=feature
    r['v20_gpu_utility_dkk']=utility
    r['v20_cpu_value_dkk']=cpu_value
    r['v20_fit_uncertainty_penalty_dkk']=fit_penalty
    r['v20_decision_cost']=int(r.get('tcwp') or 10**9)-feature-utility-cpu_value+fit_penalty
    return r


def round50(v: float) -> int:
    return gpu20.round50(v)


def cpu_bid(model: str, score: int, ask: int, anchor_score: int=94, anchor_ask: int=800) -> dict:
    walk=round50(anchor_ask + (int(score)-anchor_score)*35)
    walk=max(500,walk)
    first=min(int(ask),round50(min(int(ask)*0.85,walk*0.82)))
    target=min(int(ask),round50(min(int(ask)*0.93,walk*0.92)))
    action='STRONG_BUY' if ask<=walk*0.90 else 'BUY' if ask<=walk*0.98 else 'FAIR' if ask<=walk*1.05 else 'WAIT'
    return {'first_bid':first,'target':target,'walk_away':walk,'action':action,'rule':'CPU walk-away is anchored to the current 7500F price and WoW CPU-score delta; socket future-proofing is valued separately through AM5.'}


def best_new_32gb_price(retail: dict) -> int | None:
    vals=[]
    for r in retail.get('products') or []:
        name=str(r.get('name') or '')
        cap=int(r.get('capacity_gb') or 0)
        if cap>=32 or ('32gb' in name.lower() and 'ddr5' in name.lower()):
            p=int(r.get('price') or 0)
            if p>0: vals.append(p)
    return min(vals) if vals else None


def ram_bid(component: dict, retail: dict) -> dict:
    ask=int(component.get('price') or 0); name=str(component.get('name') or '')
    cap=int(component.get('capacity_gb') or 0)
    if not cap:
        cap=32 if '32gb' in name.lower() else 16 if '16gb' in name.lower() else 0
    new32=best_new_32gb_price(retail)
    if not new32 or not ask:
        return {'first_bid':None,'target':None,'walk_away':None,'action':'NO_VALUE_MODEL'}
    factor=0.72 if cap>=32 else 0.32
    walk=round50(new32*factor)
    if cap>=32 and ('6000' in name and ('cl30' in name.lower() or 'cl32' in name.lower())): walk=round50(walk*1.08)
    first=min(ask,round50(min(ask*0.85,walk*0.82))); target=min(ask,round50(min(ask*0.93,walk*0.92)))
    action='STRONG_BUY' if ask<=walk*0.90 else 'BUY' if ask<=walk*0.98 else 'FAIR' if ask<=walk*1.05 else 'WAIT'
    return {'first_bid':first,'target':target,'walk_away':walk,'action':action,'new_32gb_anchor':new32,'rule':'Used RAM is capped against the cheapest live 32GB DDR5 anchor: 16GB bridge <=32% and 32GB used <=72%, with a small 6000 CL30/32 allowance.'}


def add_bid_market(data: dict, retail: dict, anchor_ask: int) -> None:
    rows=data.get('self_build_ranked') or []
    gpu_rows=[]; cpu_rows=[]; ram_rows=[]; seen=set()
    for r in rows:
        for kind,target in (('GPU',gpu_rows),('CPU',cpu_rows),('RAM',ram_rows)):
            c=next((x for x in r.get('components') or [] if x.get('kind')==kind and x.get('source')=='USED ASK'),None)
            if not c: continue
            key=(kind,str(c.get('listing_id') or c.get('url')))
            if key in seen: continue
            seen.add(key)
            ask=int(c.get('price') or 0)
            if kind=='GPU': guidance=gpu20.bid_guidance(str(r.get('gpu') or ''),ask,anchor_ask=anchor_ask)
            elif kind=='CPU': guidance=cpu_bid(str(r.get('cpu') or ''),int(r.get('cpu_score') or 0),ask)
            else: guidance=ram_bid(c,retail)
            target.append({'kind':kind,'model':r.get('gpu' if kind=='GPU' else 'cpu') if kind!='RAM' else c.get('name'),'listing_id':c.get('listing_id'),'name':c.get('name'),'url':c.get('url'),'ask':ask,**guidance})
    for xs in (gpu_rows,cpu_rows,ram_rows):
        xs.sort(key=lambda x:(0 if x.get('action')=='STRONG_BUY' else 1 if x.get('action')=='BUY' else 2 if x.get('action')=='FAIR' else 3,int(x.get('ask') or 10**9)))
    data['bid_market_v20']={'GPU':gpu_rows,'CPU':cpu_rows,'RAM':ram_rows}


def main() -> None:
    gpu20.regression()
    assert OUT.exists() and RETAIL.exists()
    retail=json.loads(RETAIL.read_text(encoding='utf-8'))
    assert retail.get('model')=='V20_DYNAMIC_RETAIL_SAME_PRODUCT_GATE'
    assert retail.get('all_catalog_products_verified') is True
    assert retail.get('dynamic_discovery_gate_passed') is True
    age=(datetime.now(timezone.utc)-parse_iso(retail['generated_at'])).total_seconds()
    assert 0<=age<=MAX_RETAIL_AGE_SECONDS,f'V20 retail snapshot stale: {age:.0f}s'
    injected=inject_dynamic_candidates(retail)

    data=json.loads(OUT.read_text(encoding='utf-8'))
    assert data.get('gate_passed') is True
    data=v19.finalize(data)
    routes=data.get('self_build_ranked') or []
    anchor_ask=cheapest_anchor_ask(routes,'RTX 2080 Super',1600)
    v20_routes=[apply_gpu_model(r,anchor_ask) for r in routes]
    v20_routes=[r for r in v20_routes if r.get('z20_fit_v20')!='NO']
    v20_routes.sort(key=lambda r:(int(r.get('v20_decision_cost') or 10**9),int(r.get('tcwp') or 10**9)))
    assert v20_routes

    # The headline recommendation is the best route that actually reaches our target
    # performance class. ACCEPTABLE remains valuable, but belongs in the explicit
    # cheapest-foundation/bridge track rather than silently replacing the SWEET SPOT.
    sweet=[r for r in v20_routes if str(r.get('performance_class_v20') or '').startswith('SWEET SPOT')]
    rec=sweet[0] if sweet else v20_routes[0]
    value=min(v20_routes,key=lambda r:int(r.get('tcwp') or 10**9))
    step=min(sweet,key=lambda r:int(r.get('tcwp') or 10**9)) if sweet else rec

    data.update({'self_build_ranked':v20_routes,'recommended_self_build':rec,'value_foundation_build':value,'performance_step_up_build':step,'buy_now':rec,'ranked':v20_routes+list(data.get('complete_pc_reference') or [])})
    data['component_market_coverage_v20']={'passed':True,'v19_coverage':data.get('component_market_coverage_v19'),'dynamic_retail_injected':injected,'dynamic_retail_counts':retail.get('counts'),'rule':'V20 requires green V19 category coverage plus a completed dynamic retail discovery pass.'}
    data['gpu_optimizer_policy_v20']={'method':'TARGET_3840X1600_PERFORMANCE_PLUS_VRAM_PLUS_POWER_PLUS_EXACT_Z20_FIT','anchor_model':'RTX 2080 Super','anchor_ask':anchor_ask,'target_families':(data.get('gpu_pool_v20') or {}).get('target_families'),'headline_minimum':'SWEET SPOT; ACCEPTABLE routes remain eligible only for the cheapest-foundation/bridge track','unknown_fit_policy':'Do not hard-exclude unknown exact GPU dimensions; retain candidate with explicit uncertainty penalty. Exact known-NO is excluded.'}
    add_bid_market(data,retail,anchor_ask)
    data['retail_discovery_v20']={'model':retail.get('model'),'counts':retail.get('counts'),'dynamic_admitted_products':retail.get('dynamic_admitted_products') or []}
    data['model_version']='DBA-WOW-SELF-BUILD-FIRST-V20'
    data['strategy_mode']='V20_GPU_FIT_RAM_RETAIL_CACHE_BID'
    OUT.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    gi=rec.get('gpu_intelligence_v20') or {}
    print(json.dumps({'model':data['model_version'],'recommended_tcwp':rec.get('tcwp'),'cpu':rec.get('cpu'),'gpu':rec.get('gpu'),'performance_class_v20':rec.get('performance_class_v20'),'v20_decision_cost':rec.get('v20_decision_cost'),'value_foundation_tcwp':value.get('tcwp'),'value_foundation_gpu':value.get('gpu'),'gpu_action':(gi.get('bid') or {}).get('action'),'z20_fit_v20':rec.get('z20_fit_v20'),'dynamic_injected':injected,'retail_age_seconds':round(age,1)},ensure_ascii=False))


if __name__=='__main__':
    main()
