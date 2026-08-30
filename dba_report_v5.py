from __future__ import annotations

import json
import re
import statistics
import time
from pathlib import Path

import requests
import dba_report_v2 as base

# Keep the broader CPU parser used by v4.
EXTRA_CPU_RULES = [
    (r'\b9950x3d\b','Ryzen 9 9950X3D',140),(r'\b9900x3d\b','Ryzen 9 9900X3D',136),(r'\b9800x3d\b','Ryzen 7 9800X3D',135),
    (r'\b7950x3d\b','Ryzen 9 7950X3D',132),(r'\b7900x3d\b','Ryzen 9 7900X3D',128),(r'\b7800x3d\b','Ryzen 7 7800X3D',125),
    (r'\b5800x3d\b','Ryzen 7 5800X3D',100),(r'\b5700x3d\b','Ryzen 7 5700X3D',96),
    (r'\b5950x\b','Ryzen 9 5950X',90),(r'\b5900x\b','Ryzen 9 5900X',88),(r'\b5800x\b','Ryzen 7 5800X',84),
    (r'\b5700x\b','Ryzen 7 5700X',82),(r'\b5700g\b','Ryzen 7 5700G',73),(r'\b5600x\b','Ryzen 5 5600X',79),
    (r'\b5600g\b','Ryzen 5 5600G',68),(r'\b5600\b','Ryzen 5 5600',76),(r'\b5500\b','Ryzen 5 5500',65),
    (r'\b3800x\b','Ryzen 7 3800X',63),(r'\b3700x\b','Ryzen 7 3700X',62),(r'\b3600x\b','Ryzen 5 3600X',59),(r'\b3600\b','Ryzen 5 3600',56),
    (r'\bi9[- ]?14900(?:k|kf|f)?\b','Core i9-14900',125),(r'\bi9[- ]?13900(?:k|kf|f)?\b','Core i9-13900',118),
    (r'\bi9[- ]?12900(?:k|kf|f)?\b','Core i9-12900',108),(r'\bi9[- ]?11900(?:k|kf|f)?\b','Core i9-11900',87),
    (r'\bi9[- ]?10900(?:k|kf|f)?\b','Core i9-10900',79),(r'\bi9[- ]?9900(?:k|kf)?\b','Core i9-9900K',76),
    (r'\bi7[- ]?14700(?:k|kf|f)?\b','Core i7-14700',118),(r'\bi7[- ]?13700(?:k|kf|f)?\b','Core i7-13700',110),
    (r'\bi7[- ]?12700(?:k|kf|f)?\b','Core i7-12700',98),(r'\bi7[- ]?11700(?:k|kf|f)?\b','Core i7-11700',79),
    (r'\bi7[- ]?10700(?:k|kf|f)?\b','Core i7-10700',72),(r'\bi7[- ]?9700(?:k|kf|f)?\b','Core i7-9700',67),(r'\bi7[- ]?8700(?:k|kf)?\b','Core i7-8700',61),
    (r'\bi5[- ]?14600(?:k|kf|f)?\b','Core i5-14600K',112),(r'\bi5[- ]?13600(?:k|kf|f)?\b','Core i5-13600K',105),
    (r'\bi5[- ]?12600(?:k|kf|f)?\b','Core i5-12600K',91),(r'\bi5[- ]?12400(?:f)?\b','Core i5-12400',81),
    (r'\bi5[- ]?12100(?:f)?\b','Core i5-12100',72),(r'\bi5[- ]?11400(?:f)?\b','Core i5-11400',70),
    (r'\bi5[- ]?10400(?:f)?\b','Core i5-10400',65),(r'\bi5[- ]?9600(?:k|kf)?\b','Core i5-9600K',59),(r'\bi5[- ]?8600(?:k)?\b','Core i5-8600K',53),
]
base.CPU_RULES = EXTRA_CPU_RULES
base.main()

src = json.loads(Path('results/latest_v2.json').read_text(encoding='utf-8'))
rows = src['ranked']

MAJOR_PATTERNS = (
    'virker ikke','starter ikke','booter ikke','til dele','reservedele','mangler dele',
    'uden gpu','uden grafikkort','uden cpu','uden ram','uden strømforsyning','uden psu',
    'no gpu','damaged','broken','parts only','reparationsobjekt','rep objekt',
    'defekt psu','defekt strømforsyning','defekt bundkort','bundkort defekt','motherboard defekt'
)
MINOR_PATTERNS = (
    'blæser larmer','blæseren larmer','fan larmer','larmer en del','støjende blæser',
    'noisy fan','fan noise','kosmetisk','ridse','ridser','bule','buler'
)
GENERIC_DEFECT = ('defekt','defekte','fejl på','fejl i')
POSITIVE_PATTERNS = ('fungerer fint','virker fint','fungerer perfekt','virker perfekt','100% fungerende','100 % fungerende','uden fejl','fejlfri')
BUNDLE_PATTERNS = ('komplet gaming setup','gaming setup','med skærm','inkl skærm','inkl. skærm','monitor','240hz skærm','144hz skærm')


def matches(text: str, pats: tuple[str, ...]) -> list[str]:
    t=text.lower()
    return [p for p in pats if p in t]


def condition(title: str, desc: str) -> tuple[str,list[str]]:
    t=(title+'\n'+desc).lower()
    major=matches(t,MAJOR_PATTERNS)
    minor=matches(t,MINOR_PATTERNS)
    generic=matches(t,GENERIC_DEFECT)
    positive=matches(t,POSITIVE_PATTERNS)
    if major:
        return 'MAJOR DEFECT', major
    # Known small/localized issues are retained even if generic wording also occurs.
    if minor:
        return 'MINOR ISSUE', sorted(set(minor+generic))
    if generic:
        return 'MAJOR DEFECT', generic
    return 'PASS', positive


