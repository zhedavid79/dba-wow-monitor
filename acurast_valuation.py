from __future__ import annotations

import json, math, re, statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import requests

INPUT=Path('results/acurast_latest.json')
OUTPUT=Path('results/acurast_valuation.json')
REPORT=Path('results/acurast_valuation.md')
BOT_BASE='https://api.acurastbot.com'
EPOCHS_MONTH=16.0*30.0
CORE_MIN_ANDROID=12

# Acurast Core requires Android 12+. This is intentionally fail-closed:
# a device must match a known Android-12-capable model/family rule to enter valuation.
# Unknown models remain discoverable in DBA, but are excluded before AAE/bid ranking.
CORE_ANDROID12_RULES=[
    # Samsung flagship/foldable families with official Android 12+ availability.
    (r'\bsamsung\s+(?:galaxy\s+)?s10(?:e|\+|\s+plus)?\b', 'Samsung S10 family updated to Android 12'),
    (r'\bsamsung\s+(?:galaxy\s+)?s(?:20|21|22|23|24|25)(?:\s*(?:fe|ultra|\+|plus))?\b', 'Samsung S20+ family supports Android 12+'),
    (r'\bsamsung\s+(?:galaxy\s+)?note\s*10(?:\+|plus)?\b', 'Samsung Note 10 family updated to Android 12'),
    (r'\bsamsung\s+(?:galaxy\s+)?note\s*20(?:\s*ultra)?\b', 'Samsung Note 20 family supports Android 12+'),
    (r'\bsamsung\s+(?:galaxy\s+)?(?:z\s*)?(?:flip|fold)\s*[1-9]\b', 'Samsung Z Fold/Flip family supports Android 12+'),
    (r'\bsamsung\s+(?:galaxy\s+)?a(?:13|14|15|23|24|25|33|34|35|52|53|54|55|56|72|73)\b', 'Samsung A-series model supports Android 12+'),

    # Google Pixel: Pixel 3a/4 and newer received or launched with Android 12+.
    (r'\bgoogle\s+pixel\s+(?:3a|4(?:a)?|5(?:a)?|6(?:a|\s*pro)?|7(?:a|\s*pro)?|8(?:a|\s*pro)?|9(?:a|\s*pro|\s*pro\s*xl)?|10)\b', 'Google Pixel model supports Android 12+'),

    # OnePlus 7 generation and newer officially reached Android 12 or later.
    (r'\boneplus\s+(?:7|7t|8|8t|9|10|11|12|13)(?:\s*pro)?\b', 'OnePlus flagship family supports Android 12+'),
    (r'\boneplus\s+nord(?:\s+ce)?\s*(?:2|2t|3|4)(?:\s*lite)?\b', 'OnePlus Nord family supports Android 12+'),
    (r'\boneplus\s+nord\s*n(?:10|20|30)\b', 'OnePlus Nord N-series model supports Android 12+'),

    # Motorola models/families known to have Android 12+ support.
    (r'\bmotorola\s+g(?:30|31|32|34|42|52|53|54|60|62|71|72|73|82|84|85|100|200)\b', 'Motorola G-series model supports Android 12+'),
    (r'\bmotorola\s+e(?:13|14|20|22|32|40)\b', 'Motorola E-series model supports Android 12+'),
    (r'\bmotorola\s+edge\s*(?:20|30|40|50)(?:\s*(?:neo|fusion|pro|ultra))?\b', 'Motorola Edge family supports Android 12+'),
    (r'\bmotorola\s+razr\s*(?:2022|40|50)(?:\s*(?:ultra))?\b', 'Motorola Razr model supports Android 12+'),

    # Xiaomi / Redmi / Poco families commonly represented in AcurastBot and officially Android-12-capable.
    (r'\bxiaomi\s+(?:mi\s*)?(?:10|10t|11|11t|12|12t|13|13t|14|15)(?:\s*(?:lite|pro|ultra))?\b', 'Xiaomi flagship family supports Android 12+'),
    (r'\bxiaomi\s+redmi\s+note\s*(?:10|11|12|13|14)(?:\s*(?:pro|pro\s*\+|pro\+|plus))?\b', 'Redmi Note family supports Android 12+'),
    (r'\bxiaomi\s+redmi\s+(?:10|11|12|13|14)(?:\s*[a-z0-9]+)?\b', 'Redmi model supports Android 12+'),
    (r'\bpoco\s+(?:f3|f4|f5|f6|x3\s*pro|x4|x5|x6|m4|m5|m6)(?:\s*(?:pro|gt))?\b', 'Poco model supports Android 12+'),

    # Other modern Android families searched by the discovery layer.
    (r'\bnothing\s+phone\s*\(?[1-9][a-z]?\)?\b', 'Nothing Phone supports Android 12+'),
    (r'\basus\s+rog\s+phone\s*(?:5|6|7|8|9)\b', 'ASUS ROG Phone model supports Android 12+'),
    (r'\bsony\s+xperia\s+(?:1|5|10)\s*(?:ii|iii|iv|v|vi)\b', 'Sony Xperia generation supports Android 12+'),
    (r'\boppo\s+(?:find\s+x[3-9]|reno\s*[6-9]|reno\s*1[0-9])(?:\s*(?:pro|lite|neo))?\b', 'OPPO model supports Android 12+'),
    (r'\brealme\s+(?:gt|gt\s*neo|[89]|1[0-9])(?:\s*(?:pro|plus|5g|master))?\b', 'Realme model supports Android 12+'),
    (r'\bhonor\s+(?:50|60|70|80|90|100|200|magic\s*[4-9])(?:\s*(?:pro|lite))?\b', 'Honor model supports Android 12+'),
]

