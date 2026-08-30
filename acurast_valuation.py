from __future__ import annotations

import json, math, re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

INPUT = Path('results/acurast_latest.json')
OUTPUT = Path('results/acurast_valuation.json')
REPORT = Path('results/acurast_valuation.md')

BOT_BASE = 'https://api.acurastbot.com'
EPOCHS_DAY = 16.0
REFERENCE_ACQUISITION_DKK = 275.0
ELECTRICITY_DKK_KWH = 2.50

# Fallback hardware metadata is only used for power/risk and for selecting the
# closest AcurastBot configuration. Reward ranking itself comes from AcurastBot.
PROFILES: dict[str, dict[str, Any]] = {
    'Samsung Galaxy S10': {'brand':'Samsung','ram':8,'storage':128,'watt':4.0,'risk':0.10},
    'Samsung Galaxy S20': {'brand':'Samsung','ram':8,'storage':128,'watt':4.8,'risk':0.12},
    'Samsung Galaxy S20 Ultra': {'brand':'Samsung','ram':12,'storage':128,'watt':5.0,'risk':0.12},
    'Samsung Galaxy S21': {'brand':'Samsung','ram':8,'storage':128,'watt':4.8,'risk':0.10},
    'Samsung Galaxy S21 Ultra': {'brand':'Samsung','ram':12,'storage':128,'watt':5.0,'risk':0.10},
    'Samsung Galaxy S22': {'brand':'Samsung','ram':8,'storage':128,'watt':5.8,'risk':0.18},
    'Samsung Galaxy S22 Ultra': {'brand':'Samsung','ram':8,'storage':128,'watt':6.0,'risk':0.18},
    'Samsung Galaxy S23': {'brand':'Samsung','ram':8,'storage':128,'watt':5.0,'risk':0.07},
    'Samsung Galaxy S23 FE': {'brand':'Samsung','ram':8,'storage':128,'watt':5.8,'risk':0.16},
    'Samsung Galaxy Z Flip4': {'brand':'Samsung','ram':8,'storage':128,'watt':5.2,'risk':0.20},
    'Samsung Galaxy Z Flip5': {'brand':'Samsung','ram':8,'storage':256,'watt':5.0,'risk':0.15},
    'OnePlus Nord 2': {'brand':'OnePlus','ram':8,'storage':128,'watt':4.4,'risk':0.08},
    'OnePlus Nord 2T': {'brand':'OnePlus','ram':8,'storage':128,'watt':4.4,'risk':0.08},
    'OnePlus Nord 3': {'brand':'OnePlus','ram':16,'storage':256,'watt':5.2,'risk':0.09},
    'OnePlus 9': {'brand':'OnePlus','ram':8,'storage':128,'watt':6.2,'risk':0.20},
    'OnePlus 9 Pro': {'brand':'OnePlus','ram':8,'storage':128,'watt':6.4,'risk':0.20},
    'OnePlus 10': {'brand':'OnePlus','ram':8,'storage':128,'watt':6.4,'risk':0.22},
    'OnePlus 10 Pro': {'brand':'OnePlus','ram':8,'storage':128,'watt':6.4,'risk':0.22},
    'OnePlus 11': {'brand':'OnePlus','ram':8,'storage':128,'watt':5.1,'risk':0.07},
    'Xiaomi 11': {'brand':'Xiaomi','ram':8,'storage':128,'watt':6.2,'risk':0.20},
    'Xiaomi 12': {'brand':'Xiaomi','ram':8,'storage':128,'watt':6.3,'risk':0.22},
    'Xiaomi 12 Pro': {'brand':'Xiaomi','ram':12,'storage':256,'watt':6.5,'risk':0.22},
    'Poco F3': {'brand':'Poco','ram':8,'storage':128,'watt':5.0,'risk':0.10},
    'Poco F4': {'brand':'Poco','ram':8,'storage':128,'watt':5.0,'risk':0.10},
    'Poco F5': {'brand':'Poco','ram':8,'storage':256,'watt':4.8,'risk':0.08},
    'Motorola Edge 30': {'brand':'Motorola','ram':8,'storage':128,'watt':4.2,'risk':0.08},
    'Motorola Edge 40': {'brand':'Motorola','ram':8,'storage':256,'watt':4.5,'risk':0.08},
    'Motorola Edge 40 Neo': {'brand':'Motorola','ram':12,'storage':256,'watt':4.2,'risk':0.08},
    'Google Pixel 6': {'brand':'Google','ram':8,'storage':128,'watt':5.4,'risk':0.14},
    'Google Pixel 7': {'brand':'Google','ram':8,'storage':128,'watt':5.2,'risk':0.13},
    'Google Pixel 8': {'brand':'Google','ram':8,'storage':128,'watt':5.2,'risk':0.12},
}