def is_bundle(title: str) -> bool:
    return any(p in title.lower() for p in BUNDLE_PATTERNS)

def r100(x): return int(round(float(x)/100.0)*100)

s=requests.Session(); clean=[]; disqualified=[]
for row in rows:
    try:
        item=base.getj(s,base.ITEM_URL.format(id=row['listing_id'])).get('itemData') or {}
        title=str(item.get('title') or row['title']); desc=str(item.get('description') or '')
        p1=base.amount(item.get('price')); disposed=bool(item.get('disposed'))
        if disposed or p1 is None:
            disqualified.append({'listing_id':row['listing_id'],'title':title,'reason':'disposed/missing live price'}); continue
        state,evidence=condition(title,desc)
        if state=='MAJOR DEFECT':
            disqualified.append({'listing_id':row['listing_id'],'title':title,'ask':p1,'reason':'MAJOR DEFECT','matches':evidence}); continue
        r=dict(row); r['title']=title; r['ask_t1']=int(p1); r['bundle']=is_bundle(title)
        r['condition']=state; r['condition_evidence']=evidence; r['quality_gate']='PASS' if state=='PASS' else 'PASS WITH WARNING'
        clean.append(r)
    except Exception as e:
        disqualified.append({'listing_id':row['listing_id'],'title':row.get('title'),'reason':f'quality refetch failed: {e}'})
    time.sleep(.03)

# Minor-issue ads can be ranked, but are not used as clean-market comparables.
def comparables(row):
    pool=[x for x in clean if x['condition']=='PASS' and not x['bundle'] and x['listing_id']!=row['listing_id'] and x['gpu']==row['gpu']]
    near=[x for x in pool if abs(x['cpu_score']-row['cpu_score'])<=12]
    return near if len(near)>=3 else pool

valued=[]
for row in clean:
    r=dict(row); peers=comparables(r); asks=sorted(x['ask_t1'] for x in peers)
    med=statistics.median(asks) if len(asks)>=3 else None
    r['comparable_count']=len(asks); r['peer_median_ask']=int(med) if med is not None else None
    r['discount_pct']=round((1-r['ask_t1']/med)*100,1) if med else None
    if r['bundle']: decision='BUNDLE / REVIEW'
    elif med is None: decision='REVIEW'
    else:
        ratio=r['ask_t1']/med
        if r['performance_class'] in ('SWEET SPOT','OVERKILL') and ratio<=.72: decision='KØB NU'
        elif ratio<=.88: decision='BUD'
        elif ratio<=1.05: decision='MARKEDSPRIS'
        else: decision='FOR DYRT'
    # A minor issue never silently receives an unconditional buy label.
    if r['condition']=='MINOR ISSUE' and decision=='KØB NU': decision='KØB NU / MINOR ISSUE'
    r['decision']=decision
    if med and not r['bundle']:
        r['start_bid']=min(r['ask_t1'],r100(med*.70)); r['target_price']=min(r['ask_t1'],r100(med*.82)); r['hard_max']=min(r['ask_t1'],r100(med*.90))
    else: r['start_bid']=r['target_price']=r['hard_max']=None
    valued.append(r)

priority={'KØB NU':0,'KØB NU / MINOR ISSUE':1,'BUD':2,'MARKEDSPRIS':3,'REVIEW':4,'BUNDLE / REVIEW':5,'FOR DYRT':6}
valued.sort(key=lambda x:(priority.get(x['decision'],9),x['ask_t1'],-x['gpu_score'],-x['cpu_score']))
out={'generated_at':src['generated_at'],'gate_passed':True,'regression_gate':src['regression_gate'],
     'counts':{**src['counts'],'condition_pass':sum(x['condition']=='PASS' for x in clean),'minor_issue':sum(x['condition']=='MINOR ISSUE' for x in clean),'major_disqualified':len(disqualified)},
     'method':'Live DBA T0/T1 + graded live condition refetch. PASS and MINOR ISSUE may rank; MAJOR DEFECT is excluded. Only PASS non-bundles form market comparables.',
     'ranked':valued,'disqualified':disqualified}
Path('results/report_v5.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
lines=['# DBA WoW-PC verified report v5 — graded condition model','',f"Generated: {out['generated_at']}",'',f"Regression 24247594: **PASS** — {out['regression_gate']['price']} DKK",'',f"PASS: {out['counts']['condition_pass']} | MINOR ISSUE: {out['counts']['minor_issue']} | MAJOR/other disqualified: {len(disqualified)}",'', '> MINOR ISSUE remains rankable with an explicit warning. MAJOR DEFECT is excluded. ASK is live T1 price.','', '| Rank | Decision | Condition | ASK | Peer median | Discount | GPU | CPU | Listing |','|---:|---|---|---:|---:|---:|---|---|---|']
for i,r in enumerate(valued[:30],1):
    med=f"{r['peer_median_ask']} kr." if r['peer_median_ask'] else '—'; disc=f"{r['discount_pct']:+.1f}%" if r['discount_pct'] is not None else '—'
    lines.append(f"| {i} | {r['decision']} | {r['condition']} | {r['ask_t1']} kr. | {med} | {disc} | {r['gpu']} | {r['cpu']} | [{r['title']}]({r['url']}) |")
lines += ['', '## Major disqualifications', '']
for d in disqualified[:30]: lines.append(f"- {d.get('listing_id')}: {d.get('title')} — {d.get('reason')}")
Path('results/report_v5.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(json.dumps({'gate':True,'pass':out['counts']['condition_pass'],'minor':out['counts']['minor_issue'],'disqualified':len(disqualified),'top':valued[:5]},ensure_ascii=False,indent=2))
