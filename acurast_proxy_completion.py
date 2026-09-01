from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import acurast_valuation as compat
import acurast_valuation_fixed as f
from acurast_pulse_proxy import build_family_proxy

LATEST=Path('results/acurast_latest.json')
VALUATION=Path('results/acurast_valuation.json')


def valued_from_proxy(row:dict, proxy:dict, hurdles:dict)->dict:
    ask=int(row.get('ask_t2') or row.get('ask_t1'))
    observed_epoch=float(proxy['observed_acu_epoch'])
    observed_day=float(proxy['earnings_day'])
    baseline_day=float(proxy['baseline_day'])
    baseline_ratio=min(1.0,max(0.0,f.safe_div(baseline_day,observed_day) or (1/1.10)))
    base_epoch=observed_epoch*baseline_ratio
    base_year=baseline_day*f.DAYS_YEAR
    high_epoch=max(observed_epoch,base_epoch*1.10)
    high_day=max(observed_day,baseline_day*1.10)
    high_year=high_day*f.DAYS_YEAR

    # Deliberately low bid confidence: the absolute reward remains Mainnet-Pulse
    # derived, but it is a conservative family proxy rather than an exact device row.
    confidence_factor=0.50
    bid_year=base_year*confidence_factor

    x={
        'listing_id':row['listing_id'],'url':row['url'],'title':row['title'],'model':row['model'],'ask':ask,
        'price_source':'DBA same-listing T1/T2 structured verification',
        'verified_timestamp':row.get('final_timestamp') or datetime.now(timezone.utc).isoformat(),
        'core_android_min':compat.CORE_MIN_ANDROID,'core_compatibility':True,
        'core_compatibility_reason':compat.core_compatibility(row['model'],row.get('title',''),row.get('description',''))[1],
        'reward_source':'ACURAST_PULSE_MAINNET_CHAIN_DERIVED',
        'reward_match_method':'FAMILY_CONSERVATIVE_PROXY','reward_match_confidence':proxy.get('proxy_confidence',0.55),
        'pulse_model_id':proxy['pulse_model_id'],'pulse_model':proxy['pulse_model'],'pulse_url':proxy.get('pulse_url'),
        'pulse_processors':proxy.get('processors'),'pulse_active':proxy.get('active'),'pulse_uptime_pct':proxy.get('uptime_pct'),
        'pulse_variant_count':proxy.get('variant_count'),'pulse_observed_acu_epoch':observed_epoch,
        'pulse_observed_earnings_day':observed_day,'pulse_raw_baseline_day':baseline_day,
        'pulse_baseline_day_used':baseline_day,'deployment_baseline_ratio':baseline_ratio,
        'confidence':'LOW','confidence_factor':confidence_factor,
        'proxy_reference_models':proxy.get('proxy_reference_models') or [],
        'proxy_reference_ids':proxy.get('proxy_reference_ids') or [],
        'proxy_policy':proxy.get('proxy_policy'),
        'acu_epoch_low':base_epoch,'acu_epoch_base':base_epoch,'acu_epoch_conservative':base_epoch,
        'acu_epoch_bid_basis':base_epoch*confidence_factor,'acu_epoch_high':high_epoch,
        'acu_day_base':baseline_day,'acu_month_base':baseline_day*(f.DAYS_YEAR/12.0),
        'acu_year_base':base_year,'acu_year_conservative':base_year,'acu_year_bid_basis':bid_year,'acu_year_high':high_year,
        'aae_ask_base':f.safe_div(base_year,ask),'aae_ask_low':f.safe_div(base_year,ask),'aae_100_ask_base':f.safe_div(base_year*100.0,ask),
    }

    start_h=float(hurdles.get('start_annual_baseline_aae') or 0)
    target_h=float(hurdles.get('target_annual_baseline_aae_p75') or 0)
    hard_h=float(hurdles.get('hard_max_annual_baseline_aae_p50') or 0)
    sb=f.round25(bid_year/start_h) if start_h>0 else 25
    tb=f.round25(bid_year/target_h) if target_h>0 else ask
    hb=f.round25(bid_year/hard_h) if hard_h>0 else tb
    x['start_bid']=min(ask,sb)
    x['target']=min(ask,max(x['start_bid'],tb))
    x['hard_max']=max(x['target'],hb)
    x['aae_target_base']=f.safe_div(base_year,x['target']); x['aae_target_low']=x['aae_target_base']
    x['aae_hard_max_base']=f.safe_div(base_year,x['hard_max']); x['aae_hard_max_low']=x['aae_hard_max_base']

    cum={}
    for months in (12,24,36):
        elec=f.electricity(months)
        lc=f.cumulative_from_year1(base_year,months,f.ANNUAL_LOW_REWARD_DECAY)
        bc=f.cumulative_from_year1(base_year,months)
        hc=f.cumulative_from_year1(high_year,months)
        cum[str(months)]={
            'acu_low_stress':lc,'acu_base':bc,'acu_high':hc,
            'electricity_kwh':elec['kwh'],'electricity_dkk':elec['dkk'],
            'break_even_acu_price_dkk_low_stress_at_target':f.safe_div(x['target']+elec['dkk'],lc),
            'scenario_value_base_dkk':{str(p):bc*p for p in f.PRICE_SCENARIOS},
        }
    x['cumulative']=cum
    one=f.electricity(12)
    x['electricity_kwh_month']=one['kwh']/12
    x['electricity_dkk_month']=one['dkk']/12
    x['energy_dkk_per_acu_base']=f.safe_div(one['dkk'],base_year)
    x['decision']='STRONG BID' if ask<=x['target'] and x['aae_ask_base']>=target_h else ('BID' if ask<=x['hard_max'] else 'WATCH/NEGOTIATE')
    x['opportunity_score']=100.0*(x['aae_ask_base']/hard_h) if hard_h>0 else 0.0
    return x


