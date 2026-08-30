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
QUERIES=['samsung s10','samsung s20','samsung s20 ultra','samsung s21','samsung s21 ultra','samsung s22','samsung s22 ultra','samsung s23','samsung s23 fe','samsung z flip','oneplus nord','oneplus nord 2','oneplus nord 2t','oneplus nord 3','oneplus 8','oneplus 9','oneplus 9 pro','oneplus 10','oneplus 10 pro','oneplus 11','xiaomi 11','xiaomi 12','xiaomi 12 pro','poco f3','poco f4','poco f5','motorola edge 30','motorola edge 40','pixel 6','pixel 7','pixel 8','defekt samsung','defekt oneplus','defekt xiaomi','defekt motorola','defekt pixel','defekt skærm android','revnet skærm samsung','repareres android','reservedele android','burn in samsung']
MODEL_RULES=[(r'galaxy\s+s10\b','Samsung Galaxy S10'),(r'galaxy\s+s20\s*ultra','Samsung Galaxy S20 Ultra'),(r'galaxy\s+s20\b(?!\s*(?:fe|\+|plus))','Samsung Galaxy S20'),(r'galaxy\s+s21\s*ultra','Samsung Galaxy S21 Ultra'),(r'galaxy\s+s21\b(?!\s*(?:fe|\+|plus))','Samsung Galaxy S21'),(r'galaxy\s+s22\s*ultra','Samsung Galaxy S22 Ultra'),(r'galaxy\s+s22\b(?!\s*(?:\+|plus))','Samsung Galaxy S22'),(r'galaxy\s+s23\s*fe','Samsung Galaxy S23 FE'),(r'galaxy\s+s23\b(?!\s*(?:fe|\+|plus))','Samsung Galaxy S23'),(r'(?:galaxy\s+)?z\s*flip\s*4','Samsung Galaxy Z Flip4'),(r'(?:galaxy\s+)?z\s*flip\s*5','Samsung Galaxy Z Flip5'),(r'oneplus\s+nord\s*2t','OnePlus Nord 2T'),(r'oneplus\s+nord\s*3','OnePlus Nord 3'),(r'oneplus\s+nord\s*2\b','OnePlus Nord 2'),(r'oneplus\s+9\s*pro','OnePlus 9 Pro'),(r'oneplus\s+9\b','OnePlus 9'),(r'oneplus\s+10\s*pro','OnePlus 10 Pro'),(r'oneplus\s+10\b','OnePlus 10'),(r'oneplus\s+11\b','OnePlus 11'),(r'xiaomi\s+12\s*pro','Xiaomi 12 Pro'),(r'xiaomi\s+12\b','Xiaomi 12'),(r'xiaomi\s+11\b','Xiaomi 11'),(r'poco\s+f3\b','Poco F3'),(r'poco\s+f4\b','Poco F4'),(r'poco\s+f5\b','Poco F5'),(r'motorola\s+edge\s+40\s*neo','Motorola Edge 40 Neo'),(r'motorola\s+edge\s+40\b','Motorola Edge 40'),(r'motorola\s+edge\s+30\b','Motorola Edge 30'),(r'(?:google\s+)?pixel\s+6\b','Google Pixel 6'),(r'(?:google\s+)?pixel\s+7\b','Google Pixel 7'),(r'(?:google\s+)?pixel\s+8\b','Google Pixel 8')]
ACCESSORY_RE=re.compile(r'(mobilcover|telefoncover|cover|covers|case|etui|skærmbeskytt|screenor|panserglas|beskyttelsesglas|privacy.?filter|kabel|ledning|oplader|charger|adapter|holder|mount|taske|pung|stativ|reservedel|reservedele|batteri\b|display\b|lcd\b|oled\b|skærm\s+til|kamera.?modul|bagglas|ramme\s+til)',re.I)
COMPLETE_PHONE_RE=re.compile(r'\b(telefon|mobiltelefon|smartphone)\b',re.I)
FUNCTION_RE=re.compile(r'\b(virker|fungerer|tænder|starter|defekt|revnet|ødelagt|skadet|imei|simkort|dual sim|factory reset|nulstillet|android\s*1[2-9])\b',re.I)
SPEC_RE=re.compile(r'\b(?:6|8|12|16)\s*gb\s*(?:ram)?\b|\b(?:64|128|256|512)\s*gb\b',re.I)

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

