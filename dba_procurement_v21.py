from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

STRATEGY=Path('results/wow_strategy_latest.json')
AVAIL=Path('results/retail_availability_v21.json')
ISSUES=Path('dba_known_listing_issues_v21.json')
OUT=Path('results/procurement_plan_v21.json')
ORDER=('MOTHERBOARD','PSU','CASE','COOLER','RAM','CPU','GPU','STORAGE')
ACTION_RANK={'STRONG_BUY':0,'BUY':1,'FAIR':2,'WAIT':3,'NO_VALUE_MODEL':4,None:9}


def selected(route:dict,kind:str)->dict|None:
    return next((c for c in route.get('components') or [] if c.get('kind')==kind),None)


def listing_id_from_route(route:dict)->str:
    for k in ('listing_id','source_listing_id','complete_listing_id'):
        if route.get(k):return str(route[k])
    for c in route.get('components') or []:
        if c.get('listing_id'):return str(c['listing_id'])
        u=str(c.get('url') or '')
        if '/item/' in u:return u.rstrip('/').split('/item/')[-1].split('?')[0]
    return ''


def component_identity(c:dict|None)->str:
    if not c:return 'NONE'
    return str(c.get('listing_id') or c.get('sku') or c.get('url') or c.get('name') or 'UNKNOWN')


def route_signature(route:dict)->tuple:
    return tuple((k,component_identity(selected(route,k))) for k in ORDER)


def dedupe_routes(routes:list[dict])->list[dict]:
    out=[];seen=set()
    for r in routes:
        sig=route_signature(r)
        if sig in seen:continue
        seen.add(sig);out.append(r)
    return out


def load_json(path:Path)->dict:
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


def hard_exclusions()->dict[str,dict]:
    d=load_json(ISSUES);out={}
    for lid,row in (d.get('listings') or {}).items():
        if row.get('severity')=='HARD_EXCLUDE' and row.get('cleared') is not True:out[str(lid)]=row
    return out


def bid_index(data:dict)->dict[tuple[str,str],dict]:
    out={}
    for kind,rows in (data.get('bid_market_v20') or {}).items():
        for r in rows or []:
            lid=str(r.get('listing_id') or '')
            if lid:out[(kind,lid)]=r
    return out


def availability_index()->dict[str,dict]:
    d=load_json(AVAIL)
    return {str(r.get('url')):r for r in d.get('rows') or [] if r.get('url')}


def price_map(doc:dict)->dict[str,dict]:
    rec=doc.get('recommended_self_build') or {};out={}
    for k in ORDER:
        c=selected(rec,k)
        if c:out[k]={'name':c.get('name'),'price':int(c.get('price') or 0),'id':component_identity(c)}
    return out


def load_compare(path_value:str)->dict:
    if not path_value:return {}
    p=Path(path_value)
    try:return load_json(p)
    except Exception:return {}


def action_for_component(c:dict,bids:dict,avail:dict)->dict:
    kind=str(c.get('kind') or '');price=int(c.get('price') or 0);src=str(c.get('source') or '')
    base={'kind':kind,'name':c.get('name'),'url':c.get('url'),'source':src,'ask':price,'listing_id':c.get('listing_id'),'sku':c.get('sku')}
    if src=='USED ASK':
        lid=str(c.get('listing_id') or '')
        b=bids.get((kind,lid)) or {}
        act=b.get('action') or 'NO_VALUE_MODEL';first=b.get('first_bid');target=b.get('target');walk=b.get('walk_away')
        if act in {'STRONG_BUY','BUY','FAIR'}:
            procurement_action='BUY_NOW' if walk is not None and price<=int(target or walk) else 'BID'
        elif act=='WAIT':procurement_action='WAIT'
        else:procurement_action='VERIFY_VALUE'
        return base|{'procurement_action':procurement_action,'market_action':act,'first_bid':first,'target':target,'walk_away':walk,'actionable_now':procurement_action in {'BUY_NOW','BID'},'reason':('ASK is above the V20 walk-away; do not buy at current ASK.' if act=='WAIT' else 'Use negotiated target/walk-away discipline from the live bid model.')}
    a=avail.get(str(c.get('url') or '')) or {}
    in_stock=a.get('concrete_in_stock') is True
    store=a.get('store_offer')
    return base|{'procurement_action':'BUY_NOW' if in_stock else 'CHECK_STOCK','market_action':'NEW_RETAIL','first_bid':price,'target':price,'walk_away':price,'actionable_now':in_stock,'availability_status':a.get('availability_status','UNVERIFIED'),'store_offer':store,'reason':'Concrete store/stock evidence verified in this run.' if in_stock else 'Same-product price is verified, but a concrete in-stock retailer was not proven; check stock before ordering.'}