FARM_MODELS = [
    'Samsung Galaxy S10','Samsung Galaxy S20 Ultra','Samsung Galaxy S21 Ultra',
    'OnePlus Nord 2T','OnePlus Nord 2T','OnePlus Nord 3','Xiaomi 12 Pro'
]


def get_json(url: str) -> Any:
    r = requests.get(url, timeout=30, headers={'User-Agent':'Mozilla/5.0'})
    r.raise_for_status()
    return r.json()


def norm(s: str) -> str:
    return re.sub(r'[^a-z0-9]+', ' ', (s or '').lower()).strip()


def num_gb(v: Any) -> int | None:
    if v is None: return None
    m = re.search(r'(\d+)', str(v))
    return int(m.group(1)) if m else None


def parse_title_capacity(title: str, default_ram: int, default_storage: int) -> tuple[int,int]:
    vals = [int(x) for x in re.findall(r'(\d{1,4})\s*gb', title.lower())]
    ram = next((x for x in vals if x in (4,6,8,10,12,16,18,24)), default_ram)
    storage = next((x for x in vals if x >= 64), default_storage)
    return ram, storage


def round25(v: float) -> int:
    return max(25, int(round(v / 25.0) * 25))


def find_device(devices: list[dict[str,Any]], model: str, brand: str) -> dict[str,Any] | None:
    wanted = norm(model.replace(brand, '', 1))
    wt = set(wanted.split())
    candidates=[]
    for d in devices:
        if norm(d.get('company','')) != norm(brand):
            continue
        dm = norm(d.get('model',''))
        dt = set(dm.split())
        overlap = len(wt & dt)
        if overlap == 0: continue
        missing = len(wt - dt)
        extra = len(dt - wt)
        score = overlap*10 - missing*7 - extra
        candidates.append((score,d))
    return max(candidates,key=lambda x:x[0])[1] if candidates else None


def choose_config(device: dict[str,Any], ram: int, storage: int, stats_by_cfg: dict[int,dict[str,Any]]) -> tuple[dict[str,Any],dict[str,Any]] | None:
    opts=[]
    for c in device.get('configurations') or []:
        cid=c.get('id'); st=stats_by_cfg.get(int(cid)) if cid is not None else None
        if not st: continue
        cr=num_gb(c.get('ram')); cs=num_gb(c.get('storage'))
        penalty=(abs((cr or ram)-ram)*8 + abs((cs or storage)-storage)/32)
        opts.append((penalty,c,st))
    if not opts: return None
    _,c,st=min(opts,key=lambda x:x[0])
    return c,st


def reward_from_stats(st: dict[str,Any]) -> dict[str,float] | None:
    def f(k: str) -> float | None:
        try: return float(st[k])
        except Exception: return None
    med=f('expectedRewardMedian')
    avg=f('expectedRewardAvg')
    lo=f('expectedRewardMin')
    hi=f('expectedRewardMax')
    base = med if med is not None else avg
    if base is None: return None
    # AcurastBot labels this metric cACU/epoch; 1 cACU = 0.01 ACU.
    return {'low':(lo if lo is not None else base)*0.01,
            'base':base*0.01,
            'high':(hi if hi is not None else base)*0.01,
            'raw_cacu_median':med,'raw_cacu_avg':avg}


