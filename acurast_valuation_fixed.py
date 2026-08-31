from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

import acurast_valuation as v

PULSE_BASE='https://www.acurastpulse.com'
PULSE_PAGES=('/phones','/phones/deployed')
HEADERS={'User-Agent':'Mozilla/5.0','Accept-Language':'en-US,en;q=0.9'}
DAYS_YEAR=365.0
POWER_W_WALL=4.0
DKK_PER_KWH=2.50
ANNUAL_LOW_REWARD_DECAY=0.20
PRICE_SCENARIOS=(0.5,1.0,2.0,5.0,10.0,20.0)
MATCH_NOISE={'galaxy','phone','smartphone','mobile','mobil','lte','nr'}


def safe_div(a,b): return a/b if b else None

def round25(x:float)->int: return max(25,int(round(x/25.0)*25))

def pnorm(s:str)->str:
    s=(s or '').lower().replace('+',' plus ')
    s=re.sub(r'\bone\s+plus\b','oneplus',s)
    s=re.sub(r'\bmoto\b','motorola',s)
    s=re.sub(r'([a-z])([0-9])',r'\1 \2',s)
    s=re.sub(r'([0-9])([a-z])',r'\1 \2',s)
    s=re.sub(r'[^a-z0-9]+',' ',s).strip()
    return re.sub(r'\s+',' ',s)

def model_key(s:str,drop_connectivity:bool=True)->tuple[str,...]:
    out=[]
    for t in pnorm(s).split():
        if t in MATCH_NOISE: continue
        if drop_connectivity and t in {'5g','4g'}: continue
        if not out or out[-1]!=t: out.append(t)
    return tuple(out)

def parse_pulse_model(text:str)->tuple[str|None,str|None]:
    m=re.match(r'^(.*?)\s+([A-Za-z0-9][A-Za-z0-9._-]*)\s+·\s+',text)
    return (m.group(1).strip(),m.group(2).strip()) if m else (None,None)

def parse_pulse_row(href:str,text:str)->dict|None:
    if 'ACU/epoch' not in text:return None
    model,brand=parse_pulse_model(text)
    if not model:return None
    em=re.search(r'([0-9]+(?:\.[0-9]+)?)\s+ACU/epoch',text)
    if not em:return None
    ordinary=[float(x) for x in re.findall(r'([0-9]+(?:\.[0-9]+)?)\s+ACU(?!/epoch)',text)]
    if not ordinary:return None
    um=re.search(r'([0-9]+(?:\.[0-9]+)?)%\s+([0-9,]+)\s+([0-9,]+)\s*/\s*([0-9,]+)',text)
    vm=re.search(r'(\d+)\s+variants?',text,re.I) or re.search(r'(\d+)×\s*configs?',text,re.I)
    return {
        'pulse_model_id':href.rsplit('/',1)[-1],
        'pulse_url':PULSE_BASE+href,
        'pulse_model':model,
        'pulse_brand':brand,
        'observed_acu_epoch':float(em.group(1)),
        'earnings_day':ordinary[0],
        'baseline_day':ordinary[1] if len(ordinary)>=2 else None,
        'processors':int(um.group(2).replace(',','')) if um else None,
        'active':int(um.group(3).replace(',','')) if um else None,
        'uptime_pct':float(um.group(1)) if um else None,
        'variant_count':int(vm.group(1)) if vm else None,
        'raw_text':text,
    }

def fetch_pulse_catalog()->list[dict]:
    rows={}; errors=[]
    for path in PULSE_PAGES:
        try:
            r=requests.get(PULSE_BASE+path,headers=HEADERS,timeout=30); r.raise_for_status()
            soup=BeautifulSoup(r.text,'html.parser')
            for a in soup.find_all('a',href=True):
                href=a.get('href','')
                if not re.fullmatch(r'/phones/\d+',href):continue
                text=' '.join(a.stripped_strings); row=parse_pulse_row(href,text)
                if row:
                    old=rows.get(row['pulse_model_id'])
                    if old is None or len(text)>len(old['raw_text']): rows[row['pulse_model_id']]=row
        except Exception as e:
            errors.append(f'{path}: {e!r}')
    if not rows:
        raise RuntimeError('ACURAST PULSE MAINNET DATA GATE FAILED: '+'; '.join(errors))
    return list(rows.values())

