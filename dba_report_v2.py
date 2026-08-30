from __future__ import annotations

import json, re, time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import requests

BASE='https://www.dba.dk'
SEARCH_API=BASE+'/recommerce/forsale/search/api/search/SEARCH_ID_BAP_COMMON'
ITEM_URL=BASE+'/recommerce/forsale/item/{id}'
REGRESSION_ID='24247594'
HEADERS={'User-Agent':'Mozilla/5.0','Accept-Language':'da-DK,da;q=0.9','Accept':'application/json,text/html;q=0.9,*/*;q=0.8'}
TIMEOUT=25
QUERIES=['gaming pc','gamer pc','gaming computer','stationær gaming','rtx 3060 ti pc','rtx 3070 pc','rtx 3070 ti pc','rtx 3080 pc','rtx 2080 ti pc','rtx 4060 pc','rtx 4060 ti pc','rx 6700 xt pc','rx 6750 xt pc','rx 6800 pc','omen gaming','legion gaming pc','acer nitro pc','predator gaming pc','sharkgaming','dutzo gaming','mm vision gamer','skal væk gaming pc']

GPU_RULES=[
(r'\brtx\s*4090\b','RTX 4090',130),(r'\brtx\s*4080(?:\s*super)?\b','RTX 4080',115),(r'\brtx\s*4070\s*ti(?:\s*super)?\b','RTX 4070 Ti',105),(r'\brtx\s*4070(?:\s*super)?\b','RTX 4070',92),(r'\brtx\s*4060\s*ti\b','RTX 4060 Ti',72),(r'\brtx\s*4060\b','RTX 4060',60),(r'\brtx\s*3090\s*ti\b','RTX 3090 Ti',105),(r'\brtx\s*3090\b','RTX 3090',100),(r'\brtx\s*3080\s*ti\b','RTX 3080 Ti',96),(r'\brtx\s*3080\b','RTX 3080',90),(r'\brtx\s*3070\s*ti\b','RTX 3070 Ti',79),(r'\brtx\s*3070\b','RTX 3070',73),(r'\brtx\s*3060\s*ti\b','RTX 3060 Ti',66),(r'\brtx\s*3060\b','RTX 3060',54),(r'\brtx\s*2080\s*ti\b','RTX 2080 Ti',73),(r'\brtx\s*2080\s*super\b','RTX 2080 Super',65),(r'\brtx\s*2080\b','RTX 2080',61),(r'\brtx\s*2070\s*super\b','RTX 2070 Super',57),(r'\brtx\s*2070\b','RTX 2070',52),(r'\brtx\s*2060\s*super\b','RTX 2060 Super',50),(r'\brtx\s*2060\b','RTX 2060',45),(r'\bgtx\s*1080\s*ti\b','GTX 1080 Ti',60),(r'\bgtx\s*1080\b','GTX 1080',50),(r'\brx\s*7900\s*xtx\b','RX 7900 XTX',120),(r'\brx\s*7900\s*xt\b','RX 7900 XT',110),(r'\brx\s*7800\s*xt\b','RX 7800 XT',98),(r'\brx\s*7700\s*xt\b','RX 7700 XT',86),(r'\brx\s*7600\b','RX 7600',59),(r'\brx\s*6950\s*xt\b','RX 6950 XT',98),(r'\brx\s*6900\s*xt\b','RX 6900 XT',94),(r'\brx\s*6800\s*xt\b','RX 6800 XT',90),(r'\brx\s*6800\b','RX 6800',84),(r'\brx\s*6750\s*xt\b','RX 6750 XT',72),(r'\brx\s*6700\s*xt\b','RX 6700 XT',68),(r'\brx\s*6700\b','RX 6700',62),(r'\brx\s*6650\s*xt\b','RX 6650 XT',54),(r'\brx\s*6600\s*xt\b','RX 6600 XT',51),(r'\brx\s*5700\s*xt\b','RX 5700 XT',55)]
CPU_RULES=[
(r'\b9800x3d\b','Ryzen 7 9800X3D',135),(r'\b7800x3d\b','Ryzen 7 7800X3D',125),(r'\b5800x3d\b','Ryzen 7 5800X3D',100),(r'\b5700x3d\b','Ryzen 7 5700X3D',96),(r'\b5700x\b','Ryzen 7 5700X',82),(r'\b5600x\b','Ryzen 5 5600X',79),(r'\b5600g\b','Ryzen 5 5600G',68),(r'\b5600\b','Ryzen 5 5600',76),(r'\b3600x\b','Ryzen 5 3600X',59),(r'\b3600\b','Ryzen 5 3600',56),(r'\bi5[- ]?14600k[f]?\b','Core i5-14600K',112),(r'\bi5[- ]?13600k[f]?\b','Core i5-13600K',105),(r'\bi5[- ]?12600k[f]?\b','Core i5-12600K',91),(r'\bi5[- ]?12400f?\b','Core i5-12400',81),(r'\bi5[- ]?12100f?\b','Core i5-12100',72),(r'\bi5[- ]?11400f?\b','Core i5-11400',70),(r'\bi5[- ]?10400f?\b','Core i5-10400',65),(r'\bi5[- ]?9600k[f]?\b','Core i5-9600K',59),(r'\bi5[- ]?8600k\b','Core i5-8600K',53),(r'\bi9[- ]?10900k?\b','Core i9-10900',79),(r'\bi9[- ]?9900k[f]?\b','Core i9-9900K',76),(r'\bi7[- ]?12700k?\b','Core i7-12700',98),(r'\bi7[- ]?11700k?\b','Core i7-11700',79),(r'\bi7[- ]?10700k?\b','Core i7-10700',72),(r'\bi7[- ]?9700k?\b','Core i7-9700',67),(r'\bi7[- ]?8700k?\b','Core i7-8700',61)]