INCOMPATIBLE_STATE_RE=re.compile(
    r'\b(rooted|rootet|magisk|lineage\s*os|lineageos|custom\s*rom|bootloader\s*(?:unlocked|oplåst)|oplåst\s+bootloader)\b',
    re.I,
)


def get_json(url:str)->Any:
    r=requests.get(url,timeout=30,headers={'User-Agent':'Mozilla/5.0'}); r.raise_for_status(); return r.json()


def norm(s:str)->str:
    return re.sub(r'[^a-z0-9]+',' ',(s or '').lower()).strip()


def num_gb(v:Any)->int|None:
    if v is None:return None
    m=re.search(r'(\d+)',str(v)); return int(m.group(1)) if m else None


def title_capacities(title:str)->tuple[int|None,int|None]:
    vals=[int(x) for x in re.findall(r'(\d{1,4})\s*gb',title.lower())]
    ram=next((x for x in vals if x in (4,6,8,10,12,16,18,24)),None)
    storage=next((x for x in vals if x>=64),None)
    return ram,storage


def round25(v:float)->int:
    return max(25,int(round(v/25.0)*25))


def core_compatibility(model:str,title:str='',description:str='')->tuple[bool,str]:
    text=f'{model} {title} {description}'
    if INCOMPATIBLE_STATE_RE.search(text):
        return False,'listing indicates rooted/custom-ROM/unlocked-bootloader state'
    nm=norm(model)
    for pattern,reason in CORE_ANDROID12_RULES:
        if re.search(pattern,nm,re.I):
            return True,reason
    return False,f'Android {CORE_MIN_ANDROID}+ compatibility not verified by conservative Core allowlist'


def exact_device(devices:list[dict[str,Any]],label:str)->dict[str,Any]|None:
    nl=norm(label)
    hits=[]
    for d in devices:
        full=norm(f"{d.get('company','')} {d.get('model','')}")
        model=norm(d.get('model',''))
        if nl==full or nl==model:
            hits.append(d)
    return hits[0] if len(hits)==1 else None


def choose_config(device:dict[str,Any],title:str,stats_by_cfg:dict[int,dict[str,Any]]):
    wanted_ram,wanted_storage=title_capacities(title)
    opts=[]
    for c in device.get('configurations') or []:
        cid=c.get('id'); st=stats_by_cfg.get(int(cid)) if cid is not None else None
        if not st: continue
        cr=num_gb(c.get('ram')); cs=num_gb(c.get('storage'))
        penalty=0.0
        if wanted_ram is not None: penalty+=abs((cr or wanted_ram)-wanted_ram)*10
        if wanted_storage is not None: penalty+=abs((cs or wanted_storage)-wanted_storage)/32
        count=int(st.get('processorCount') or 0)
        penalty-=min(count,20)*0.05
        opts.append((penalty,-count,c,st))
    if not opts:return None
    _,_,c,st=min(opts,key=lambda x:(x[0],x[1])); return c,st


