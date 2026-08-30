from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone

import acurast_valuation as v

GENERIC={'galaxy','smartphone','phone','mobile','moto','5g','lte'}
FAMILY_BLOCK={'redmi','note','poco','edge','pixel','realme','oppo','honor'}
BRAND_ALIASES={'one plus':'oneplus','oneplus':'oneplus','samsung':'samsung','xiaomi':'xiaomi'}

# V1.4 long-horizon assumptions. These are deliberately explicit rather than hidden.
EPOCHS_DAY=16.0
DAYS_YEAR=365.0
MONTHS_YEAR=12.0
POWER_W_WALL=4.0
DKK_PER_KWH=2.50
ANNUAL_LOW_REWARD_DECAY=0.20
PRICE_SCENARIOS=(0.5,1.0,2.0,5.0,10.0,20.0)


def split_tokens(s):
    n=v.norm(s)
    n=re.sub(r'([a-z]+)(\d)',r'\1 \2',n)
    n=re.sub(r'(\d)([a-z]+)',r'\1 \2',n)
    return [t for t in n.split() if t not in GENERIC]


def brand_of(label):
    n=v.norm(label)
    if n.startswith('one plus '): return 'oneplus'
    return n.split()[0] if n.split() else ''


def core_tokens(s,brand):
    toks=split_tokens(s)
    out=[]
    for t in toks:
        if t==brand: continue
        if brand=='xiaomi' and t=='mi': continue
        if not out or out[-1]!=t: out.append(t)
    return out


def strict_reference_device(devices,label,stats_by_cfg):
    target_brand=BRAND_ALIASES.get(brand_of(label),brand_of(label))
    target=core_tokens(label,target_brand)
    target_set=set(target)
    target_compact=''.join(target)
    candidates=[]; best=0.0
    for d in devices:
        company_raw=v.norm(d.get('company',''))
        company=BRAND_ALIASES.get(company_raw,company_raw)
        if not (company==target_brand or company.startswith(target_brand+' ')):
            continue
        cand=core_tokens(str(d.get('model') or ''),target_brand)
        cset=set(cand); cand_compact=''.join(cand)
        overlap=len(target_set & cset)/len(target_set) if target_set else 0.0
        best=max(best,overlap)
        token_match=target_set.issubset(cset)
        compact_match=bool(target_compact and target_compact in cand_compact)
        if not (token_match or compact_match): continue
        extra=cset-target_set
        if extra & FAMILY_BLOCK: continue
        observed=sum(int(stats_by_cfg.get(int(c.get('id')),{}).get('processorCount') or 0)
                     for c in (d.get('configurations') or []) if c.get('id') is not None)
        candidates.append((len(extra),-observed,d))
    if not candidates:return None,best
    candidates.sort(key=lambda x:(x[0],x[1]))
    return candidates[0][2],1.0


def safe_partial_calibration(devices,stats_by_cfg):
    samples=[]; missing=[]
    for label,title_hint,weight in v.REFERENCE_FARM:
        d,match_score=strict_reference_device(devices,label,stats_by_cfg)
        if not d:
            missing.append({'model':label,'best_match_score':round(match_score,3),'reason':'exact marketed model absent from current AcurastBot device catalog'})
            continue
        picked=v.choose_config(d,title_hint,stats_by_cfg)
        if not picked:
            missing.append({'model':label,'reason':'matched device has no reward stats'}); continue
        cfg,st=picked; rw=v.rewards(st)
        if not rw:
            missing.append({'model':label,'reason':'matched config has no expectedReward'}); continue
        matched_name=f"{d.get('company','')} {d.get('model','')}".strip()
        for _ in range(weight):
            samples.append({'model':label,'matched_device':matched_name,'match_score':round(match_score,3),'configuration_id':cfg.get('id'),'bot_base_acu_epoch':rw['base']})
    if len(samples)<2:
        return {'status':'INSUFFICIENT_REFERENCE_MATCH','scale':1.0,'matched':len(samples),'missing':missing,'samples':samples,
                'observed_floor':v.OBSERVED_REFERENCE_AVG_ACU_EPOCH_FLOOR,
                'reference_mode':'exact-only; no cross-family substitution'}
    bot_mean=sum(x['bot_base_acu_epoch'] for x in samples)/len(samples)
    scale=max(1.0,v.OBSERVED_REFERENCE_AVG_ACU_EPOCH_FLOOR/bot_mean) if bot_mean>0 else 1.0
    return {'status':'CALIBRATED_PARTIAL_REFERENCE','scale':scale,'matched':len(samples),'missing':missing,'samples':samples,
            'bot_reference_mean':bot_mean,'observed_floor':v.OBSERVED_REFERENCE_AVG_ACU_EPOCH_FLOOR,
            'calibrated_reference_mean':bot_mean*scale,
            'reference_mode':'partial exact-reference production-floor calibration; uniform scale preserves relative AAE ranking and bid ordering',
            'confidence':'LOW_ABSOLUTE_SCALE_HIGH_RELATIVE_RANKING'}


