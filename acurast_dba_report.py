from __future__ import annotations

import json, re, time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
import requests

BASE='https://www.dba.dk'
SEARCH_API=BASE+'/recommerce/forsale/search/api/search/SEARCH_ID_BAP_COMMON'
ITEM_URL=BASE+'/recommerce/forsale/item/{id}'
BOT_BASE='https://api.acurastbot.com'
HEADERS={'User-Agent':'Mozilla/5.0','Accept-Language':'da-DK,da;q=0.9','Accept':'application/json,text/html;q=0.9,*/*;q=0.8'}
TIMEOUT=15
REQUEST_RETRIES=3
MOBILE_CATEGORY='2.93.3217.39'
MAX_ASK_DKK=1000
CATEGORY_MAX_PAGES=100
T1_WORKERS=12
ACCESSORY_RE=re.compile(r'(mobilcover|telefoncover|cover|covers|case|etui|skærmbeskytt|screenor|panserglas|beskyttelsesglas|privacy.?filter|kabel|ledning|oplader|charger|adapter|holder|mount|taske|pung|stativ|reservedel|reservedele|batteri\b|display\b|lcd\b|oled\b|skærm\s+til|kamera.?modul|bagglas|ramme\s+til|stylus|s[ -]?pen\b)',re.I)
COMPLETE_PHONE_RE=re.compile(r'\b(telefon|telefonen|mobiltelefon|smartphone|mobil|mobilen)\b',re.I)
FUNCTION_RE=re.compile(r'\b(virker|fungerer|tænder|starter|defekt|revnet|ødelagt|skadet|imei|simkort|dual sim|factory reset|nulstillet|android\s*1[2-9])\b',re.I)
SPEC_RE=re.compile(r'\b(?:3|4|6|8|10|12|16|18|24)\s*gb\s*(?:ram)?\b|\b(?:32|64|128|256|512|1024)\s*gb\b',re.I)
KNOWN_PHONE_BRANDS={'apple','iphone','huawei','nokia','htc','lg','zte','meizu','vivo','blackview','ulefone','cubot','fairphone','tecno','infinix'}
VARIANT_WORDS=('ultra','pro','lite','fe','neo','fusion','plus')
GENERIC_MODEL_TOKENS={'galaxy','phone','smartphone','mobile','mobil','5g','4g','lte','nr'}


def getj(s,url,params=None):
    last=None
    for attempt in range(REQUEST_RETRIES):
        try:
            r=s.get(url,params=params,headers=HEADERS,timeout=TIMEOUT); r.raise_for_status(); return r.json()
        except (requests.ConnectionError,requests.Timeout,requests.HTTPError) as e:
            last=e
            if isinstance(e,requests.HTTPError) and e.response is not None and e.response.status_code < 500 and e.response.status_code != 429: raise
            if attempt+1<REQUEST_RETRIES: time.sleep(0.35*(2**attempt))
    raise last


def amount(v):
    if isinstance(v,(int,float)): return int(v)
    if isinstance(v,dict):
        for k in ('amount','value','price'):
            if isinstance(v.get(k),(int,float)): return int(v[k])
    if isinstance(v,str):
        s=re.sub(r'[^0-9]','',v); return int(s) if s else None
    return None


def norm(s): return re.sub(r'[^a-z0-9]+',' ',(s or '').lower()).strip()
def compact(s):
    n=norm(s); n=re.sub(r'([a-z]+)(\d)',r'\1 \2',n); n=re.sub(r'(\d)([a-z]+)',r'\1 \2',n); return re.sub(r'\s+','',n)


def alias_variants(brand,model,full):
    b=norm(brand); aliases={norm(model),norm(full)}; m_tokens=norm(model).split()
    if m_tokens and m_tokens[0]==b: aliases.add(' '.join(m_tokens[1:]))
    reduced=[t for t in m_tokens if t!=b and t not in GENERIC_MODEL_TOKENS]
    if reduced: aliases.add(' '.join(reduced))
    expanded=set()
    for a in aliases:
        expanded.add(a)
        if ' fe ' in f' {a} ': expanded.add(re.sub(r'\bfe\b','fan edition',a))
    return {a.strip() for a in expanded if len(a.strip())>=4}