def match_pulse(model:str,catalog:list[dict])->tuple[dict|None,str,float]:
    target=pnorm(model)
    exact=[r for r in catalog if pnorm(r['pulse_model'])==target]
    if len(exact)==1:return exact[0],'EXACT',1.0
    if len(exact)>1:return None,'AMBIGUOUS_EXACT',0.0
    key=model_key(model,True)
    candidates=[r for r in catalog if model_key(r['pulse_model'],True)==key]
    if not candidates:return None,'NO_MATCH',0.0
    target_5g='5g' in pnorm(model).split()
    same=[r for r in candidates if ('5g' in pnorm(r['pulse_model']).split())==target_5g]
    if len(same)==1:return same[0],'NORMALIZED_CONNECTIVITY_EXACT',0.97
    if len(candidates)==1:return candidates[0],'UNIQUE_MARKETING_ALIAS',0.93
    return None,'AMBIGUOUS_VARIANT',0.0

def evidence_factor(processors:int|None,match_conf:float,variant_count:int|None)->float:
    n=processors or 0
    f=1.00 if n>=50 else 0.97 if n>=20 else 0.93 if n>=10 else 0.88 if n>=5 else 0.82 if n>=3 else 0.76 if n==2 else 0.65
    # Model-level Pulse earnings can aggregate several hardware/RAM/storage variants.
    # This must affect bidding confidence, not the physical BASE estimate itself.
    vf=1.00 if not variant_count or variant_count<=1 else 0.95 if variant_count<=2 else 0.90
    return f*match_conf*vf

def evidence_label(processors:int|None,match_conf:float,variant_count:int|None)->str:
    n=processors or 0
    if match_conf>=0.99 and n>=20 and (not variant_count or variant_count<=2): return 'HIGH'
    if match_conf>=0.93 and n>=5: return 'MEDIUM'
    return 'LOW'

def cumulative_from_year1(year1:float,months:int,decay:float=0.0)->float:
    years=months/12.0; whole=int(math.floor(years)); rem=years-whole; total=0.0
    for y in range(whole): total+=year1*((1.0-decay)**y)
    if rem>0: total+=year1*((1.0-decay)**whole)*rem
    return total

def electricity(months:int)->dict:
    kwh=POWER_W_WALL/1000.0*24.0*(DAYS_YEAR/12.0)*months
    return {'kwh':kwh,'dkk':kwh*DKK_PER_KWH}

