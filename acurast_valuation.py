from __future__ import annotations

import json, math, statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

INPUT = Path('results/acurast_latest.json')
OUTPUT = Path('results/acurast_valuation.json')
REPORT = Path('results/acurast_valuation.md')

# Official Mainnet benchmark metric weights, verified against Acurast docs.
WEIGHTS = {'cpu_sc': 0.2307, 'cpu_mc': 0.2307, 'ram': 0.4615, 'storage': 0.0769}
EPOCHS_DAY = 16.0  # ~900 blocks / ~90 minutes
FARM_PHONES = 7
FARM_REWARD_BASE = 0.27  # observed midpoint ACU/epoch for current farm
FARM_REWARD_LOW = 0.22
FARM_REWARD_HIGH = 0.32
FARM_AVAILABLE_RAM_GB = 60.9
FARM_AVAILABLE_STORAGE_GB = 802.89
FARM_AVG_AVAILABLE_RAM = FARM_AVAILABLE_RAM_GB / FARM_PHONES
FARM_AVG_AVAILABLE_STORAGE = FARM_AVAILABLE_STORAGE_GB / FARM_PHONES
ELECTRICITY_DKK_KWH = 2.50  # conservative fallback; explicitly reported as assumption

# Relative CPU factors are intentionally coarse and calibrated around the user's current mixed farm = 1.0.
# RAM/storage are modelled separately using estimated Acurast-available capacity.
PROFILES: dict[str, dict[str, Any]] = {
    'Samsung Galaxy S10': {'ram':8,'storage':128,'soc':'Exynos 9820','sc':0.72,'mc':0.66,'watt':4.0,'risk':0.10},
    'Samsung Galaxy S20': {'ram':8,'storage':128,'soc':'Exynos 990','sc':0.82,'mc':0.78,'watt':4.8,'risk':0.12},
    'Samsung Galaxy S20 Ultra': {'ram':12,'storage':128,'soc':'Exynos 990','sc':0.82,'mc':0.78,'watt':5.0,'risk':0.12},
    'Samsung Galaxy S21': {'ram':8,'storage':128,'soc':'Exynos 2100','sc':0.98,'mc':0.98,'watt':4.8,'risk':0.10},
    'Samsung Galaxy S21 Ultra': {'ram':12,'storage':128,'soc':'Exynos 2100','sc':0.98,'mc':0.98,'watt':5.0,'risk':0.10},
    'Samsung Galaxy S22': {'ram':8,'storage':128,'soc':'Exynos 2200','sc':1.10,'mc':1.06,'watt':5.8,'risk':0.18},
    'Samsung Galaxy S22 Ultra': {'ram':8,'storage':128,'soc':'Exynos 2200','sc':1.10,'mc':1.06,'watt':6.0,'risk':0.18},
    'Samsung Galaxy S23': {'ram':8,'storage':128,'soc':'Snapdragon 8 Gen 2','sc':1.34,'mc':1.32,'watt':5.0,'risk':0.07},
    'Samsung Galaxy S23 FE': {'ram':8,'storage':128,'soc':'Exynos 2200','sc':1.10,'mc':1.06,'watt':5.8,'risk':0.16},
    'Samsung Galaxy Z Flip4': {'ram':8,'storage':128,'soc':'Snapdragon 8+ Gen 1','sc':1.22,'mc':1.18,'watt':5.2,'risk':0.20},
    'Samsung Galaxy Z Flip5': {'ram':8,'storage':256,'soc':'Snapdragon 8 Gen 2','sc':1.34,'mc':1.32,'watt':5.0,'risk':0.15},
    'OnePlus Nord 2': {'ram':8,'storage':128,'soc':'Dimensity 1200','sc':0.90,'mc':0.92,'watt':4.4,'risk':0.08},
    'OnePlus Nord 2T': {'ram':8,'storage':128,'soc':'Dimensity 1300','sc':0.94,'mc':0.95,'watt':4.4,'risk':0.08},
    'OnePlus Nord 3': {'ram':16,'storage':256,'soc':'Dimensity 9000','sc':1.25,'mc':1.30,'watt':5.2,'risk':0.09},
    'OnePlus 9': {'ram':8,'storage':128,'soc':'Snapdragon 888','sc':1.04,'mc':1.02,'watt':6.2,'risk':0.20},
    'OnePlus 9 Pro': {'ram':8,'storage':128,'soc':'Snapdragon 888','sc':1.04,'mc':1.02,'watt':6.4,'risk':0.20},
    'OnePlus 10': {'ram':8,'storage':128,'soc':'Snapdragon 8 Gen 1','sc':1.12,'mc':1.08,'watt':6.4,'risk':0.22},
    'OnePlus 10 Pro': {'ram':8,'storage':128,'soc':'Snapdragon 8 Gen 1','sc':1.12,'mc':1.08,'watt':6.4,'risk':0.22},
    'OnePlus 11': {'ram':8,'storage':128,'soc':'Snapdragon 8 Gen 2','sc':1.34,'mc':1.32,'watt':5.1,'risk':0.07},
    'Xiaomi 11': {'ram':8,'storage':128,'soc':'Snapdragon 888','sc':1.04,'mc':1.02,'watt':6.2,'risk':0.20},
    'Xiaomi 12': {'ram':8,'storage':128,'soc':'Snapdragon 8 Gen 1','sc':1.12,'mc':1.08,'watt':6.3,'risk':0.22},
    'Xiaomi 12 Pro': {'ram':12,'storage':256,'soc':'Snapdragon 8 Gen 1','sc':1.12,'mc':1.08,'watt':6.5,'risk':0.22},
    'Poco F3': {'ram':8,'storage':128,'soc':'Snapdragon 870','sc':0.94,'mc':0.91,'watt':5.0,'risk':0.10},
    'Poco F4': {'ram':8,'storage':128,'soc':'Snapdragon 870','sc':0.94,'mc':0.91,'watt':5.0,'risk':0.10},
    'Poco F5': {'ram':8,'storage':256,'soc':'Snapdragon 7+ Gen 2','sc':1.18,'mc':1.16,'watt':4.8,'risk':0.08},
    'Motorola Edge 30': {'ram':8,'storage':128,'soc':'Snapdragon 778G+','sc':0.84,'mc':0.82,'watt':4.2,'risk':0.08},
    'Motorola Edge 40': {'ram':8,'storage':256,'soc':'Dimensity 8020','sc':0.98,'mc':1.00,'watt':4.5,'risk':0.08},
    'Motorola Edge 40 Neo': {'ram':12,'storage':256,'soc':'Dimensity 7030','sc':0.82,'mc':0.82,'watt':4.2,'risk':0.08},
    'Google Pixel 6': {'ram':8,'storage':128,'soc':'Tensor G1','sc':0.93,'mc':0.88,'watt':5.4,'risk':0.14},
    'Google Pixel 7': {'ram':8,'storage':128,'soc':'Tensor G2','sc':1.00,'mc':0.94,'watt':5.2,'risk':0.13},
    'Google Pixel 8': {'ram':8,'storage':128,'soc':'Tensor G3','sc':1.10,'mc':1.03,'watt':5.2,'risk':0.12},
}