def _catalog_row(brand,model,processor_count=0,source='ACURASTBOT'):
    brand=str(brand or '').strip(); model=str(model or '').strip()
    full=f'{brand} {model}'.strip()
    return {'label':full,'brand':brand,'model':model,
            'aliases':alias_variants(brand,model,full),
            'processor_count':int(processor_count or 0),'catalog_source':source}


def _pulse_discovery_rows(bot_catalog):
    # V1.6 ranks on Mainnet Pulse. Therefore a model present in Pulse must be able
    # to reach T1 even when the legacy AcurastBot supported-device registry has no
    # row for it. Pulse is used only for model discovery here; Core compatibility,
    # same-listing identity and reward gates remain downstream fail-closed gates.
    try:
        from acurast_valuation_fixed import fetch_pulse_catalog
        pulse=fetch_pulse_catalog()
    except Exception:
        return []

    brand_names={norm(x['brand']):x['brand'] for x in bot_catalog if norm(x.get('brand'))}
    for b in KNOWN_PHONE_BRANDS:
        brand_names.setdefault(norm(b),b)
    # Common Pulse brands may not currently have an AcurastBot registry row.
    for b in ('Samsung','Google','Xiaomi','Motorola','OnePlus','Nothing','Poco','Asus','Sony','Oppo','Realme','Honor'):
        brand_names.setdefault(norm(b),b)

    out=[]
    for p in pulse:
        full=str(p.get('pulse_model') or '').strip()
        nf=norm(full)
        if not nf: continue
        hits=[(len(nb),nb,display) for nb,display in brand_names.items() if nf.startswith(nb+' ')]
        if not hits: continue
        _,nb,display=max(hits)
        parts=full.split()
        brand_words=len(nb.split())
        model=' '.join(parts[brand_words:]).strip()
        if not model: continue
        out.append(_catalog_row(display,model,p.get('processors') or 0,'ACURAST_PULSE_MAINNET'))
    return out


def build_catalog(s):
    # Discovery is the union of the AcurastBot supported-device registry and the
    # authoritative V1.6 Mainnet Pulse model universe. Legacy Canary pool rewards
    # never decide whether a model can reach the Mainnet Pulse reward gate.
    devices=getj(s,BOT_BASE+'/devices/with-counts')
    catalog=[]
    for d in devices:
        brand=str(d.get('company') or '').strip(); model=str(d.get('model') or '').strip()
        if not norm(brand) or not model: continue
        catalog.append(_catalog_row(brand,model,d.get('totalProcessorCount') or 0,'ACURASTBOT'))

    by_key={(norm(x['brand']),norm(x['model'])):x for x in catalog}
    for row in _pulse_discovery_rows(catalog):
        key=(norm(row['brand']),norm(row['model']))
        old=by_key.get(key)
        if old is None:
            catalog.append(row); by_key[key]=row
        else:
            old['aliases'] |= row['aliases']
            old['processor_count']=max(old['processor_count'],row['processor_count'])
            if old.get('catalog_source')!='ACURAST_PULSE_MAINNET': old['catalog_source']='ACURASTBOT+ACURAST_PULSE_MAINNET'
    catalog.sort(key=lambda x:(-x['processor_count'],x['label']))
    return catalog


def catalog_brands(catalog): return {norm(x['brand']) for x in catalog if norm(x['brand'])}
def detected_brand(text,catalog):
    n=' '+norm(text)+' '; aliases={'pixel':'google','galaxy':'samsung','redmi':'xiaomi','moto':'motorola'}; hits=[]
    for b in catalog_brands(catalog) | KNOWN_PHONE_BRANDS:
        if f' {b} ' in n: hits.append('apple' if b=='iphone' else b)
    for token,b in aliases.items():
        if f' {token} ' in n: hits.append(b)
    if re.search(r'\bi\s*phone\b|\biphone\b',n): return 'apple'
    uniq=set(hits); return next(iter(uniq)) if len(uniq)==1 else None


def candidate_variant_ok(text,model):
    raw=(text or '').lower(); nt=' '+norm(text)+' '; nm=' '+norm(model)+' '
    if '+' in str(model) and not ('+' in raw or ' plus ' in nt): return False
    for variant in VARIANT_WORDS:
        if f' {variant} ' in nm and f' {variant} ' not in nt: return False
    return True