def rewards(st:dict[str,Any]):
    def f(k):
        try:return float(st[k])
        except Exception:return None
    med=f('expectedRewardMedian'); avg=f('expectedRewardAvg'); lo=f('expectedRewardMin'); hi=f('expectedRewardMax')
    base=med if med is not None else avg
    if base is None:return None
    base*=0.01; lo=(lo if lo is not None else base/0.01)*0.01; hi=(hi if hi is not None else base/0.01)*0.01
    count=max(1,int(st.get('processorCount') or 1))
    spread=max(0.0,hi-lo)
    spread_ratio=spread/base if base>0 else 1.0
    sample_factor=min(1.0,0.70+0.10*math.log2(count+1))
    spread_factor=max(0.70,1.0-min(spread_ratio,1.0)*0.20)
    confidence_factor=sample_factor*spread_factor
    conservative=max(lo,base*0.70)*confidence_factor
    confidence='HIGH' if count>=10 and spread_ratio<=0.25 else ('MEDIUM' if count>=3 and spread_ratio<=0.60 else 'LOW')
    return {'low':lo,'base':base,'high':hi,'conservative':conservative,'count':count,'spread_ratio':spread_ratio,'confidence_factor':confidence_factor,'confidence':confidence}


def percentile(values:list[float],p:float)->float:
    if not values:return 0.0
    xs=sorted(values)
    if len(xs)==1:return xs[0]
    pos=(len(xs)-1)*p; lo=math.floor(pos); hi=math.ceil(pos)
    if lo==hi:return xs[lo]
    return xs[lo]+(xs[hi]-xs[lo])*(pos-lo)