def fetch_acu_dkk() -> tuple[float | None, dict[str, Any]]:
    url='https://api.coingecko.com/api/v3/simple/price'
    try:
        r=requests.get(url,params={'ids':'acurast','vs_currencies':'dkk,usd'},timeout=20,headers={'User-Agent':'Mozilla/5.0'})
        r.raise_for_status(); data=r.json().get('acurast') or {}
        dkk=float(data['dkk']) if data.get('dkk') is not None else None
        return dkk, {'source':'CoinGecko simple price','url':url,'usd':data.get('usd'),'dkk':dkk,'ok':dkk is not None}
    except Exception as e:
        return None, {'source':'CoinGecko simple price','url':url,'ok':False,'error':repr(e)}


def round25(v: float) -> int:
    return max(0, int(math.floor(v / 25.0) * 25))


def available_ram(physical: float) -> float:
    # Empirical farm relationship is around 80% for a plausible 76 GB physical total.
    return physical * 0.80


def available_storage(nominal: float) -> float:
    # Conservative allowance for Android/system/reserved space.
    return nominal * 0.78


def reward_estimate(profile: dict[str, Any]) -> dict[str, float]:
    ram_rel=available_ram(profile['ram'])/FARM_AVG_AVAILABLE_RAM
    storage_rel=available_storage(profile['storage'])/FARM_AVG_AVAILABLE_STORAGE
    idx=(WEIGHTS['cpu_sc']*profile['sc'] + WEIGHTS['cpu_mc']*profile['mc'] + WEIGHTS['ram']*ram_rel + WEIGHTS['storage']*storage_rel)
    avg=FARM_REWARD_BASE/FARM_PHONES
    # Base is empirical farm-calibrated. LOW/HIGH deliberately wide because global metric pool totals and exact device Acurast benchmarks are unavailable here.
    base=avg*idx
    low=base*0.70
    high=base*1.30
    return {'index':idx,'low':low,'base':base,'high':high,'available_ram_gb':available_ram(profile['ram']),'available_storage_gb':available_storage(profile['storage'])}


