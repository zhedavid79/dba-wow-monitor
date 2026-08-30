from __future__ import annotations

import json, re, statistics, time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import requests

BASE='https://www.dba.dk'
SEARCH_API=BASE+'/recommerce/forsale/search/api/search/SEARCH_ID_BAP_COMMON'
ITEM_URL=BASE+'/recommerce/forsale/item/{id}'
REGRESSION_ID='24247594'
REGRESSION_PRICE=4399
HEADERS={'User-Agent':'Mozilla/5.0','Accept-Language':'da-DK,da;q=0.9','Accept':'application/json,text/html;q=0.9,*/*;q=0.8'}
TIMEOUT=25

QUERIES=[
 'samsung s10','samsung s20','samsung s20 ultra','samsung s21','samsung s21 ultra','samsung s22','samsung s22 ultra','samsung s23','samsung s23 fe','samsung z flip',
 'oneplus nord','oneplus nord 2','oneplus nord 2t','oneplus nord 3','oneplus 8','oneplus 9','oneplus 9 pro','oneplus 10','oneplus 10 pro','oneplus 11',
 'xiaomi 11','xiaomi 12','xiaomi 12 pro','poco f3','poco f4','poco f5','motorola edge 30','motorola edge 40','pixel 6','pixel 7','pixel 8',
 'defekt samsung','defekt oneplus','defekt xiaomi','defekt motorola','defekt pixel','defekt skærm android','revnet skærm samsung','repareres android','reservedele android','burn in samsung'
]

MODEL_RULES=[
 (r'galaxy\s+s10\b','Samsung Galaxy S10'),(r'galaxy\s+s20\s*ultra','Samsung Galaxy S20 Ultra'),(r'galaxy\s+s20\b','Samsung Galaxy S20'),
 (r'galaxy\s+s21\s*ultra','Samsung Galaxy S21 Ultra'),(r'galaxy\s+s21\b','Samsung Galaxy S21'),(r'galaxy\s+s22\s*ultra','Samsung Galaxy S22 Ultra'),
 (r'galaxy\s+s22\b','Samsung Galaxy S22'),(r'galaxy\s+s23\s*fe','Samsung Galaxy S23 FE'),(r'galaxy\s+s23\b','Samsung Galaxy S23'),
 (r'(?:galaxy\s+)?z\s*flip\s*4','Samsung Galaxy Z Flip4'),(r'(?:galaxy\s+)?z\s*flip\s*5','Samsung Galaxy Z Flip5'),
 (r'oneplus\s+nord\s*2t','OnePlus Nord 2T'),(r'oneplus\s+nord\s*3','OnePlus Nord 3'),(r'oneplus\s+nord\s*2\b','OnePlus Nord 2'),
 (r'oneplus\s+9\s*pro','OnePlus 9 Pro'),(r'oneplus\s+9\b','OnePlus 9'),(r'oneplus\s+10\s*pro','OnePlus 10 Pro'),(r'oneplus\s+10\b','OnePlus 10'),(r'oneplus\s+11\b','OnePlus 11'),
 (r'xiaomi\s+12\s*pro','Xiaomi 12 Pro'),(r'xiaomi\s+12\b','Xiaomi 12'),(r'xiaomi\s+11\b','Xiaomi 11'),
 (r'poco\s+f3\b','Poco F3'),(r'poco\s+f4\b','Poco F4'),(r'poco\s+f5\b','Poco F5'),
 (r'motorola\s+edge\s+40\s*neo','Motorola Edge 40 Neo'),(r'motorola\s+edge\s+40\b','Motorola Edge 40'),(r'motorola\s+edge\s+30\b','Motorola Edge 30'),
 (r'(?:google\s+)?pixel\s+6\b','Google Pixel 6'),(r'(?:google\s+)?pixel\s+7\b','Google Pixel 7'),(r'(?:google\s+)?pixel\s+8\b','Google Pixel 8'),
]