def fallback_for(kind:str,current_lid:str,bid_market:dict,route_models:dict[str,str])->dict|None:
    rows=[]
    for r in bid_market.get(kind) or []:
        if str(r.get('listing_id') or '')==current_lid:continue
        if r.get('action') in {'WAIT','NO_VALUE_MODEL'}:continue
        sweet=1
        if kind=='GPU':sweet=0 if str(route_models.get(str(r.get('model') or ''),'')).startswith('SWEET SPOT') else 1
        rows.append((sweet,ACTION_RANK.get(r.get('action'),9),int(r.get('ask') or 10**9),r))
    if not rows:return None
    rows.sort(key=lambda x:x[:3]);return rows[0][3]


def gpu_comparison(routes:list[dict],rec_gpu:str)->list[dict]:
    preferred=[rec_gpu,'RTX 2080 Super','RX 6700 XT','RTX 3070','RX 6800','RX 6800 XT']
    best={}
    for r in routes:
        model=str(r.get('gpu') or '')
        if model not in preferred:continue
        gi=r.get('gpu_intelligence_v20') or {};u=gi.get('utility') or {};fit=gi.get('z20_fit_v20') or {};bid=gi.get('bid') or {}
        row={'gpu':model,'tcwp':int(r.get('tcwp') or 0),'decision_cost':int(r.get('v20_decision_cost') or 10**9),'ask':int(gi.get('ask') or (selected(r,'GPU') or {}).get('price') or 0),'perf':u.get('perf_proxy_2080s_1_00'),'vram_gb':u.get('vram_gb'),'power_w':u.get('power_w'),'z20_fit':fit.get('status','UNKNOWN'),'action':bid.get('action'),'target':bid.get('target'),'walk_away':bid.get('walk_away'),'url':(selected(r,'GPU') or {}).get('url'),'name':(selected(r,'GPU') or {}).get('name')}
        cur=best.get(model)
        if cur is None or (row['decision_cost'],row['tcwp'])<(cur['decision_cost'],cur['tcwp']):best[model]=row
    rec=best.get(rec_gpu) or {};rec_ask=int(rec.get('ask') or 0)
    out=[]
    for m in preferred:
        if m not in best:continue
        x=dict(best[m]);x['ask_delta_vs_recommended']=int(x.get('ask') or 0)-rec_ask;out.append(x)
    return out


