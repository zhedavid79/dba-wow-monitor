from __future__ import annotations

import json, re, statistics, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import requests

BASE='https://www.dba.dk'
SEARCH_API=BASE+'/recommerce/forsale/search/api/search/SEARCH_ID_BAP_COMMON'
ITEM_URL=BASE+'/recommerce/forsale/item/{id}'
BOT_BASE='https://api.acurastbot.com'
HEADERS={'User-Agent':'Mozilla/5.0','Accept-Language':'da-DK,da;q=0.9','Accept':'application/json,text/html;q=0.9,*/*;q=0.8'}
TIMEOUT=15
MOBILE_CATEGORY='2.93.3217.39'
MAX_ASK_DKK=1000
CATEGORY_MAX_PAGES=30
T1_WORKERS=12
T2_WORKERS=12
T2_LIMIT=120
ALLOWED_BRANDS={'samsung','oneplus','xiaomi','poco','motorola','google','nothing','asus','sony','oppo','realme','honor'}
SALVAGE_QUERIES=['defekt samsung','defekt oneplus','defekt xiaomi','defekt motorola','defekt pixel','revnet skærm samsung','revnet skærm oneplus','skærm defekt android','burn in samsung','repareres android']
ACCESSORY_RE=re.compile(r'(mobilcover|telefoncover|cover|covers|case|etui|skærmbeskytt|screenor|panserglas|beskyttelsesglas|privacy.?filter|kabel|ledning|oplader|charger|adapter|holder|mount|taske|pung|stativ|reservedel|reservedele|batteri\b|display\b|lcd\b|oled\b|skærm\s+til|kamera.?modul|bagglas|ramme\s+til|stylus|s[ -]?pen\b)',re.I)
COMPLETE_PHONE_RE=re.compile(r'\b(telefon|mobiltelefon|smartphone|mobil)\b',re.I)
FUNCTION_RE=re.compile(r'\b(virker|fungerer|tænder|starter|defekt|revnet|ødelagt|skadet|imei|simkort|dual sim|factory reset|nulstillet|android\s*1[2-9])\b',re.I)
SPEC_RE=re.compile(r'\b(?:4|6|8|10|12|16|18|24)\s*gb\s*(?:ram)?\b|\b(?:64|128|256|512|1024)\s*gb\b',re.I)


def getj(s,url,params=None):
    r=s.get(url,params=params,headers=HEADERS,timeout=TIMEOUT); r.raise_for_status(); return r.json()


def amount(v:Any)->int|None:
    if isinstance(v,(int,float)): return int(v)
    if isinstance(v,dict):
        for k in ('amount','value','price'):
            if isinstance(v.get(k),(int,float)): return int(v[k])
    if isinstance(v,str):
        s=re.sub(r'[^0-9]','',v); return int(s) if s else None
    return None


def norm(s:str)->str:
    return re.sub(r'[^a-z0-9]+',' ',(s or '').lower()).strip()


def build_catalog(s:requests.Session):
    devices=getj(s,BOT_BASE+'/devices/with-counts')
    stats=getj(s,BOT_BASE+'/devices/pool-statistics')
    stats_by_cfg={int(x['deviceConfigurationId']):x for x in stats if x.get('deviceConfigurationId') is not None}
    catalog=[]
    for d in devices:
        brand=norm(d.get('company',''))
        if brand not in ALLOWED_BRANDS: continue
        model=str(d.get('model') or '').strip()
        if not model: continue
        best_reward=None; total_count=0
        for c in d.get('configurations') or []:
            cid=c.get('id'); st=stats_by_cfg.get(int(cid)) if cid is not None else None
            if not st: continue
            total_count=max(total_count,int(st.get('processorCount') or 0))
            try: rw=float(st.get('expectedRewardMedian') or st.get('expectedRewardAvg'))
            except Exception: continue
            best_reward=rw if best_reward is None else max(best_reward,rw)
        if best_reward is None: continue
        full=f"{d.get('company','')} {model}".strip()
        aliases={norm(model),norm(full)}
        if norm(model).startswith(brand+' '): aliases.add(norm(model)[len(brand)+1:])
        aliases={a for a in aliases if len(a)>=4}
        catalog.append({'label':full,'brand':d.get('company',''),'model':model,'aliases':aliases,'reward':best_reward,'processor_count':total_count})
    catalog.sort(key=lambda x:(-x['reward'],-x['processor_count'],x['label']))
    return catalog


def model_of(text:str,catalog)->str|None:
    nt=' '+norm(text)+' '
    matches=[]
    for x in catalog:
        for a in x['aliases']:
            if f' {a} ' in nt:
                matches.append((len(a.split()),len(a),x['label']))
    return max(matches)[2] if matches else None