def fetch_acu_dkk() -> tuple[float | None,dict[str,Any]]:
    url='https://api.coingecko.com/api/v3/simple/price'
    try:
        r=requests.get(url,params={'ids':'acurast','vs_currencies':'dkk,usd'},timeout=20,headers={'User-Agent':'Mozilla/5.0'})
        r.raise_for_status(); d=(r.json().get('acurast') or {})
        return (float(d['dkk']) if d.get('dkk') is not None else None,
                {'source':'CoinGecko','dkk':d.get('dkk'),'usd':d.get('usd')})
    except Exception as e:
        return None, {'source':'CoinGecko','error':repr(e)}


def main():
    src=json.loads(INPUT.read_text(encoding='utf-8'))
    if not src.get('gate_passed'):
        raise SystemExit('PRICE DATA GATE FAILED upstream')

    devices=get_json(BOT_BASE+'/devices/with-counts')
    stats=get_json(BOT_BASE+'/devices/pool-statistics')
    stats_by_cfg={int(s['deviceConfigurationId']):s for s in stats if s.get('deviceConfigurationId') is not None}

    # Build AcurastBot benchmark reference from the user's current seven-phone mix.
    farm_rewards=[]
    for model in FARM_MODELS:
        p=PROFILES[model]; d=find_device(devices,model,p['brand'])
        if not d: continue
        picked=choose_config(d,p['ram'],p['storage'],stats_by_cfg)
        if not picked: continue
        rw=reward_from_stats(picked[1])
        if rw: farm_rewards.append(rw['base'])
    if len(farm_rewards) < 4:
        raise SystemExit('ACURASTBOT DATA GATE FAILED — insufficient farm benchmark coverage')
    farm_ref=sum(farm_rewards)/len(farm_rewards)

    acu_dkk, token_meta=fetch_acu_dkk()  # scenario/reference only; never drives primary ranking/bids
    valued=[]; unsupported=[]
    for row in src.get('ranked_by_verified_ask',[]):
        model=row.get('model'); p=PROFILES.get(model)
        if not p:
            unsupported.append({'listing_id':row.get('listing_id'),'model':model,'reason':'no profile'}); continue
        d=find_device(devices,model,p['brand'])
        if not d:
            unsupported.append({'listing_id':row.get('listing_id'),'model':model,'reason':'no AcurastBot device match'}); continue
        ram,storage=parse_title_capacity(row.get('title',''),p['ram'],p['storage'])
        picked=choose_config(d,ram,storage,stats_by_cfg)
        if not picked:
            unsupported.append({'listing_id':row.get('listing_id'),'model':model,'reason':'no AcurastBot stats for configuration'}); continue
        cfg,st=picked; rw=reward_from_stats(st)
        if not rw:
            unsupported.append({'listing_id':row.get('listing_id'),'model':model,'reason':'no AcurastBot expectedReward'}); continue

        ask=int(row.get('ask_t2') or row.get('ask_t1'))
        perf=rw['base']/farm_ref if farm_ref>0 else 1.0
        risk=float(p['risk'])
        # Price-independent accumulation budget: scale historical desired acquisition level by
        # observed AcurastBot reward performance vs current farm, then apply risk haircut.
        target=round25(REFERENCE_ACQUISITION_DKK*perf*(1-risk))
        hard=round25(target*1.30)
        start=round25(target*0.65)
        acu_month=rw['base']*EPOCHS_DAY*30
        aae_ask=acu_month/ask if ask>0 else 0
        aae_target=acu_month/target if target>0 else 0
        if ask <= target: decision='STRONG BID'
        elif ask <= hard: decision='BID'
        else: decision='LOW OFFER / NEGOTIATE'

        power_month=p['watt']*24*30/1000*ELECTRICITY_DKK_KWH
        spot={}
        if acu_dkk is not None:
            for label,mult in [('spot_0_5x',0.5),('spot_1_0x',1.0),('spot_2_0x',2.0),('spot_5_0x',5.0)]:
                gross=acu_month*acu_dkk*mult
                spot[label]={'gross_dkk_month':gross,'net_after_power_dkk_month':gross-power_month,
                             'payback_at_target_months':target/(gross-power_month) if gross>power_month else None}

        valued.append({
            'listing_id':row['listing_id'],'url':row['url'],'title':row['title'],'model':model,'ask':ask,
            'acurastbot_device':f"{d.get('company')} {d.get('model')}",
            'acurastbot_configuration_id':cfg.get('id'),'acurastbot_ram':cfg.get('ram'),'acurastbot_storage':cfg.get('storage'),
            'acurastbot_processor_count':st.get('processorCount'),'acurastbot_calculated_at':st.get('calculatedAt'),
            'acu_epoch_low':rw['low'],'acu_epoch_base':rw['base'],'acu_epoch_high':rw['high'],'acu_month_base':acu_month,
            'relative_to_current_farm_reference':perf,
            'aae_ask_acu_month_per_dkk':aae_ask,'aae_target_acu_month_per_dkk':aae_target,
            'start_bid':start,'target':target,'hard_max':hard,'decision':decision,
            'power_dkk_month_assumption':power_month,'spot_scenarios':spot,
        })

    # Primary ranking = ACU accumulation efficiency at verified ASK, not current ACU spot price.
    valued.sort(key=lambda x:(-x['aae_ask_acu_month_per_dkk'],x['ask']))
    out={'generated_at':datetime.now(timezone.utc).isoformat(),'valuation_gate':True,
         'method':'AcurastBot observed expected reward + verified DBA ASK; primary metric AAE',
         'reference_acquisition_dkk':REFERENCE_ACQUISITION_DKK,
         'farm_acurastbot_reference_acu_epoch':farm_ref,'farm_reference_device_count':len(farm_rewards),
         'token_price_reference_only':token_meta,'electricity_reference_only':{'dkk_kwh':ELECTRICITY_DKK_KWH},
         'dba_counts':src.get('counts'),'ranked':valued,'unsupported':unsupported}
    OUTPUT.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')

    lines=['# Acurast DBA Value Hunter','',f"Generated: {out['generated_at']}",'',
           'DBA data gate: **PASS** — structured discovery + same-listing live verification + final refetch.',
           f"AcurastBot data gate: **PASS** — farm reference based on {len(farm_rewards)} current-phone entries.",
           '', '> Primær rangering er **AAE = forventet ACU pr. måned pr. investeret DKK**. ACU spotpris bruges kun som scenariereference og påvirker ikke rangering, STARTBUD, TARGET eller HARD MAX.',
           '', '| # | Model | ASK | AcurastBot ACU/epoch | ACU/md | AAE ved ASK | Start | Target | Hard max | Beslutning |',
           '|---:|---|---:|---:|---:|---:|---:|---:|---:|---|']
    for i,r in enumerate(valued[:30],1):
        lines.append(f"| {i} | [{r['model']}]({r['url']}) | {r['ask']} | {r['acu_epoch_base']:.5f} | {r['acu_month_base']:.2f} | {r['aae_ask_acu_month_per_dkk']:.4f} | {r['start_bid']} | {r['target']} | {r['hard_max']} | {r['decision']} |")
    lines += ['', '## Bedste bud nu','']
    for r in valued[:10]:
        lines.append(f"- **{r['model']}** — ASK {r['ask']} kr. — AAE {r['aae_ask_acu_month_per_dkk']:.4f} — start {r['start_bid']} kr., target {r['target']} kr., walk-away {r['hard_max']} kr. — **{r['decision']}** — [DBA]({r['url']})")
    if unsupported:
        lines += ['',f"Ikke rangeret pga. manglende AcurastBot-match/statistik: {len(unsupported)} annoncer."]
    REPORT.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({'valuation_gate':True,'farm_ref_acu_epoch':farm_ref,'ranked':len(valued),'unsupported':len(unsupported),
                      'top':[{k:r[k] for k in ('listing_id','model','ask','acu_epoch_base','aae_ask_acu_month_per_dkk','start_bid','target','hard_max','decision')} for r in valued[:10]]},ensure_ascii=False,indent=2))

if __name__=='__main__': main()