def model_of(text,catalog):
    text=re.sub(r'\bfan\s+edition\b','fe',text or '',flags=re.I)
    nt=' '+norm(text)+' '; ct=compact(text); seller_brand=detected_brand(text,catalog); matches=[]
    if seller_brand=='apple': return None
    for x in catalog:
        xb=norm(x['brand'])
        if seller_brand and xb!=seller_brand: continue
        if not candidate_variant_ok(text,x['model']): continue
        for a in x['aliases']:
            ca=compact(a)
            if f' {a} ' in nt or (len(ca)>=5 and ca in ct):
                toks=[t for t in norm(x['model']).split() if t not in {xb,'galaxy','phone','smartphone','5g','lte'}]
                matches.append((sum(len(t) for t in toks),len(toks),len(ca),x['label']))
    return max(matches)[3] if matches else None


def resolve_model(title,description,catalog): return model_of(title,catalog) or model_of(f'{title} {description}',catalog)


def product_identity(title,description,model,price,catalog):
    t=' '.join((title or '').split()); d=' '.join((description or '').split()); both=f'{t} {d}'
    explicit=detected_brand(t,catalog)
    if explicit=='apple': return False,'Apple/iPhone listing is not an Android Acurast Core candidate'
    if price is not None and price>MAX_ASK_DKK:return False,'ASK ceiling'
    if not model:return False,'no supported model resolved'
    model_brand=norm(next((x['brand'] for x in catalog if x['label']==model),''))
    if explicit and explicit!=model_brand:return False,f'explicit brand mismatch: {explicit} != {model_brand}'
    model_name=next((x['model'] for x in catalog if x['label']==model),model)
    if not candidate_variant_ok(both,model_name): return False,'resolved model variant is not supported by seller text'
    if ACCESSORY_RE.search(t):return False,'accessory/part title'
    complete=bool(COMPLETE_PHONE_RE.search(both)); functional=bool(FUNCTION_RE.search(both)); specs=bool(SPEC_RE.search(both)); explicit_model_title=bool(model_of(t,catalog))
    if price is not None and price<150 and not (complete and (functional or specs)):return False,'weak complete-phone evidence'
    if ACCESSORY_RE.search(d) and not (complete and functional) and not (explicit_model_title and functional):return False,'description indicates part without explicit functional phone evidence'
    return True,'supported-device registry + Mainnet Pulse discovery + strict brand/model/variant identity + live product identity passed'


def canonical_id_from_payload(payload):
    stack=[payload]
    while stack:
        x=stack.pop()
        if isinstance(x,dict):
            for k,v in x.items():
                if k.lower() in ('url','canonicalurl','canonical_url','listingid','itemid','id'):
                    m=re.search(r'/item/(\d+)',str(v))
                    if m:return m.group(1)
                    if str(v).isdigit() and k.lower()!='url':return str(v)
                if isinstance(v,(dict,list)):stack.append(v)
        elif isinstance(x,list):stack.extend(x[:200])
    return None


def fetch_item(lid):
    r=requests.get(ITEM_URL.format(id=lid),headers=HEADERS,timeout=TIMEOUT); r.raise_for_status(); p=r.json(); i=p.get('itemData') or {}; bound=canonical_id_from_payload(p)
    return {'listing_id':lid,'identity_ok':bound==lid if bound else False,'url':ITEM_URL.format(id=lid),'title':str(i.get('title') or '').strip(),'price':amount(i.get('price')),'disposed':bool(i.get('disposed')),'trade_type':i.get('tradeType') or i.get('adViewTypeLabel'),'description':str(i.get('description') or '')}


def add_search_docs(found,docs,source,catalog):
    for d in docs:
        lid=str(d.get('id') or d.get('listingId') or d.get('itemId') or ''); title=str(d.get('heading') or d.get('title') or '').strip(); p=amount(d.get('price'))
        if not lid or not title or p is None or p>MAX_ASK_DKK:continue
        r=found.setdefault(lid,{'listing_id':lid,'title_t0':title,'ask_t0':p,'model_t0':model_of(title,catalog),'brand_t0':detected_brand(title,catalog),'sources':[]})
        if source not in r['sources']:r['sources'].append(source)