def product_identity(title:str,description:str,model:str|None,price:int|None)->tuple[bool,str]:
    t=' '.join((title or '').split()); d=' '.join((description or '').split()); both=f'{t} {d}'
    title_model=model_of(t)
    if not model or title_model!=model: return False,'model not identified unambiguously in live title'
    if ACCESSORY_RE.search(t): return False,'accessory/part language in live title'
    # Extremely cheap ads are overwhelmingly accessories/parts; require strong evidence that the object is the phone.
    complete=bool(COMPLETE_PHONE_RE.search(both)); functional=bool(FUNCTION_RE.search(both)); specs=bool(SPEC_RE.search(both))
    if price is not None and price < 150 and not (complete and (functional or specs)):
        return False,'sub-150 DKK listing lacks strong complete-phone evidence'
    # Above the noise floor, a clean model title is acceptable, but descriptions containing explicit accessory-only wording are not.
    if ACCESSORY_RE.search(d) and not (complete and functional): return False,'description indicates accessory/part rather than complete phone'
    return True,'complete-phone identity passed'

def getj(s,url,params=None):
    r=s.get(url,params=params,headers=HEADERS,timeout=TIMEOUT); r.raise_for_status(); return r.json()

def canonical_id_from_payload(payload):
    for obj in (payload.get('jsonLd'),payload.get('meta'),payload.get('itemData')):
        if isinstance(obj,dict):
            for key in ('url','canonical','canonicalUrl','canonical_url','id','listingId','itemId'):
                v=obj.get(key)
                if v is None: continue
                m=re.search(r'/item/(\d+)',str(v))
                if m:return m.group(1)
                if str(v).isdigit():return str(v)
    stack=[payload]
    while stack:
        x=stack.pop()
        if isinstance(x,dict):
            for k,v in x.items():
                if k.lower() in ('url','canonicalurl','canonical_url','listingid','itemid'):
                    m=re.search(r'/item/(\d+)',str(v))
                    if m:return m.group(1)
                    if str(v).isdigit() and k.lower()!='url':return str(v)
                if isinstance(v,(dict,list)):stack.append(v)
        elif isinstance(x,list):stack.extend(x[:200])
    return None

def fetch_item(s,lid):
    payload=getj(s,ITEM_URL.format(id=lid)); item=payload.get('itemData') or {}; bound=canonical_id_from_payload(payload)
    return {'listing_id':lid,'bound_listing_id':bound,'identity_ok':bound==lid if bound else False,'url':ITEM_URL.format(id=lid),'title':str(item.get('title') or '').strip(),'price':amount(item.get('price')),'disposed':bool(item.get('disposed')),'trade_type':item.get('tradeType') or item.get('adViewTypeLabel'),'description':str(item.get('description') or ''),'location':item.get('location'),'extras':item.get('extras'),'meta':item.get('meta')}