@dataclass
class Candidate:
    listing_id:str; url:str; title:str; ask_t0:int; ask_t1:int; disposed:bool; trade_type:str|None; gpu:str; gpu_score:int; cpu:str; cpu_score:int; performance_class:str; source_queries:list[str]

def amount(v:Any)->int|None:
    if isinstance(v,(int,float)): return int(v)
    if isinstance(v,dict):
        for k in ('amount','value','price'):
            if isinstance(v.get(k),(int,float)): return int(v[k])
    if isinstance(v,str):
        s=re.sub(r'[^0-9]','',v); return int(s) if s else None
    return None

def match(text:str,rules):
    for pat,label,score in rules:
        if re.search(pat,text,re.I): return label,score
    return 'Ukendt',0

def preferred_match(title:str,desc:str,rules):
    # Title is seller's concise configuration claim; description may mention alternatives/upgrades.
    m=match(title,rules)
    return m if m[1] else match(desc,rules)

def perf(gs:int,cs:int)->str:
    if gs<50 or cs<50:return 'UNDER MINIMUM'
    if gs>=90 and cs>=76:return 'OVERKILL'
    if gs>=65 and cs>=60:return 'SWEET SPOT'
    return 'ACCEPTABLE'

def getj(s,url,params=None):
    r=s.get(url,params=params,headers=HEADERS,timeout=TIMEOUT); r.raise_for_status(); return r.json()

def main():
    s=requests.Session()
    reg=getj(s,ITEM_URL.format(id=REGRESSION_ID)).get('itemData') or {}
    regp=amount(reg.get('price')); regok=bool(reg.get('title') and regp==4399 and not bool(reg.get('disposed')))
    if not regok: raise SystemExit(f'PRICE DATA GATE FAILED regression price={regp} disposed={reg.get("disposed")}')
    found={}
    for q in QUERIES:
        try: docs=(getj(s,SEARCH_API,{'q':q,'sort':'PRICE_ASC'}).get('docs') or [])
        except Exception as e: print('search failed',q,e); continue
        for d in docs:
            lid=str(d.get('id') or d.get('listingId') or d.get('itemId') or ''); title=str(d.get('heading') or d.get('title') or ''); p=amount(d.get('price'))
            if not lid or not title or p is None: continue
            row=found.setdefault(lid,{'id':lid,'title':title,'price':p,'queries':[]}); row['queries'].append(q); row['price']=min(row['price'],p)
        time.sleep(.05)
    prom=[]
    for r in found.values():
        g,gs=match(r['title'],GPU_RULES)
        if gs>=50 and 500<=r['price']<=15000: prom.append((r,gs))
    prom=sorted(prom,key=lambda x:(x[0]['price'],-x[1]))[:100]
    ranked=[]; rejected=[]
    for r,_ in prom:
        try:
            item=(getj(s,ITEM_URL.format(id=r['id'])).get('itemData') or {}); p1=amount(item.get('price')); disposed=bool(item.get('disposed'))
            if p1 is None or disposed: rejected.append({'id':r['id'],'reason':'missing price/disposed'}); continue
            title=str(item.get('title') or r['title']); desc=str(item.get('description') or '')
            gpu,gs=preferred_match(title,desc,GPU_RULES); cpu,cs=preferred_match(title,desc,CPU_RULES)
            if not gs or not cs: rejected.append({'id':r['id'],'reason':'unparsed specs','title':title}); continue
            trade=item.get('tradeType') or item.get('adViewTypeLabel')
            ranked.append(Candidate(r['id'],ITEM_URL.format(id=r['id']),title,int(r['price']),int(p1),disposed,str(trade) if trade else None,gpu,gs,cpu,cs,perf(gs,cs),sorted(set(r['queries']))))
        except Exception as e: rejected.append({'id':r['id'],'reason':str(e)})
        time.sleep(.05)
    ranked.sort(key=lambda c:(0 if c.performance_class in ('SWEET SPOT','OVERKILL') else 1,c.ask_t1,-c.gpu_score,-c.cpu_score))
    out={'generated_at':datetime.now(timezone.utc).isoformat(),'gate_passed':True,'regression_gate':{'ok':True,'listing_id':REGRESSION_ID,'price':regp,'disposed':False,'title':reg.get('title')},'counts':{'t0_unique':len(found),'t0_promising':len(prom),'t1_verified_specs':len(ranked),'rejected':len(rejected)},'ranked':[asdict(x) for x in ranked],'rejected':rejected}
    Path('results').mkdir(exist_ok=True); Path('results/latest_v2.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# DBA WoW-PC verified price report v2','',f"Generated: {out['generated_at']}",'',f"Regression 24247594: **PASS** — {regp} DKK — disposed=False",'',f"Structured T0 records: {len(found)}",f"T1 verified ranked records: {len(ranked)}",'', '| Rank | ASK | Class | GPU | CPU | Listing |','|---:|---:|---|---|---|---|']
    for i,c in enumerate(ranked[:25],1): lines.append(f'| {i} | {c.ask_t1} kr. | {c.performance_class} | {c.gpu} | {c.cpu} | [{c.title}]({c.url}) |')
    Path('results/report_v2.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({'gate':True,'t0':len(found),'ranked':len(ranked),'top':[asdict(x) for x in ranked[:5]]},ensure_ascii=False,indent=2))
if __name__=='__main__': main()