def economics(reward: dict[str,float], profile: dict[str,Any], acu_dkk: float) -> dict[str,Any]:
    power_month=profile['watt']*24*30/1000*ELECTRICITY_DKK_KWH
    out={'power_dkk_month':power_month}
    for name,mult in [('bear',0.5),('base',1.0),('bull',1.5)]:
        gross=reward['base']*EPOCHS_DAY*30*acu_dkk*mult
        out[f'gross_{name}_dkk_month']=gross
        out[f'net_{name}_dkk_month']=gross-power_month
    low_net=reward['low']*EPOCHS_DAY*30*acu_dkk-power_month
    high_net=reward['high']*EPOCHS_DAY*30*acu_dkk-power_month
    out['net_reward_low_dkk_month']=low_net
    out['net_reward_high_dkk_month']=high_net
    # Procurement limits: target <=8m base payback, hard max <=12m conservative reward payback, both risk haircutted.
    risk=float(profile.get('risk',0.1))
    target=round25(max(0,out['net_base_dkk_month']*8*(1-risk)))
    hard=round25(max(0,low_net*12*(1-risk)))
    hard=max(target,hard) if target else hard
    start=round25(target*0.65) if target else 0
    out.update({'start_bid':start,'target':target,'hard_max':hard})
    return out


def classify(ask:int,econ:dict[str,Any]) -> str:
    target=econ['target']; hard=econ['hard_max']
    if hard<=0:return 'REJECT'
    if ask<=target and econ['net_reward_low_dkk_month']>0:return 'STRONG BID'
    if ask<=hard:return 'BID'
    # High ASK can still be a rational low-offer case.
    if ask<=hard*1.8:return 'BID / LOW OFFER'
    if target>0:return 'WATCH/NEGOTIATE'
    return 'REJECT'


def payback(price:int,net:float)->float|None:
    return round(price/net,1) if net>0 else None