def main():
    s=requests.Session(); Path('results').mkdir(exist_ok=True); reg=fetch_item(s,REGRESSION_ID)
    regression_ok=bool(reg['identity_ok'] and reg['price']==REGRESSION_PRICE and reg['title'] and not reg['disposed'])
    if not regression_ok:
        out={'generated_at':datetime.now(timezone.utc).isoformat(),'gate_passed':False,'reason':'PRICE DATA GATE FAILED','regression':reg,'expected_price':REGRESSION_PRICE}; Path('results/acurast_latest.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)); raise SystemExit('PRICE DATA GATE FAILED')
    found={}; search_errors=[]
    for q in QUERIES:
        try:
            for d in (getj(s,SEARCH_API,{'q':q,'sort':'PRICE_ASC'}).get('docs') or []):
                lid=str(d.get('id') or d.get('listingId') or d.get('itemId') or ''); title=str(d.get('heading') or d.get('title') or '').strip(); p=amount(d.get('price')); model=model_of(title)
                if not lid or not title or p is None or not model: continue
                r=found.setdefault(lid,{'listing_id':lid,'title_t0':title,'ask_t0':p,'model':model,'queries':[]}); r['queries'].append(q)
        except Exception as e: search_errors.append({'query':q,'error':repr(e)})
        time.sleep(.03)
    verified=[]; excluded=[]
    for r in found.values():
        try:
            t1=fetch_item(s,r['listing_id']); model=model_of(t1['title'])
            if not t1['identity_ok']: excluded.append({**r,'reason':'listing identity mismatch','t1':t1}); continue
            if t1['disposed']: excluded.append({**r,'reason':'disposed/inactive','t1':t1}); continue
            if t1['price'] is None or not t1['title']: excluded.append({**r,'reason':'missing live price/title','t1':t1}); continue
            prod_ok,prod_reason=product_identity(t1['title'],t1['description'],model,int(t1['price']))
            if not prod_ok: excluded.append({**r,'reason':'PRODUCT IDENTITY GATE: '+prod_reason,'t1':t1}); continue
            verified.append({**r,**t1,'model':model,'ask_t1':int(t1['price']),'product_identity_ok':True,'product_identity_reason':prod_reason,'price_changed':int(t1['price'])!=int(r['ask_t0']),'t1_timestamp':datetime.now(timezone.utc).isoformat()})
        except Exception as e: excluded.append({**r,'reason':f'T1 fetch failed: {e!r}'})
        time.sleep(.03)
    by_model={}
    for r in verified: by_model.setdefault(r['model'],[]).append(r)
    market=[]
    for model,rows in sorted(by_model.items()):
        asks=sorted(r['ask_t1'] for r in rows); market.append({'model':model,'n':len(asks),'min_ask':min(asks),'median_ask':statistics.median(asks),'max_ask':max(asks)})
    preliminary=sorted(verified,key=lambda r:(r['ask_t1'],r['model']))[:30]; final=[]
    for r in preliminary:
        try:
            t2=fetch_item(s,r['listing_id']); model=model_of(t2['title']); prod_ok,reason=product_identity(t2['title'],t2['description'],model,int(t2['price']) if t2['price'] is not None else None)
            if not (t2['identity_ok'] and not t2['disposed'] and t2['price'] is not None and t2['title'] and prod_ok): continue
            final.append({**r,'ask_t2':int(t2['price']),'title':t2['title'],'description':t2['description'],'product_identity_reason_t2':reason,'final_timestamp':datetime.now(timezone.utc).isoformat()})
        except Exception: pass
        time.sleep(.03)
    out={'generated_at':datetime.now(timezone.utc).isoformat(),'gate_passed':True,'product_identity_gate':True,'regression':{'listing_id':REGRESSION_ID,'price':reg['price'],'identity_ok':reg['identity_ok'],'disposed':reg['disposed'],'title':reg['title']},'counts':{'queries':len(QUERIES),'search_errors':len(search_errors),'t0_unique':len(found),'t1_verified_active_product':len(verified),'excluded':len(excluded),'product_identity_excluded':sum('PRODUCT IDENTITY GATE' in x.get('reason','') for x in excluded),'final_refetched':len(final)},'market':market,'ranked_by_verified_ask':final,'excluded':excluded,'search_errors':search_errors}
    Path('results/acurast_latest.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# Acurast DBA verified phone report','',f"Generated: {out['generated_at']}",'',f"Regression {REGRESSION_ID}: **PASS** — {reg['price']} DKK",'',f"T0: {len(found)} | T1 phone-verified: {len(verified)} | Product rejects: {out['counts']['product_identity_excluded']} | Final: {len(final)}",'','## Lowest verified complete-phone listings','', '| Rank | Model | ASK | Listing |','|---:|---|---:|---|']
    for i,r in enumerate(final,1): lines.append(f"| {i} | {r['model']} | {r['ask_t2']} kr. | [{r['title']}]({r['url']}) |")
    Path('results/acurast_report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({'gate':True,'product_gate':True,'regression_price':reg['price'],'t0':len(found),'verified_phone':len(verified),'product_rejects':out['counts']['product_identity_excluded'],'final':len(final),'top':[{k:r[k] for k in ('listing_id','model','ask_t2','title','url')} for r in final[:10]]},ensure_ascii=False,indent=2))
if __name__=='__main__': main()