def main():
    src=json.loads(INPUT.read_text(encoding='utf-8'))
    if not src.get('gate_passed'): raise SystemExit('PRICE DATA GATE FAILED upstream')
    devices=get_json(BOT_BASE+'/devices/with-counts')
    stats=get_json(BOT_BASE+'/devices/pool-statistics')
    stats_by_cfg={int(s['deviceConfigurationId']):s for s in stats if s.get('deviceConfigurationId') is not None}

    valued=[]; unsupported=[]; core_incompatible=[]
    for row in src.get('ranked_by_verified_ask',[]):
        model=row.get('model') or ''
        core_ok,core_reason=core_compatibility(model,row.get('title',''),row.get('description',''))
        if not core_ok:
            core_incompatible.append({'listing_id':row.get('listing_id'),'model':model,'url':row.get('url'),'reason':core_reason})
            continue
        d=exact_device(devices,model)
        if not d:
            unsupported.append({'listing_id':row.get('listing_id'),'model':model,'reason':'no unique exact AcurastBot device match'}); continue
        picked=choose_config(d,row.get('title',''),stats_by_cfg)
        if not picked:
            unsupported.append({'listing_id':row.get('listing_id'),'model':model,'reason':'no AcurastBot configuration stats'}); continue
        cfg,st=picked; rw=rewards(st)
        if not rw:
            unsupported.append({'listing_id':row.get('listing_id'),'model':model,'reason':'no expectedReward stats'}); continue
        ask=int(row.get('ask_t2') or row.get('ask_t1'))
        acu_month=rw['base']*EPOCHS_MONTH
        conservative_month=rw['conservative']*EPOCHS_MONTH
        aae=acu_month/ask if ask else 0.0
        conservative_aae=conservative_month/ask if ask else 0.0
        valued.append({'listing_id':row['listing_id'],'url':row['url'],'title':row['title'],'model':model,'ask':ask,
            'core_android_min':CORE_MIN_ANDROID,'core_compatibility':True,'core_compatibility_reason':core_reason,
            'acurastbot_device':f"{d.get('company')} {d.get('model')}",'configuration_id':cfg.get('id'),'ram':cfg.get('ram'),'storage':cfg.get('storage'),
            'processor_count':rw['count'],'confidence':rw['confidence'],'confidence_factor':rw['confidence_factor'],'spread_ratio':rw['spread_ratio'],
            'acu_epoch_low':rw['low'],'acu_epoch_base':rw['base'],'acu_epoch_high':rw['high'],'acu_month_base':acu_month,'acu_month_conservative':conservative_month,
            'aae_ask':aae,'conservative_aae_ask':conservative_aae})

    if not valued: raise SystemExit('ACURAST CORE DATA GATE FAILED — no Android 12+ valuatable live phones')

    market_aae=[x['conservative_aae_ask'] for x in valued if x['conservative_aae_ask']>0]
    target_hurdle=percentile(market_aae,0.75)
    hard_hurdle=percentile(market_aae,0.50)
    start_hurdle=target_hurdle*1.25
    for x in valued:
        cm=x['acu_month_conservative']
        x['start_bid']=round25(cm/start_hurdle) if start_hurdle>0 else 25
        x['target']=round25(cm/target_hurdle) if target_hurdle>0 else x['ask']
        x['hard_max']=round25(cm/hard_hurdle) if hard_hurdle>0 else x['target']
        x['aae_at_target']=cm/x['target'] if x['target'] else 0
        if x['ask']<=x['target']: x['decision']='STRONG BID'
        elif x['ask']<=x['hard_max']: x['decision']='BID'
        else: x['decision']='LOW OFFER / NEGOTIATE'
        x['opportunity_score']=100*(x['conservative_aae_ask']/hard_hurdle) if hard_hurdle>0 else 0

    valued.sort(key=lambda x:(-x['conservative_aae_ask'],-x['confidence_factor'],x['ask']))
    out={'generated_at':datetime.now(timezone.utc).isoformat(),'valuation_gate':True,
         'core_gate':{'minimum_android':CORE_MIN_ANDROID,'mode':'hard fail-closed allowlist','excluded_count':len(core_incompatible)},
         'method':'market-wide AcurastBot expected reward + verified DBA ASK + hard Android 12 Core compatibility gate; conservative AAE ranking; no farm calibration; no ACU spot-price dependence',
         'hurdles':{'start_conservative_aae':start_hurdle,'target_conservative_aae_p75':target_hurdle,'hard_max_conservative_aae_p50':hard_hurdle},
         'dba_counts':src.get('counts'),'ranked':valued,'core_incompatible':core_incompatible,'unsupported':unsupported}
    OUTPUT.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')

    lines=['# Acurast DBA Profitability Hunter','',f"Generated: {out['generated_at']}",'',
        'DBA data gate: **PASS** — structured discovery + same-listing T1 + final T2 refetch.',
        f'Acurast Core gate: **PASS** — only verified Android {CORE_MIN_ANDROID}+ model families may enter ranking; unknown compatibility is excluded.',
        f'Core-incompatible/unverified exclusions: **{len(core_incompatible)}**.',
        'AcurastBot data gate: **PASS** — dynamic market-wide device/config matching.', '',
        '> Rangeringen bruger **konservativ AAE = confidence-adjusteret forventet ACU pr. måned pr. DKK**. Din nuværende farm og ACU spotpris indgår ikke i rangering eller budgrænser.', '',
        f"Target-hurdle (P75): {target_hurdle:.6f} konservativ ACU/md/DKK | Hard-max hurdle (P50): {hard_hurdle:.6f}",'',
        '| # | Model | ASK | Android gate | ACU/md base | ACU/md konservativ | Conf. | n | AAE konservativ | Score | Start | Target | Hard max | Beslutning | Link |',
        '|---:|---|---:|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---|---|']
    for i,x in enumerate(valued,1):
        lines.append(f"| {i} | {x['model']} | {x['ask']} | {CORE_MIN_ANDROID}+ PASS | {x['acu_month_base']:.2f} | {x['acu_month_conservative']:.2f} | {x['confidence']} | {x['processor_count']} | {x['conservative_aae_ask']:.5f} | {x['opportunity_score']:.0f} | {x['start_bid']} | {x['target']} | {x['hard_max']} | {x['decision']} | [DBA]({x['url']}) |")
    lines+=['','## Bedste muligheder nu','']
    for x in valued[:12]:
        lines.append(f"- **{x['model']}** — ASK {x['ask']} kr. — Android {CORE_MIN_ANDROID}+ PASS — score {x['opportunity_score']:.0f} — {x['confidence']} confidence (n={x['processor_count']}) — start {x['start_bid']} / target {x['target']} / max {x['hard_max']} — **{x['decision']}** — [DBA]({x['url']})")
    if core_incompatible:
        lines+=['','## Ekskluderet af Acurast Core Android-gate','']
        for x in core_incompatible[:30]:
            url=x.get('url') or ''
            link=f" — [DBA]({url})" if url else ''
            lines.append(f"- {x.get('model') or 'Ukendt model'} — {x['reason']}{link}")
    REPORT.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({'valuation_gate':True,'core_min_android':CORE_MIN_ANDROID,'core_excluded':len(core_incompatible),'ranked':len(valued),'unsupported':len(unsupported),'target_hurdle':target_hurdle,'hard_hurdle':hard_hurdle,'top':[{k:x[k] for k in ('listing_id','model','ask','conservative_aae_ask','opportunity_score','start_bid','target','hard_max','decision','url')} for x in valued[:10]]},ensure_ascii=False,indent=2))

if __name__=='__main__': main()