def product_identity(title:str,description:str,model:str|None,price:int|None,catalog)->tuple[bool,str]:
    t=' '.join((title or '').split()); d=' '.join((description or '').split()); both=f'{t} {d}'
    if price is not None and price > MAX_ASK_DKK: return False,f'live ASK exceeds {MAX_ASK_DKK} DKK ceiling'
    if not model: return False,'no AcurastBot-supported Android model resolved from live listing'
    if ACCESSORY_RE.search(t): return False,'accessory/part language in live title'
    complete=bool(COMPLETE_PHONE_RE.search(both)); functional=bool(FUNCTION_RE.search(both)); specs=bool(SPEC_RE.search(both))
    if price is not None and price < 150 and not (complete and (functional or specs)):
        return False,'sub-150 DKK listing lacks strong complete-phone evidence'
    if ACCESSORY_RE.search(d) and not (complete and functional): return False,'description indicates accessory/part rather than complete phone'
    return True,'Mobiltelefoner category + <=1000 DKK + supported-model + complete-phone identity passed'


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


def fetch_item(lid):
    r=requests.get(ITEM_URL.format(id=lid),headers=HEADERS,timeout=TIMEOUT); r.raise_for_status()
    payload=r.json(); item=payload.get('itemData') or {}; bound=canonical_id_from_payload(payload)
    return {'listing_id':lid,'bound_listing_id':bound,'identity_ok':bound==lid if bound else False,'url':ITEM_URL.format(id=lid),'title':str(item.get('title') or '').strip(),'price':amount(item.get('price')),'disposed':bool(item.get('disposed')),'trade_type':item.get('tradeType') or item.get('adViewTypeLabel'),'description':str(item.get('description') or ''),'location':item.get('location'),'extras':item.get('extras'),'meta':item.get('meta')}


def add_search_docs(found:dict,docs:list,source:str,catalog):
    added=0
    for d in docs:
        lid=str(d.get('id') or d.get('listingId') or d.get('itemId') or '')
        title=str(d.get('heading') or d.get('title') or '').strip(); p=amount(d.get('price'))
        if not lid or not title or p is None or p > MAX_ASK_DKK: continue
        model=model_of(title,catalog)
        is_new=lid not in found
        r=found.setdefault(lid,{'listing_id':lid,'title_t0':title,'ask_t0':p,'model_t0':model,'sources':[]})
        if source not in r['sources']: r['sources'].append(source)
        if is_new: added+=1
    return added


def t1_pool(found:dict)->list[dict]:
    return sorted(found.values(),key=lambda r:(int(r['ask_t0']),r['listing_id']))


def verify_t1(r,catalog):
    try:
        t1=fetch_item(r['listing_id']); model=model_of(f"{t1['title']} {t1['description']}",catalog)
        if not t1['identity_ok']: return None,{**r,'reason':'listing identity mismatch','t1':t1}
        if t1['disposed']: return None,{**r,'reason':'disposed/inactive','t1':t1}
        if t1['price'] is None or not t1['title']: return None,{**r,'reason':'missing live price/title','t1':t1}
        if int(t1['price']) > MAX_ASK_DKK: return None,{**r,'reason':f'live ASK exceeds {MAX_ASK_DKK} DKK ceiling','t1':t1}
        prod_ok,prod_reason=product_identity(t1['title'],t1['description'],model,int(t1['price']),catalog)
        if not prod_ok: return None,{**r,'reason':'PRODUCT IDENTITY GATE: '+prod_reason,'t1':t1}
        return {**r,**t1,'model':model,'ask_t1':int(t1['price']),'product_identity_ok':True,'product_identity_reason':prod_reason,'price_changed':int(t1['price'])!=int(r['ask_t0']),'t1_timestamp':datetime.now(timezone.utc).isoformat()},None
    except Exception as e:
        return None,{**r,'reason':f'T1 fetch failed: {e!r}'}


def verify_t2(r,catalog):
    try:
        t2=fetch_item(r['listing_id']); model=model_of(f"{t2['title']} {t2['description']}",catalog)
        if t2['price'] is None or int(t2['price']) > MAX_ASK_DKK: return None
        prod_ok,reason=product_identity(t2['title'],t2['description'],model,int(t2['price']),catalog)
        if not (t2['identity_ok'] and not t2['disposed'] and t2['title'] and prod_ok): return None
        return {**r,'model':model,'ask_t2':int(t2['price']),'title':t2['title'],'description':t2['description'],'product_identity_reason_t2':reason,'final_timestamp':datetime.now(timezone.utc).isoformat()}
    except Exception:
        return None