def main():
    src=json.loads(INPUT.read_text(encoding='utf-8'))
    if not src.get('gate_passed'):
        raise SystemExit('PRICE DATA GATE FAILED upstream')
    acu_dkk,price_meta=fetch_acu_dkk()
    if acu_dkk is None:
        # Do not fabricate token economics. Preserve verified DBA data but fail valuation gate.
        out={'generated_at':datetime.now(timezone.utc).isoformat(),'valuation_gate':False,'reason':'ACU PRICE GATE FAILED','price_meta':price_meta}
        OUTPUT.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
        REPORT.write_text('# Acurast procurement valuation\n\n**ACU PRICE GATE FAILED — ingen ROI-rangering**\n',encoding='utf-8')
        raise SystemExit('ACU PRICE GATE FAILED')

    valued=[]; unsupported=[]
    for row in src.get('ranked_by_verified_ask',[]):
        model=row.get('model'); profile=PROFILES.get(model)
        if not profile:
            unsupported.append({'listing_id':row.get('listing_id'),'model':model,'reason':'no conservative hardware profile'}); continue
        reward=reward_estimate(profile); econ=economics(reward,profile,acu_dkk); ask=int(row.get('ask_t2') or row.get('ask_t1'))
        decision=classify(ask,econ)
        base_net=econ['net_base_dkk_month']; low_net=econ['net_reward_low_dkk_month']
        x={
            'listing_id':row['listing_id'],'url':row['url'],'title':row['title'],'model':model,'ask':ask,
            't1_timestamp':row.get('t1_timestamp'),'final_timestamp':row.get('final_timestamp'),
            'soc':profile['soc'],'ram_gb':profile['ram'],'storage_gb':profile['storage'],'watt':profile['watt'],
            'acurastbot':'unavailable/not integrated: no verified public device-data endpoint used',
            'reward_source':'empirical farm calibration + official metric weights; not exact per-device Acurast benchmark',
            'acu_epoch_low':reward['low'],'acu_epoch_base':reward['base'],'acu_epoch_high':reward['high'],
            'acu_month_base':reward['base']*EPOCHS_DAY*30,'acu_dkk':acu_dkk,
            **econ,
            'payback_target_months':payback(econ['target'],base_net) if econ['target'] else None,
            'payback_hard_max_months':payback(econ['hard_max'],low_net) if econ['hard_max'] else None,
            'ask_payback_base_months':payback(ask,base_net),
            'roi_12m_at_target_pct':round(((base_net*12-econ['target'])/econ['target']*100),1) if econ['target']>0 else None,
            'decision':decision,
            'risk':'thermal/condition/onboarding uncertainty + model-level rather than exact Acurast benchmark',
        }
        # capital efficiency at target; higher is better
        x['net_dkk_per_target_dkk_month']=base_net/econ['target'] if econ['target']>0 else 0
        valued.append(x)

    priority={'STRONG BID':0,'BID':1,'BID / LOW OFFER':2,'WATCH/NEGOTIATE':3,'REJECT':4}
    valued.sort(key=lambda x:(priority.get(x['decision'],9),-x['net_dkk_per_target_dkk_month'],x['ask']))
    out={
      'generated_at':datetime.now(timezone.utc).isoformat(),'valuation_gate':True,
      'upstream_generated_at':src.get('generated_at'),'regression':src.get('regression'),'dba_counts':src.get('counts'),
      'official_reward_model':{'weights':WEIGHTS,'epochs_day':EPOCHS_DAY,'base_benchmark_rewards_acu_epoch':856.164,'staking_rewards_acu_epoch':5993.15,'note':'staking/deployment rewards not added to procurement cashflow'},
      'farm_calibration':{'phones':FARM_PHONES,'observed_acu_epoch_low':FARM_REWARD_LOW,'observed_acu_epoch_base':FARM_REWARD_BASE,'observed_acu_epoch_high':FARM_REWARD_HIGH},
      'token_price':price_meta,'electricity':{'dkk_kwh':ELECTRICITY_DKK_KWH,'source':'conservative assumption'},
      'ranked':valued,'unsupported':unsupported}
    OUTPUT.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')

    lines=['# Acurast DBA Procurement Model — valuation','',f"Generated: {out['generated_at']}",'',
           f"DBA regression: **PASS** — listing 24247594 = {src['regression']['price']} kr.",
           f"ACU spot used: **{acu_dkk:.4f} DKK/ACU** (CoinGecko)",
           f"Electricity assumption: **{ELECTRICITY_DKK_KWH:.2f} DKK/kWh**",'',
           '> Reward estimates are LOW/BASE/HIGH farm-calibrated estimates using the official Acurast metric weights. Staking and deployment rewards are not added.','',
           '| Rank | Decision | ASK | Start | Target | Hard max | ACU/epoch L/B/H | Net base/md | Ask payback | Listing |',
           '|---:|---|---:|---:|---:|---:|---|---:|---:|---|']
    for i,r in enumerate(valued[:30],1):
        pb=f"{r['ask_payback_base_months']:.1f} mdr" if r['ask_payback_base_months'] is not None else '—'
        lines.append(f"| {i} | {r['decision']} | {r['ask']} kr. | {r['start_bid']} | {r['target']} | {r['hard_max']} | {r['acu_epoch_low']:.4f}/{r['acu_epoch_base']:.4f}/{r['acu_epoch_high']:.4f} | {r['net_base_dkk_month']:.1f} kr. | {pb} | [{r['model']}]({r['url']}) |")
    lines += ['', '## Top bid instructions','']
    for r in valued[:10]:
        lines.append(f"- **{r['model']} — {r['decision']}** — ASK {r['ask']} kr. — Start {r['start_bid']} kr.; gå til {r['target']} kr.; walk away {r['hard_max']} kr. — [DBA]({r['url']})")
    REPORT.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({'valuation_gate':True,'acu_dkk':acu_dkk,'ranked':len(valued),'top':[{k:r[k] for k in ('listing_id','model','ask','start_bid','target','hard_max','decision')} for r in valued[:10]]},ensure_ascii=False,indent=2))

if __name__=='__main__': main()