def main():
    src=json.loads(v.INPUT.read_text(encoding='utf-8'))
    if not src.get('gate_passed') or not src.get('product_identity_gate'):
        raise SystemExit('PRICE DATA GATE FAILED upstream')

    pulse=fetch_pulse_catalog(); valued=[]; unsupported=[]; core_incompatible=[]
    for row in src.get('ranked_by_verified_ask',[]):
        model=row.get('model') or ''
        core_ok,core_reason=v.core_compatibility(model,row.get('title',''),row.get('description',''))
        if not core_ok:
            core_incompatible.append({'listing_id':row.get('listing_id'),'model':model,'url':row.get('url'),'reason':core_reason}); continue
        pr,method,mconf=match_pulse(model,pulse)
        if not pr:
            unsupported.append({'listing_id':row.get('listing_id'),'model':model,'reason':f'no unique Mainnet Pulse reward match: {method}'}); continue

        ask=int(row.get('ask_t2') or row.get('ask_t1'))
        observed_epoch=float(pr['observed_acu_epoch'])
        observed_day=float(pr['earnings_day'])
        raw_baseline_day=float(pr['baseline_day']) if pr.get('baseline_day') is not None else observed_day/1.10

        # Pulse observed earnings can include the protocol's +10% deployment boost.
        # Procurement must rank intrinsic hardware, so BASE strips that boost.
        # Do not allow a noisy baseline aggregate to exceed observed earnings.
        baseline_day=min(observed_day,raw_baseline_day) if observed_day>0 else raw_baseline_day
        baseline_ratio=min(1.0,max(0.0,safe_div(baseline_day,observed_day) or (1/1.10)))
        base_epoch=observed_epoch*baseline_ratio
        low_epoch=base_epoch
        high_epoch=max(observed_epoch,base_epoch*1.10)
        base_year=baseline_day*DAYS_YEAR
        low_year=base_year
        high_day=max(observed_day,baseline_day*1.10)
        high_year=high_day*DAYS_YEAR

        variants=pr.get('variant_count')
        ef=evidence_factor(pr.get('processors'),mconf,variants)
        bid_year=base_year*ef

        valued.append({
            'listing_id':row['listing_id'],'url':row['url'],'title':row['title'],'model':model,'ask':ask,
            'price_source':'DBA same-listing T1/T2 structured verification','verified_timestamp':row.get('final_timestamp') or src.get('generated_at'),
            'core_android_min':v.CORE_MIN_ANDROID,'core_compatibility':True,'core_compatibility_reason':core_reason,
            'reward_source':'ACURAST_PULSE_MAINNET_CHAIN_DERIVED','reward_match_method':method,'reward_match_confidence':mconf,
            'pulse_model_id':pr['pulse_model_id'],'pulse_model':pr['pulse_model'],'pulse_url':pr['pulse_url'],
            'pulse_processors':pr.get('processors'),'pulse_active':pr.get('active'),'pulse_uptime_pct':pr.get('uptime_pct'),
            'pulse_variant_count':variants,'pulse_observed_acu_epoch':observed_epoch,'pulse_observed_earnings_day':observed_day,
            'pulse_raw_baseline_day':raw_baseline_day,'pulse_baseline_day_used':baseline_day,'deployment_baseline_ratio':baseline_ratio,
            'confidence':evidence_label(pr.get('processors'),mconf,variants),'confidence_factor':ef,
            'acu_epoch_low':low_epoch,'acu_epoch_base':base_epoch,'acu_epoch_conservative':low_epoch,
            'acu_epoch_bid_basis':base_epoch*ef,'acu_epoch_high':high_epoch,
            'acu_day_base':baseline_day,'acu_month_base':baseline_day*(DAYS_YEAR/12.0),
            'acu_year_base':base_year,'acu_year_conservative':low_year,'acu_year_bid_basis':bid_year,'acu_year_high':high_year,
            'aae_ask_base':safe_div(base_year,ask),'aae_ask_low':safe_div(low_year,ask),'aae_100_ask_base':safe_div(base_year*100.0,ask),
        })

    if not valued:
        raise SystemExit('ACURAST PULSE MAINNET DATA GATE FAILED — no live DBA phones have unique Pulse rewards')
    coverage=len(valued)/max(1,len(src.get('ranked_by_verified_ask',[])))

    # Hardware-baseline AAE, not deployment-boosted earnings, drives all acquisition thresholds.
    market=[x['aae_ask_base'] for x in valued if x['aae_ask_base'] and x['aae_ask_base']>0]
    target_h=v.percentile(market,0.75); hard_h=v.percentile(market,0.50); start_h=target_h*1.25

    for x in valued:
        by=x['acu_year_bid_basis']
        sb=round25(by/start_h) if start_h>0 else 25
        tb=round25(by/target_h) if target_h>0 else x['ask']
        hb=round25(by/hard_h) if hard_h>0 else tb
        x['start_bid']=min(x['ask'],sb)
        x['target']=min(x['ask'],max(x['start_bid'],tb))
        x['hard_max']=max(x['target'],hb)
        x['aae_target_base']=safe_div(x['acu_year_base'],x['target'])
        x['aae_target_low']=safe_div(x['acu_year_conservative'],x['target'])
        x['aae_hard_max_base']=safe_div(x['acu_year_base'],x['hard_max'])
        x['aae_hard_max_low']=safe_div(x['acu_year_conservative'],x['hard_max'])

        cum={}
        for months in (12,24,36):
            elec=electricity(months)
            lc=cumulative_from_year1(x['acu_year_conservative'],months,ANNUAL_LOW_REWARD_DECAY)
            bc=cumulative_from_year1(x['acu_year_base'],months)
            hc=cumulative_from_year1(x['acu_year_high'],months)
            cum[str(months)]={
                'acu_low_stress':lc,'acu_base':bc,'acu_high':hc,
                'electricity_kwh':elec['kwh'],'electricity_dkk':elec['dkk'],
                'break_even_acu_price_dkk_low_stress_at_target':safe_div(x['target']+elec['dkk'],lc),
                'scenario_value_base_dkk':{str(p):bc*p for p in PRICE_SCENARIOS},
            }
        x['cumulative']=cum
        one=electricity(12)
        x['electricity_kwh_month']=one['kwh']/12
        x['electricity_dkk_month']=one['dkk']/12
        x['energy_dkk_per_acu_base']=safe_div(one['dkk'],x['acu_year_base'])
        x['decision']='STRONG BID' if x['ask']<=x['target'] and x['aae_ask_base']>=target_h else ('BID' if x['ask']<=x['hard_max'] else 'WATCH/NEGOTIATE')
        x['opportunity_score']=100.0*(x['aae_ask_base']/hard_h) if hard_h>0 else 0.0

    valued.sort(key=lambda x:(-x['aae_ask_base'],-x['confidence_factor'],x['ask']))

    out={
        'generated_at':datetime.now(timezone.utc).isoformat(),
        'model_version':'V1.6-MAINNET-PULSE-BASELINE-AAE',
        'valuation_gate':True,'dba_same_listing_gate':True,'reward_data_gate':True,
        'reward_source':{
            'primary':'Acurast Pulse Mainnet chain-derived stake-neutral phone earnings',
            'catalog_rows':len(pulse),'matched_listings':len(valued),'input_listings':len(src.get('ranked_by_verified_ask',[])),'coverage':coverage,
            'canary_acurastbot_used_for_absolute_acu':False,'old_cacu_to_acu_0_01_conversion_retired':True,'old_partial_farm_scale_retired':True,
            'base_definition':'Pulse chain-derived baseline/day and observed ACU/epoch with deployment boost stripped; BASE is intrinsic hardware baseline',
            'low_definition':'same current-epoch hardware baseline; 20% annual network/reward decay is applied only to long-horizon LOW accumulation',
            'high_definition':'observed deployment-boosted ACU/epoch or +10% over hardware baseline, whichever is higher',
            'variant_policy':'model-level Pulse aggregates are allowed; multiple variants lower bid-confidence only and never inflate BASE reward',
        },
        'core_gate':{'minimum_android':v.CORE_MIN_ANDROID,'mode':'hard fail-closed allowlist','excluded_count':len(core_incompatible)},
        'economic_invariant':'Rank and bid on long-term ACU accumulation efficiency; ACU spot price is not a purchase gate.',
        'ranking_metric':'deployment-neutral Mainnet Pulse baseline annual ACU / verified DBA ASK DKK; evidence confidence only reduces bid basis',
        'reward_decay_stress':{'low_path_annual_decay':ANNUAL_LOW_REWARD_DECAY,'base_path_decay':0.0,'high_path_decay':0.0},
        'electricity_assumption':{'wall_power_w':POWER_W_WALL,'dkk_per_kwh':DKK_PER_KWH},
        'price_scenarios_dkk_per_acu':PRICE_SCENARIOS,
        'hurdles':{'start_annual_baseline_aae':start_h,'target_annual_baseline_aae_p75':target_h,'hard_max_annual_baseline_aae_p50':hard_h},
        'dba_counts':src.get('counts'),'ranked':valued,'core_incompatible':core_incompatible,'unsupported':unsupported,
    }
    v.OUTPUT.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')

    lines=[
        '# Acurast DBA Procurement V1.6 — Mainnet baseline ACU Accumulation Efficiency','',
        f"Generated: {out['generated_at']}",'',
        'DBA data gate: **PASS** — live same-listing structured discovery + T1/T2 verification.',
        f"Reward data gate: **PASS** — Acurast Pulse Mainnet chain-derived rewards; {len(valued)}/{len(src.get('ranked_by_verified_ask',[]))} live listings matched.",
        '**Retired permanently:** AcurastBot Canary cACU ×0.01 conversion and ×6.742 partial-farm calibration.',
        'BASE = deployment-neutral Mainnet hardware baseline. HIGH may include the protocol deployment boost. Evidence confidence affects bid basis, not physical BASE ACU/epoch.',
        f"Long-horizon LOW stress: {ANNUAL_LOW_REWARD_DECAY*100:.0f}% annual reward decay. Electricity: {POWER_W_WALL:.1f} W at {DKK_PER_KWH:.2f} DKK/kWh.",'',
        '| # | Model | ASK | ACU/epoch BASE | HIGH | ACU/day BASE | ACU/år BASE | AAE BASE @ASK | Pulse n | Variants | Confidence | Start | Target | Hard max | Klasse | Link |',
        '|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|---|---|',
    ]
    for i,x in enumerate(valued,1):
        lines.append(f"| {i} | {x['model']} | {x['ask']} | {x['acu_epoch_base']:.5f} | {x['acu_epoch_high']:.5f} | {x['acu_day_base']:.4f} | {x['acu_year_base']:.1f} | {x['aae_ask_base']:.4f} | {x.get('pulse_processors') or 0} | {x.get('pulse_variant_count') or 0} | {x['confidence']} | {x['start_bid']} | {x['target']} | {x['hard_max']} | {x['decision']} | [DBA]({x['url']}) |")
    lines += ['', '## Topkandidater', '']
    for x in valued[:12]:
        lines.append(f"- **{x['model']}** — ASK {x['ask']} kr. — BASE {x['acu_epoch_base']:.5f} ACU/epoch; {x['acu_year_base']:.1f} ACU/år; AAE {x['aae_ask_base']:.4f}; Pulse n={x.get('pulse_processors') or 0}, variants={x.get('pulse_variant_count') or 0}, confidence={x['confidence']}; start {x['start_bid']} / target {x['target']} / max {x['hard_max']} — **{x['decision']}** — [DBA]({x['url']})")
    v.REPORT.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({'valuation_gate':True,'model_version':out['model_version'],'ranked':len(valued),'coverage':coverage,'top':[{'listing_id':x['listing_id'],'model':x['model'],'ask':x['ask'],'acu_epoch_base':x['acu_epoch_base'],'acu_year_base':x['acu_year_base'],'aae_ask_base':x['aae_ask_base'],'confidence':x['confidence'],'url':x['url']} for x in valued[:10]]},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