def annual_acu(epoch_reward: float) -> float:
    return epoch_reward * EPOCHS_DAY * DAYS_YEAR


def cumulative_base(epoch_reward: float, months: int) -> float:
    return epoch_reward * EPOCHS_DAY * (DAYS_YEAR/12.0) * months


def cumulative_low(epoch_reward: float, months: int) -> float:
    # Apply a 20% annual network/reward-dilution stress to the conservative reward path.
    years=months/12.0
    total=0.0
    whole=int(math.floor(years))
    for y in range(whole):
        total += annual_acu(epoch_reward) * ((1.0-ANNUAL_LOW_REWARD_DECAY)**y)
    remainder=years-whole
    if remainder>0:
        total += annual_acu(epoch_reward) * ((1.0-ANNUAL_LOW_REWARD_DECAY)**whole) * remainder
    return total


def electricity(months:int)->dict:
    kwh=POWER_W_WALL/1000.0*24.0*(DAYS_YEAR/12.0)*months
    return {'kwh':kwh,'dkk':kwh*DKK_PER_KWH}


def safe_div(a,b):
    return a/b if b else None


def main():
    src=json.loads(v.INPUT.read_text(encoding='utf-8'))
    if not src.get('gate_passed'):
        raise SystemExit('PRICE DATA GATE FAILED upstream')

    devices=v.get_json(v.BOT_BASE+'/devices/with-counts')
    stats=v.get_json(v.BOT_BASE+'/devices/pool-statistics')
    stats_by_cfg={int(s['deviceConfigurationId']):s for s in stats if s.get('deviceConfigurationId') is not None}
    calibration=safe_partial_calibration(devices,stats_by_cfg)
    reward_scale=float(calibration['scale'])

    valued=[]; unsupported=[]; core_incompatible=[]
    for row in src.get('ranked_by_verified_ask',[]):
        model=row.get('model') or ''
        core_ok,core_reason=v.core_compatibility(model,row.get('title',''),row.get('description',''))
        if not core_ok:
            core_incompatible.append({'listing_id':row.get('listing_id'),'model':model,'url':row.get('url'),'reason':core_reason})
            continue
        d=v.exact_device(devices,model)
        if not d:
            unsupported.append({'listing_id':row.get('listing_id'),'model':model,'reason':'no unique exact AcurastBot device match'})
            continue
        picked=v.choose_config(d,row.get('title',''),stats_by_cfg)
        if not picked:
            unsupported.append({'listing_id':row.get('listing_id'),'model':model,'reason':'no AcurastBot configuration stats'})
            continue
        cfg,st=picked; rw=v.rewards(st)
        if not rw:
            unsupported.append({'listing_id':row.get('listing_id'),'model':model,'reason':'no expectedReward stats'})
            continue

        ask=int(row.get('ask_t2') or row.get('ask_t1'))
        lo=rw['low']*reward_scale
        base=rw['base']*reward_scale
        high=rw['high']*reward_scale
        conservative=rw['conservative']*reward_scale
        bid_basis=rw['bid_reward']*reward_scale
        base_year=annual_acu(base)
        cons_year=annual_acu(conservative)
        bid_year=annual_acu(bid_basis)

        item={
            'listing_id':row['listing_id'],'url':row['url'],'title':row['title'],'model':model,'ask':ask,
            'price_source':'DBA same-listing T1/T2 structured verification',
            'verified_timestamp':row.get('final_timestamp') or src.get('generated_at'),
            'core_android_min':v.CORE_MIN_ANDROID,'core_compatibility':True,'core_compatibility_reason':core_reason,
            'acurastbot_device':f"{d.get('company')} {d.get('model')}",'configuration_id':cfg.get('id'),
            'ram':cfg.get('ram'),'storage':cfg.get('storage'),'processor_count':rw['count'],
            'confidence':rw['confidence'],'confidence_factor':rw['confidence_factor'],
            'bid_evidence_factor':rw['bid_evidence_factor'],'spread_ratio':rw['spread_ratio'],
            'absolute_reward_scale':reward_scale,
            'acu_epoch_low':lo,'acu_epoch_base':base,'acu_epoch_conservative':conservative,'acu_epoch_bid_basis':bid_basis,'acu_epoch_high':high,
            'acu_day_base':base*EPOCHS_DAY,'acu_month_base':base*EPOCHS_DAY*(DAYS_YEAR/12.0),'acu_year_base':base_year,
            'acu_year_conservative':cons_year,'acu_year_bid_basis':bid_year,
            'aae_ask_base':safe_div(base_year,ask),'aae_ask_low':safe_div(cons_year,ask),
            'aae_100_ask_base':safe_div(base_year*100.0,ask),
        }
        valued.append(item)

    if not valued:
        raise SystemExit('ACURAST CORE DATA GATE FAILED — no Android 12+ valuatable live phones')

    # Market-relative acquisition-price ceilings use conservative annual ACU, not fiat token value.
    market_aae=[x['aae_ask_low'] for x in valued if x['aae_ask_low'] and x['aae_ask_low']>0]
    target_hurdle=v.percentile(market_aae,0.75)
    hard_hurdle=v.percentile(market_aae,0.50)
    start_hurdle=target_hurdle*1.25

    for x in valued:
        bid_year=x['acu_year_bid_basis']
        theoretical_start=v.round25(bid_year/start_hurdle) if start_hurdle>0 else 25
        theoretical_target=v.round25(bid_year/target_hurdle) if target_hurdle>0 else x['ask']
        theoretical_hard=v.round25(bid_year/hard_hurdle) if hard_hurdle>0 else theoretical_target

        x['start_bid']=min(x['ask'],theoretical_start)
        x['target']=min(x['ask'],max(x['start_bid'],theoretical_target))
        x['hard_max']=max(x['target'],theoretical_hard)
        x['aae_target_base']=safe_div(x['acu_year_base'],x['target'])
        x['aae_target_low']=safe_div(x['acu_year_conservative'],x['target'])
        x['aae_hard_max_base']=safe_div(x['acu_year_base'],x['hard_max'])
        x['aae_hard_max_low']=safe_div(x['acu_year_conservative'],x['hard_max'])

        # 12/24/36m ACU production. LOW includes reward-dilution stress; BASE/HIGH do not.
        cumulative={}
        for months in (12,24,36):
            elec=electricity(months)
            low_cum=cumulative_low(x['acu_epoch_conservative'],months)
            base_cum=cumulative_base(x['acu_epoch_base'],months)
            high_cum=cumulative_base(x['acu_epoch_high'],months)
            be=safe_div(x['target']+elec['dkk'],low_cum)
            cumulative[str(months)]={
                'acu_low_stress':low_cum,'acu_base':base_cum,'acu_high':high_cum,
                'electricity_kwh':elec['kwh'],'electricity_dkk':elec['dkk'],
                'break_even_acu_price_dkk_low_stress_at_target':be,
                'scenario_value_base_dkk':{str(p):base_cum*p for p in PRICE_SCENARIOS},
            }
        x['cumulative']=cumulative
        one_year_elec=electricity(12)
        x['electricity_kwh_month']=one_year_elec['kwh']/12.0
        x['electricity_dkk_month']=one_year_elec['dkk']/12.0
        x['energy_dkk_per_acu_base']=safe_div(one_year_elec['dkk'],x['acu_year_base'])

        if x['ask']<=x['target'] and x['aae_ask_low']>=target_hurdle:
            x['decision']='STRONG BID'
        elif x['ask']<=x['hard_max']:
            x['decision']='BID'
        else:
            x['decision']='WATCH/NEGOTIATE'
        x['opportunity_score']=100.0*(x['aae_ask_low']/hard_hurdle) if hard_hurdle>0 else 0.0

    # Primary ranking: conservative ACU/year per ASK DKK, then evidence confidence.
    valued.sort(key=lambda x:(-x['aae_ask_low'],-x['confidence_factor'],x['ask']))

    out={
        'generated_at':datetime.now(timezone.utc).isoformat(),
        'model_version':'V1.4-AAE-LONG-HORIZON',
        'valuation_gate':True,
        'dba_same_listing_gate':True,
        'core_gate':{'minimum_android':v.CORE_MIN_ANDROID,'mode':'hard fail-closed allowlist','excluded_count':len(core_incompatible)},
        'reward_calibration':calibration,
        'economic_invariant':'Rank and bid on long-term ACU accumulation efficiency; ACU spot price is not a purchase gate.',
        'ranking_metric':'conservative annual ACU / verified DBA ASK DKK; acquisition ceilings use conservative annual ACU and market-relative AAE hurdles',
        'reward_decay_stress':{'low_path_annual_decay':ANNUAL_LOW_REWARD_DECAY,'base_path_decay':0.0,'high_path_decay':0.0},
        'electricity_assumption':{'wall_power_w':POWER_W_WALL,'dkk_per_kwh':DKK_PER_KWH,'note':'explicit conservative generic phone-farm assumption; replace with measured per-device draw when available'},
        'price_scenarios_dkk_per_acu':PRICE_SCENARIOS,
        'hurdles':{'start_annual_conservative_aae':start_hurdle,'target_annual_conservative_aae_p75':target_hurdle,'hard_max_annual_conservative_aae_p50':hard_hurdle},
        'dba_counts':src.get('counts'),
        'ranked':valued,'core_incompatible':core_incompatible,'unsupported':unsupported,
    }
    v.OUTPUT.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')

    lines=[
        '# Acurast DBA Procurement V1.4 — ACU Accumulation Efficiency','',
        f"Generated: {out['generated_at']}",'',
        'DBA data gate: **PASS** — live same-listing structured discovery + T1/T2 verification.',
        'Primary objective: **maximize long-term ACU accumulation per invested DKK**. Current ACU spot price is not used as a purchase gate.',
        f"Reward calibration: **{calibration['status']}**, scale ×{calibration['scale']:.3f}, exact reference matches {calibration['matched']}/7.",
        f"LOW stress path: {ANNUAL_LOW_REWARD_DECAY*100:.0f}% annual reward decay. Electricity assumption: {POWER_W_WALL:.1f} W wall draw at {DKK_PER_KWH:.2f} DKK/kWh.",'',
        '| # | Model | ASK | ACU/epoch LOW | BASE | HIGH | ACU/år BASE | AAE LOW @ASK | AAE BASE @ASK | Start | Target | Hard max | 24m BE ACU | Klasse | Link |',
        '|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|'
    ]
    for i,x in enumerate(valued,1):
        be24=x['cumulative']['24']['break_even_acu_price_dkk_low_stress_at_target']
        lines.append(f"| {i} | {x['model']} | {x['ask']} | {x['acu_epoch_conservative']:.5f} | {x['acu_epoch_base']:.5f} | {x['acu_epoch_high']:.5f} | {x['acu_year_base']:.1f} | {x['aae_ask_low']:.4f} | {x['aae_ask_base']:.4f} | {x['start_bid']} | {x['target']} | {x['hard_max']} | {be24:.2f} | {x['decision']} | [DBA]({x['url']}) |")

    lines += ['', '## Topkandidater', '']
    for x in valued[:12]:
        c12=x['cumulative']['12']; c24=x['cumulative']['24']; c36=x['cumulative']['36']
        lines.append(
            f"- **{x['model']}** — ASK {x['ask']} kr. — {x['acu_epoch_base']:.5f} ACU/epoch BASE; "
            f"{x['acu_year_base']:.1f} ACU/år; AAE BASE @ASK {x['aae_ask_base']:.4f}; "
            f"12/24/36m BASE {c12['acu_base']:.1f}/{c24['acu_base']:.1f}/{c36['acu_base']:.1f} ACU; "
            f"24m break-even LOW-stress {c24['break_even_acu_price_dkk_low_stress_at_target']:.2f} DKK/ACU; "
            f"start {x['start_bid']} / target {x['target']} / max {x['hard_max']} — **{x['decision']}** — [DBA]({x['url']})"
        )
    v.REPORT.write_text('\n'.join(lines)+'\n',encoding='utf-8')

    print(json.dumps({
        'valuation_gate':True,'model_version':out['model_version'],'ranked':len(valued),
        'core_excluded':len(core_incompatible),'unsupported':len(unsupported),
        'reward_calibration':{'status':calibration['status'],'scale':calibration['scale'],'matched':calibration['matched']},
        'top':[{k:x[k] for k in ('listing_id','model','ask','acu_epoch_base','acu_epoch_conservative','acu_year_base','aae_ask_low','aae_ask_base','start_bid','target','hard_max','decision','url')} for x in valued[:10]]
    },ensure_ascii=False,indent=2))


v.reference_device=strict_reference_device
v.reference_calibration=safe_partial_calibration

if __name__=='__main__':
    main()