def main()->None:
    latest=json.loads(LATEST.read_text(encoding='utf-8'))
    val=json.loads(VALUATION.read_text(encoding='utf-8'))
    if val.get('model_version')!='V1.6-MAINNET-PULSE-BASELINE-AAE' or not val.get('reward_data_gate'):
        raise SystemExit('Proxy completion requires valid V1.6 Mainnet Pulse valuation')

    pulse=f.fetch_pulse_catalog()
    ranked=val.get('ranked') or []
    ranked_ids={str(x.get('listing_id')) for x in ranked}
    core_bad={str(x.get('listing_id')) for x in (val.get('core_incompatible') or [])}
    added=[]

    for row in latest.get('ranked_by_verified_ask') or []:
        lid=str(row.get('listing_id'))
        if lid in ranked_ids or lid in core_bad:
            continue
        model=str(row.get('model') or '')
        direct,method,_=f.match_pulse(model,pulse)
        if direct is not None and method not in {'NO_MATCH','AMBIGUOUS_EXACT','AMBIGUOUS_VARIANT'}:
            continue
        core_ok,_=compat.core_compatibility(model,row.get('title',''),row.get('description',''))
        if not core_ok:
            continue
        proxy=build_family_proxy(model,pulse)
        if proxy is None:
            continue
        added.append(valued_from_proxy(row,proxy,val.get('hurdles') or {}))

    if not added:
        print(json.dumps({'proxy_added':0},indent=2))
        return

    ranked.extend(added)
    ranked.sort(key=lambda x:(-float(x.get('aae_ask_base') or 0),-float(x.get('confidence_factor') or 0),int(x.get('ask') or 0)))
    val['ranked']=ranked
    added_ids={str(x['listing_id']) for x in added}
    val['unsupported']=[x for x in (val.get('unsupported') or []) if str(x.get('listing_id')) not in added_ids]
    reward=val.setdefault('reward_source',{})
    reward['matched_listings']=len(ranked)
    reward['input_listings']=len(latest.get('ranked_by_verified_ask') or [])
    reward['coverage']=len(ranked)/max(1,reward['input_listings'])
    reward['family_proxy_listings']=len(added)
    reward['family_proxy_policy']='same manufacturer/family + generation ±1; >=2 Mainnet Pulse references; minimum observed/baseline reward; LOW confidence and 0.50 bid factor'
    val['generated_at']=datetime.now(timezone.utc).isoformat()
    VALUATION.write_text(json.dumps(val,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'proxy_added':len(added),'models':[x['model'] for x in added]},ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
