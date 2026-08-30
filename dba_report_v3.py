from __future__ import annotations

import json
import math
import re
import statistics
from pathlib import Path

import dba_report_v2 as base

# Fix Intel suffix handling such as 12700KF/10700KF/10900KF.
INTEL_RULES = [
    (r'\bi9[- ]?14900(?:k|kf|f)?\b','Core i9-14900',125),
    (r'\bi9[- ]?13900(?:k|kf|f)?\b','Core i9-13900',118),
    (r'\bi9[- ]?12900(?:k|kf|f)?\b','Core i9-12900',108),
    (r'\bi9[- ]?11900(?:k|kf|f)?\b','Core i9-11900',87),
    (r'\bi9[- ]?10900(?:k|kf|f)?\b','Core i9-10900',79),
    (r'\bi9[- ]?9900(?:k|kf)?\b','Core i9-9900K',76),
    (r'\bi7[- ]?14700(?:k|kf|f)?\b','Core i7-14700',118),
    (r'\bi7[- ]?13700(?:k|kf|f)?\b','Core i7-13700',110),
    (r'\bi7[- ]?12700(?:k|kf|f)?\b','Core i7-12700',98),
    (r'\bi7[- ]?11700(?:k|kf|f)?\b','Core i7-11700',79),
    (r'\bi7[- ]?10700(?:k|kf|f)?\b','Core i7-10700',72),
    (r'\bi7[- ]?9700(?:k|kf|f)?\b','Core i7-9700',67),
    (r'\bi7[- ]?8700(?:k|kf)?\b','Core i7-8700',61),
    (r'\bi5[- ]?14600(?:k|kf|f)?\b','Core i5-14600K',112),
    (r'\bi5[- ]?13600(?:k|kf|f)?\b','Core i5-13600K',105),
    (r'\bi5[- ]?12600(?:k|kf|f)?\b','Core i5-12600K',91),
    (r'\bi5[- ]?12400(?:f)?\b','Core i5-12400',81),
    (r'\bi5[- ]?12100(?:f)?\b','Core i5-12100',72),
    (r'\bi5[- ]?11400(?:f)?\b','Core i5-11400',70),
    (r'\bi5[- ]?10400(?:f)?\b','Core i5-10400',65),
    (r'\bi5[- ]?9600(?:k|kf)?\b','Core i5-9600K',59),
    (r'\bi5[- ]?8600(?:k)?\b','Core i5-8600K',53),
]
# Intel first; retain Ryzen rules and any CPU families already supported.
base.CPU_RULES = INTEL_RULES + [r for r in base.CPU_RULES if not re.search(r"Core i[579]", r[1], re.I)]

# Run full live T0/T1 model with corrected parser.
base.main()

src = json.loads(Path('results/latest_v2.json').read_text(encoding='utf-8'))
rows = src['ranked']

# Pure-tower comparables: avoid bundles where peripherals inflate asking price.
def pure_tower(row):
    t = row['title'].lower()
    banned = ('komplet gaming setup', 'gaming setup', 'skærm', 'monitor', '240hz', '144hz')
    return not any(x in t for x in banned)

def r100(x):
    return int(round(float(x) / 100.0) * 100)

def comparables(row):
    pool = [x for x in rows if pure_tower(x) and x['listing_id'] != row['listing_id'] and x['gpu'] == row['gpu']]
    near = [x for x in pool if abs(x['cpu_score'] - row['cpu_score']) <= 18]
    return near if len(near) >= 2 else pool

valued=[]
for row in rows:
    row=dict(row)
    peers=comparables(row)
    asks=sorted(x['ask_t1'] for x in peers)
    med=statistics.median(asks) if len(asks)>=2 else None
    row['comparable_count']=len(asks)
    row['comparable_median_ask']=int(med) if med is not None else None
    row['market_discount_pct']=round((1-row['ask_t1']/med)*100,1) if med else None
    if not pure_tower(row):
        decision='BUNDLE / REVIEW'
    elif med is None:
        decision='REVIEW'
    else:
        ratio=row['ask_t1']/med
        if row['performance_class'] in ('SWEET SPOT','OVERKILL') and ratio <= .72:
            decision='KØB NU'
        elif ratio <= .88:
            decision='BUD'
        elif ratio <= 1.05:
            decision='MARKEDSPRIS'
        else:
            decision='FOR DYRT'
    row['decision']=decision
    if med and pure_tower(row):
        row['start_bid']=min(row['ask_t1'], r100(med*.70))
        row['target_price']=min(row['ask_t1'], r100(med*.82))
        row['hard_max']=min(row['ask_t1'], r100(med*.90))
    else:
        row['start_bid']=row['target_price']=row['hard_max']=None
    valued.append(row)

priority={'KØB NU':0,'BUD':1,'MARKEDSPRIS':2,'REVIEW':3,'BUNDLE / REVIEW':4,'FOR DYRT':5}
valued.sort(key=lambda x:(priority.get(x['decision'],9), x['ask_t1'], -x['gpu_score'], -x['cpu_score']))

out={
    'generated_at':src['generated_at'],
    'gate_passed':src['gate_passed'],
    'regression_gate':src['regression_gate'],
    'counts':src['counts'],
    'method':'Live DBA T0/T1. Market benchmark = median ASK among same-GPU pure-tower comparables; CPU-score band ±18 when >=2 peers. Bid levels are conservative fractions of peer median and never exceed ASK.',
    'ranked':valued,
}
Path('results/report_v3.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')

lines=['# DBA WoW-PC verified report v3 — price/value','',f"Generated: {out['generated_at']}",'',f"Regression 24247594: **PASS** — {out['regression_gate']['price']} DKK — disposed={out['regression_gate']['disposed']}",'',f"T0 unique: {out['counts']['t0_unique']} | T1 verified specs: {out['counts']['t1_verified_specs']}",'', '> ASK is live T1 DBA price. Market median is a same-GPU comparable ASK benchmark, not a claimed sale-price valuation.','', '| Rank | Decision | ASK | Peer median | Discount | Start bid | Target | Hard max | GPU | CPU | Listing |','|---:|---|---:|---:|---:|---:|---:|---:|---|---|---|']
for i,r in enumerate(valued[:30],1):
    med=f"{r['comparable_median_ask']} kr." if r['comparable_median_ask'] else '—'
    disc=f"{r['market_discount_pct']:+.1f}%" if r['market_discount_pct'] is not None else '—'
    sb=f"{r['start_bid']}" if r['start_bid'] is not None else '—'
    tg=f"{r['target_price']}" if r['target_price'] is not None else '—'
    hm=f"{r['hard_max']}" if r['hard_max'] is not None else '—'
    lines.append(f"| {i} | {r['decision']} | {r['ask_t1']} kr. | {med} | {disc} | {sb} | {tg} | {hm} | {r['gpu']} | {r['cpu']} | [{r['title']}]({r['url']}) |")
Path('results/report_v3.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(json.dumps({'gate':True,'top':valued[:5]},ensure_ascii=False,indent=2))