def main():
    s=requests.Session(); Path('results').mkdir(exist_ok=True)
    catalog=build_catalog(s)
    found={}; search_errors=[]; category_pages=0; category_docs=0

    previous_ids=None
    for page in range(1,CATEGORY_MAX_PAGES+1):
        try:
            payload=getj(s,SEARCH_API,{'product_category':MOBILE_CATEGORY,'sort':'PRICE_ASC','page':page})
            docs=payload.get('docs') or []
            if not isinstance(docs,list): raise ValueError('structured DBA category search returned no docs list')
            if not docs: break
            ids=tuple(str(d.get('id') or d.get('listingId') or d.get('itemId') or '') for d in docs)
            if ids==previous_ids: break
            previous_ids=ids; category_pages+=1; category_docs+=len(docs)
            add_search_docs(found,docs,f'category:{page}',catalog)
            page_prices=[amount(d.get('price')) for d in docs]
            page_prices=[p for p in page_prices if p is not None]
            if page_prices and min(page_prices) > MAX_ASK_DKK: break
        except Exception as e:
            search_errors.append({'query':f'category page {page}','error':repr(e)})
            if page==1: break
            continue
        time.sleep(.01)

    for q in SALVAGE_QUERIES:
        try:
            payload=getj(s,SEARCH_API,{'q':q,'sort':'PRICE_ASC'})
            docs=payload.get('docs') or []
            if not isinstance(docs,list): raise ValueError('structured DBA search returned no docs list')
            add_search_docs(found,docs,'salvage:'+q,catalog)
        except Exception as e: search_errors.append({'query':q,'error':repr(e)})
        time.sleep(.01)

    if not found:
        out={'generated_at':datetime.now(timezone.utc).isoformat(),'gate_passed':False,'reason':'PRICE DATA GATE FAILED — no structured DBA candidates <= 1000 DKK','search_errors':search_errors}
        Path('results/acurast_latest.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8'); raise SystemExit(out['reason'])

    pool=t1_pool(found); verified=[]; excluded=[]
    with ThreadPoolExecutor(max_workers=T1_WORKERS) as ex:
        futures={ex.submit(verify_t1,r,catalog):r for r in pool}
        for fut in as_completed(futures):
            ok,bad=fut.result()
            if ok: verified.append(ok)
            elif bad: excluded.append(bad)
    verified.sort(key=lambda r:(r['ask_t1'],r['model']))
    if not verified: raise SystemExit('PRICE DATA GATE FAILED — no T1 verified active phones <= 1000 DKK')

    by_model={}
    for r in verified: by_model.setdefault(r['model'],[]).append(r)
    market=[]
    for model,rows in sorted(by_model.items()):
        asks=sorted(r['ask_t1'] for r in rows); market.append({'model':model,'n':len(asks),'min_ask':min(asks),'median_ask':statistics.median(asks),'max_ask':max(asks)})

    preliminary=verified[:T2_LIMIT]; final=[]
    with ThreadPoolExecutor(max_workers=T2_WORKERS) as ex:
        futures=[ex.submit(verify_t2,r,catalog) for r in preliminary]
        for fut in as_completed(futures):
            row=fut.result()
            if row: final.append(row)
    final.sort(key=lambda r:(r['ask_t2'],r['model']))
    if not final: raise SystemExit('PRICE DATA GATE FAILED — no final refetched candidates <= 1000 DKK')

    out={'generated_at':datetime.now(timezone.utc).isoformat(),'gate_passed':True,'product_identity_gate':True,'max_ask_dkk':MAX_ASK_DKK,'data_gate':'DBA Mobiltelefoner category T0 + same-listing T1 + final T2 refetch','discovery_method':'PRIMARY: DBA Mobiltelefoner category 2.93.3217.39, price-ascending and hard-capped at 1000 DKK; SECONDARY: salvage queries; concurrent live verification','counts':{'category_pages':category_pages,'category_docs':category_docs,'salvage_queries':len(SALVAGE_QUERIES),'catalog_models':len(catalog),'search_errors':len(search_errors),'t0_unique':len(found),'t1_attempted':len(pool),'t1_verified_active_product':len(verified),'excluded':len(excluded),'product_identity_excluded':sum('PRODUCT IDENTITY GATE' in x.get('reason','') for x in excluded),'final_refetched':len(final)},'market':market,'ranked_by_verified_ask':final,'excluded':excluded,'search_errors':search_errors}
    Path('results/acurast_latest.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# Acurast DBA verified phone report','',f"Generated: {out['generated_at']}",'',f"DBA data gate: **PASS** — Mobiltelefoner category, ASK <= {MAX_ASK_DKK} DKK, live same-listing verification + final refetch",'',f"Category pages: {category_pages} | category docs: {category_docs} | T0 unique <= {MAX_ASK_DKK}: {len(found)} | T1 attempted: {len(pool)} | T1 phone-verified: {len(verified)} | Final: {len(final)}",'','## Lowest verified complete-phone listings','', '| Rank | Model | ASK | Listing |','|---:|---|---:|---|']
    for i,r in enumerate(final,1): lines.append(f"| {i} | {r['model']} | {r['ask_t2']} kr. | [{r['title']}]({r['url']}) |")
    Path('results/acurast_report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({'gate':True,'discovery':'Mobiltelefoner category primary, max 1000 DKK','category_pages':category_pages,'category_docs':category_docs,'catalog_models':len(catalog),'t0':len(found),'t1_attempted':len(pool),'verified_phone':len(verified),'final':len(final),'top':[{k:r[k] for k in ('listing_id','model','ask_t2','title','url')} for r in final[:10]]},ensure_ascii=False,indent=2))

if __name__=='__main__': main()