def verify(r,catalog):
    try:
        x=fetch_item(r['listing_id'])
        if not x['identity_ok']: return None,{**r,'stage':'T1','reason':'same-listing identity failed'}
        if x['disposed']: return None,{**r,'stage':'T1','reason':'listing disposed','title':x['title'],'url':x['url']}
        if x['price'] is None: return None,{**r,'stage':'T1','reason':'live price missing','title':x['title'],'url':x['url']}
        if x['price']>MAX_ASK_DKK: return None,{**r,'stage':'T1','reason':'live ASK over ceiling','title':x['title'],'url':x['url']}
        model=resolve_model(x['title'],x['description'],catalog)
        ok,reason=product_identity(x['title'],x['description'],model,x['price'],catalog)
        if not ok: return None,{**r,**x,'stage':'PRODUCT_IDENTITY','resolved_model':model,'reason':reason}
        return {**r,**x,'model':model,'ask_t1':int(x['price']),'ask_t2':int(x['price']),'product_identity_reason':reason,'final_timestamp':datetime.now(timezone.utc).isoformat()},None
    except Exception as e:
        return None,{**r,'stage':'T1_ERROR','reason':type(e).__name__}


def main():
    s=requests.Session(); Path('results').mkdir(exist_ok=True); catalog=build_catalog(s); found={}; category_pages=0; category_docs=0; previous=None
    for page in range(1,CATEGORY_MAX_PAGES+1):
        p=getj(s,SEARCH_API,{'product_category':MOBILE_CATEGORY,'sort':'PRICE_ASC','page':page}); docs=p.get('docs') or []
        if not docs:break
        ids=tuple(str(d.get('id') or '') for d in docs)
        if ids==previous:break
        previous=ids; category_pages+=1; category_docs+=len(docs); add_search_docs(found,docs,f'category:{page}',catalog)
        prices=[amount(d.get('price')) for d in docs if amount(d.get('price')) is not None]
        if prices and min(prices)>MAX_ASK_DKK:break

    pool=sorted(found.values(),key=lambda r:(r['ask_t0'],r['listing_id'])); verified=[]; rejects=[]
    with ThreadPoolExecutor(max_workers=T1_WORKERS) as ex:
        futures=[ex.submit(verify,r,catalog) for r in pool]
        for f in as_completed(futures):
            x,rej=f.result()
            if x: verified.append(x)
            elif rej: rejects.append(rej)
    verified.sort(key=lambda r:(r['ask_t2'],r['model']))
    if not verified:raise SystemExit('PRICE DATA GATE FAILED — no verified supported devices')

    likely_unresolved=[r for r in rejects if r.get('stage')=='PRODUCT_IDENTITY' and r.get('reason')=='no supported model resolved' and r.get('brand_t0') not in (None,'apple')]
    stage_counts=Counter(r.get('stage') for r in rejects); reason_counts=Counter(r.get('reason') for r in rejects)
    audit={'generated_at':datetime.now(timezone.utc).isoformat(),'catalog_models':len(catalog),'t0_unique':len(pool),'verified_before_quality':len(verified),'reject_stage_counts':dict(stage_counts),'reject_reason_counts':dict(reason_counts),'likely_model_blindspots':sorted(likely_unresolved,key=lambda r:(r.get('ask_t0') or 999999,r.get('listing_id')))[:250],'all_rejects':rejects}
    Path('results/acurast_discovery_audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')

    out={'generated_at':datetime.now(timezone.utc).isoformat(),'gate_passed':True,'product_identity_gate':True,'max_ask_dkk':MAX_ASK_DKK,'data_gate':'AcurastBot supported-device registry + Acurast Pulse Mainnet model discovery + DBA category + same-listing verification','counts':{'category_pages':category_pages,'category_docs':category_docs,'catalog_models':len(catalog),'t0_unique':len(found),'t1_attempted':len(pool),'t1_verified_active_product':len(verified),'product_identity_excluded':stage_counts.get('PRODUCT_IDENTITY',0),'final_refetched':len(verified)},'ranked_by_verified_ask':verified,'excluded':[],'search_errors':[]}
    Path('results/acurast_latest.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'gate':True,'catalog_models':len(catalog),'category_pages':category_pages,'verified':len(verified),'reject_stages':dict(stage_counts),'likely_model_blindspots':len(likely_unresolved)},indent=2))

if __name__=='__main__':main()