def amount(v:Any)->int|None:
    if isinstance(v,(int,float)): return int(v)
    if isinstance(v,dict):
        for k in ('amount','value','price'):
            if isinstance(v.get(k),(int,float)): return int(v[k])
    if isinstance(v,str):
        s=re.sub(r'[^0-9]','',v); return int(s) if s else None
    return None

def model_of(text:str)->str|None:
    for pat,label in MODEL_RULES:
        if re.search(pat,text,re.I): return label
    return None

def getj(s:requests.Session,url:str,params=None):
    r=s.get(url,params=params,headers=HEADERS,timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()

def canonical_id_from_payload(payload:dict[str,Any])->str|None:
    # Bind identity from the same live response envelope, never from a search snippet.
    for obj in (payload.get('jsonLd'), payload.get('meta'), payload.get('itemData')):
        if isinstance(obj,dict):
            for key in ('url','canonical','canonicalUrl','canonical_url','id','listingId','itemId'):
                v=obj.get(key)
                if v is None: continue
                m=re.search(r'/item/(\d+)',str(v))
                if m: return m.group(1)
                if str(v).isdigit(): return str(v)
    # Fallback: recursively inspect only the direct live item response.
    stack=[payload]
    while stack:
        x=stack.pop()
        if isinstance(x,dict):
            for k,v in x.items():
                if k.lower() in ('url','canonicalurl','canonical_url','listingid','itemid'):
                    m=re.search(r'/item/(\d+)',str(v))
                    if m:return m.group(1)
                    if str(v).isdigit() and k.lower()!='url':return str(v)
                if isinstance(v,(dict,list)): stack.append(v)
        elif isinstance(x,list): stack.extend(x[:200])
    return None

def fetch_item(s:requests.Session,lid:str)->dict[str,Any]:
    payload=getj(s,ITEM_URL.format(id=lid))
    item=payload.get('itemData') or {}
    price=amount(item.get('price'))
    title=str(item.get('title') or '').strip()
    disposed=bool(item.get('disposed'))
    bound_id=canonical_id_from_payload(payload)
    identity_ok=(bound_id==lid) if bound_id else False
    return {
      'listing_id':lid,'bound_listing_id':bound_id,'identity_ok':identity_ok,
      'url':ITEM_URL.format(id=lid),'title':title,'price':price,'disposed':disposed,
      'trade_type':item.get('tradeType') or item.get('adViewTypeLabel'),
      'description':str(item.get('description') or ''),
      'location':item.get('location'),'extras':item.get('extras'),'meta':item.get('meta')
    }

def main():
    s=requests.Session(); Path('results').mkdir(exist_ok=True)
    reg=fetch_item(s,REGRESSION_ID)
    regression_ok=bool(reg['identity_ok'] and reg['price']==REGRESSION_PRICE and reg['title'] and not reg['disposed'])
    if not regression_ok:
        out={'generated_at':datetime.now(timezone.utc).isoformat(),'gate_passed':False,'reason':'PRICE DATA GATE FAILED','regression':reg,'expected_price':REGRESSION_PRICE}
        Path('results/acurast_latest.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
        Path('results/acurast_report.md').write_text('# Acurast DBA report\n\n**PRICE DATA GATE FAILED — INGEN VERIFICERET PRISRANGERING**\n',encoding='utf-8')
        raise SystemExit(f"PRICE DATA GATE FAILED regression={reg}")

    found:dict[str,dict[str,Any]]={}; search_errors=[]
    for q in QUERIES:
        try:
            data=getj(s,SEARCH_API,{'q':q,'sort':'PRICE_ASC'}); docs=data.get('docs') or []
            for d in docs:
                lid=str(d.get('id') or d.get('listingId') or d.get('itemId') or '')
                title=str(d.get('heading') or d.get('title') or '').strip(); p=amount(d.get('price'))
                if not lid or not title or p is None: continue
                model=model_of(title)
                if not model: continue
                r=found.setdefault(lid,{'listing_id':lid,'title_t0':title,'ask_t0':p,'model':model,'queries':[]})
                r['queries'].append(q)
        except Exception as e: search_errors.append({'query':q,'error':repr(e)})
        time.sleep(.03)

    verified=[]; excluded=[]
    for r in found.values():
        try:
            t1=fetch_item(s,r['listing_id'])
            model=model_of(t1['title']+' '+t1['description']) or r['model']
            if not t1['identity_ok']: excluded.append({**r,'reason':'listing identity mismatch','t1':t1}); continue
            if t1['disposed']: excluded.append({**r,'reason':'disposed/inactive','t1':t1}); continue
            if t1['price'] is None or not t1['title']: excluded.append({**r,'reason':'missing live price/title','t1':t1}); continue
            verified.append({**r,**t1,'model':model,'ask_t1':int(t1['price']),'price_changed':int(t1['price'])!=int(r['ask_t0']),'t1_timestamp':datetime.now(timezone.utc).isoformat()})
        except Exception as e: excluded.append({**r,'reason':f'T1 fetch failed: {e!r}'})
        time.sleep(.03)

    by_model={}
    for r in verified: by_model.setdefault(r['model'],[]).append(r)
    market=[]
    for model,rows in sorted(by_model.items()):
        asks=sorted(r['ask_t1'] for r in rows)
        market.append({'model':model,'n':len(asks),'min_ask':min(asks),'median_ask':statistics.median(asks),'max_ask':max(asks)})

    # Final T2 refetch of top low-price candidates before output.
    preliminary=sorted(verified,key=lambda r:(r['ask_t1'],r['model']))[:30]; final=[]
    for r in preliminary:
        try:
            t2=fetch_item(s,r['listing_id'])
            if not (t2['identity_ok'] and not t2['disposed'] and t2['price'] is not None and t2['title']): continue
            x={**r,'ask_t2':int(t2['price']),'title':t2['title'],'final_timestamp':datetime.now(timezone.utc).isoformat()}
            final.append(x)
        except Exception: pass
        time.sleep(.03)

    out={'generated_at':datetime.now(timezone.utc).isoformat(),'gate_passed':True,
         'regression':{'listing_id':REGRESSION_ID,'price':reg['price'],'identity_ok':reg['identity_ok'],'disposed':reg['disposed'],'title':reg['title']},
         'counts':{'queries':len(QUERIES),'search_errors':len(search_errors),'t0_unique':len(found),'t1_verified_active':len(verified),'excluded':len(excluded),'final_refetched':len(final)},
         'market':market,'ranked_by_verified_ask':final,'excluded':excluded,'search_errors':search_errors}
    Path('results/acurast_latest.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# Acurast DBA verified price report','',f"Generated: {out['generated_at']}",'',f"Regression {REGRESSION_ID}: **PASS** — {reg['price']} DKK — identity={reg['identity_ok']} — disposed={reg['disposed']}",'',f"T0 unique: {len(found)} | T1 verified active: {len(verified)} | Excluded: {len(excluded)} | Final refetched: {len(final)}",'', '## Verified market','', '| Model | n | Min ASK | Median ASK | Max ASK |','|---|---:|---:|---:|---:|']
    for m in market: lines.append(f"| {m['model']} | {m['n']} | {m['min_ask']} kr. | {m['median_ask']} kr. | {m['max_ask']} kr. |")
    lines += ['', '## Lowest T1/T2 verified active listings','', '| Rank | Model | ASK | Listing |','|---:|---|---:|---|']
    for i,r in enumerate(final,1): lines.append(f"| {i} | {r['model']} | {r['ask_t2']} kr. | [{r['title']}]({r['url']}) |")
    Path('results/acurast_report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({'gate':True,'regression_price':reg['price'],'t0':len(found),'verified':len(verified),'final':len(final),'top':[{k:r[k] for k in ('listing_id','model','ask_t2','url')} for r in final[:10]]},ensure_ascii=False,indent=2))

if __name__=='__main__': main()