def main()->None:
    data=load_json(STRATEGY)
    assert data.get('model_version')=='DBA-WOW-SELF-BUILD-FIRST-V20'
    assert (data.get('component_market_coverage_v20') or {}).get('passed') is True
    rec=data.get('recommended_self_build') or {};assert rec
    routes=list(data.get('self_build_ranked') or []);assert routes
    unique=dedupe_routes(routes)
    exclusions=hard_exclusions()

    original_complete=list(data.get('complete_pc_reference') or [])
    excluded_complete=[];clean_complete=[]
    for r in original_complete:
        lid=listing_id_from_route(r)
        if lid in exclusions:
            excluded_complete.append({'listing_id':lid,'route':r,'issue':exclusions[lid]})
        else:clean_complete.append(r)
    data['complete_pc_reference']=clean_complete
    # Also remove excluded complete-PC routes from mixed ranked output while preserving self-builds.
    data['ranked']=[r for r in (data.get('ranked') or []) if listing_id_from_route(r) not in exclusions]

    bids=bid_index(data);avail=availability_index()
    actions=[]
    for kind in ORDER:
        c=selected(rec,kind)
        if c:actions.append(action_for_component(c,bids,avail))

    route_models={}
    for r in unique:
        m=str(r.get('gpu') or '')
        if m and m not in route_models:route_models[m]=str(r.get('performance_class_v20') or r.get('performance_class') or '')
    bid_market=data.get('bid_market_v20') or {}
    for a in actions:
        if a['source']=='USED ASK':
            fb=fallback_for(a['kind'],str(a.get('listing_id') or ''),bid_market,route_models)
            if fb:a['fallback']=fb

    # One authoritative fit status: exact NO > unknown > verified. V21 intentionally does not use LIKELY.
    gpu_action=next((a for a in actions if a['kind']=='GPU'),{})
    rgi=rec.get('gpu_intelligence_v20') or {};fit=rgi.get('z20_fit_v20') or {}
    gpu_fit=str(fit.get('status') or rec.get('z20_fit_v20') or 'UNKNOWN')
    if gpu_fit=='NO':global_fit='NO'
    elif gpu_fit=='VERIFIED':global_fit='VERIFIED'
    else:global_fit='UNKNOWN'
    fit_doc={'status':global_fit,'gpu_status':gpu_fit,'gpu_reason':fit.get('reason'),'gpu_model_evidence':fit.get('gpu_model_evidence'),'rule':'V21 exposes exactly one authoritative build fit: VERIFIED only when exact GPU model/dimensions are proven and all permanent Z20 hard gates already pass; unknown GPU model => UNKNOWN; known incompatibility => NO.'}

    ask_total=sum(int(a.get('ask') or 0) for a in actions)
    first_total=sum(int(a.get('first_bid') if a.get('source')=='USED ASK' and a.get('first_bid') is not None else a.get('ask') or 0) for a in actions)
    target_total=sum(int(a.get('target') if a.get('source')=='USED ASK' and a.get('target') is not None else a.get('ask') or 0) for a in actions)
    walk_total=sum(int(a.get('walk_away') if a.get('source')=='USED ASK' and a.get('walk_away') is not None else a.get('ask') or 0) for a in actions)
    blockers=[a for a in actions if a.get('procurement_action') in {'WAIT','CHECK_STOCK','VERIFY_VALUE'}]

    previous=load_compare(os.environ.get('V21_PREVIOUS_STRATEGY',''))
    baseline=load_compare(os.environ.get('V21_BASELINE_STRATEGY',''))
    now_map=price_map(data);prev_map=price_map(previous);base_map=price_map(baseline)
    deltas=[]
    for k in ORDER:
        cur=now_map.get(k) or {};prev=prev_map.get(k) or {};base=base_map.get(k) or {}
        deltas.append({'kind':k,'current_name':cur.get('name'),'current':cur.get('price'),'previous':prev.get('price'),'previous_delta':(cur.get('price')-prev.get('price')) if cur.get('price') is not None and prev.get('price') is not None else None,'baseline':base.get('price'),'baseline_delta':(cur.get('price')-base.get('price')) if cur.get('price') is not None and base.get('price') is not None else None})

    gpu_compare=gpu_comparison(unique,str(rec.get('gpu') or ''))
    plan={'generated_at':datetime.now(timezone.utc).isoformat(),'version':'V21','core_model':'DBA-WOW-SELF-BUILD-FIRST-V20','headline':{'cpu':rec.get('cpu'),'gpu':rec.get('gpu'),'ask_total':ask_total,'first_bid_total':first_total,'target_total':target_total,'walk_away_total':walk_total,'ready_to_buy_complete_build_today':not blockers and global_fit!='NO','z20_fit':global_fit},'actions':actions,'blockers':blockers,'z20_fit_authoritative':fit_doc,'unique_self_builds':unique,'unique_count':len(unique),'raw_count':len(routes),'gpu_comparison':gpu_compare,'historical_exclusions':excluded_complete,'complete_pc_reference_clean_count':len(clean_complete),'price_deltas':deltas}
    OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
    data['procurement_v21']=plan
    data['self_build_unique_v21']=unique
    data['z20_fit_authoritative_v21']=fit_doc
    data['known_issue_exclusions_v21']=[{'listing_id':x['listing_id'],'issue':x['issue']} for x in excluded_complete]
    data['procurement_version']='V21'
    STRATEGY.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'V21_PROCUREMENT':True,'ask_total':ask_total,'target_total':target_total,'walk_away_total':walk_total,'blockers':[x['kind']+':'+x['procurement_action'] for x in blockers],'z20_fit':global_fit,'raw_routes':len(routes),'unique_routes':len(unique),'excluded_complete':[x['listing_id'] for x in excluded_complete]},ensure_ascii=False))


if __name__=='__main__':main()
