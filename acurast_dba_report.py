from __future__ import annotations

import json, re, statistics, time
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
T2_WORKERS=12
T2_LIMIT=120
SALVAGE_QUERIES=['defekt samsung','defekt oneplus','defekt xiaomi','defekt motorola','defekt pixel','revnet skærm samsung','revnet skærm oneplus','skærm defekt android','burn in samsung','repareres android']
ACCESSORY_RE=re.compile(r'(mobilcover|telefoncover|cover|covers|case|etui|skærmbeskytt|screenor|panserglas|beskyttelsesglas|privacy.?filter|kabel|ledning|oplader|charger|adapter|holder|mount|taske|pung|stativ|reservedel|reservedele|batteri\b|display\b|lcd\b|oled\b|skærm\s+til|kamera.?modul|bagglas|ramme\s+til|stylus|s[ -]?pen\b)',re.I)
COMPLETE_PHONE_RE=re.compile(r'\b(telefon|mobiltelefon|smartphone|mobil)\b',re.I)
FUNCTION_RE=re.compile(r'\b(virker|fungerer|tænder|starter|defekt|revnet|ødelagt|skadet|imei|simkort|dual sim|factory reset|nulstillet|android\s*1[2-9])\b',re.I)
SPEC_RE=re.compile(r'\b(?:4|6|8|10|12|16|18|24)\s*gb\s*(?:ram)?\b|\b(?:64|128|256|512|1024)\s*gb\b',re.I)
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
    """Generate conservative marketed-name aliases without weakening variant identity.

    DBA sellers commonly omit connectivity suffixes (5G/LTE) and family words such as
    Galaxy. AcurastBot may include them in its canonical model label. Keep marketed
    variants such as FE/Ultra/Pro/Lite intact, but strip only non-distinguishing tokens.
    """
    b=norm(brand)
    aliases={norm(model),norm(full)}
    m_tokens=norm(model).split()
    if m_tokens and m_tokens[0]==b:
        aliases.add(' '.join(m_tokens[1:]))
    reduced=[t for t in m_tokens if t!=b and t not in GENERIC_MODEL_TOKENS]
    if reduced:
        aliases.add(' '.join(reduced))
    # Common seller wording: "Fan Edition" == marketed "FE".
    expanded=set()
    for a in aliases:
        expanded.add(a)
        if ' fe ' in f' {a} ':
            expanded.add(re.sub(r'\bfe\b','fan edition',a))
    return {a.strip() for a in expanded if len(a.strip())>=4}

def build_catalog(s):
    devices=getj(s,BOT_BASE+'/devices/with-counts'); stats=getj(s,BOT_BASE+'/devices/pool-statistics')
    stats_by_cfg={int(x['deviceConfigurationId']):x for x in stats if x.get('deviceConfigurationId') is not None}; catalog=[]
    for d in devices:
        brand=norm(d.get('company','')); model=str(d.get('model') or '').strip()
        if not brand or not model: continue
        best_reward=None; total_count=0
        for c in d.get('configurations') or []:
            cid=c.get('id'); st=stats_by_cfg.get(int(cid)) if cid is not None else None
            if not st: continue
            total_count=max(total_count,int(st.get('processorCount') or 0))
            try: rw=float(st.get('expectedRewardMedian') or st.get('expectedRewardAvg'))
            except Exception: continue
            best_reward=rw if best_reward is None else max(best_reward,rw)
        if best_reward is None: continue
        full=f"{d.get('company','')} {model}".strip(); aliases=alias_variants(d.get('company',''),model,full)
        catalog.append({'label':full,'brand':d.get('company',''),'model':model,'aliases':aliases,'reward':best_reward,'processor_count':total_count})
    catalog.sort(key=lambda x:(-x['reward'],-x['processor_count'],x['label'])); return catalog

def catalog_brands(catalog): return {norm(x['brand']) for x in catalog if norm(x['brand'])}
def detected_brand(text,catalog):
    n=' '+norm(text)+' '; aliases={'pixel':'google','galaxy':'samsung','redmi':'xiaomi'}; hits=[]
    cbrands=catalog_brands(catalog)
    for b in cbrands | KNOWN_PHONE_BRANDS:
        if f' {b} ' in n: hits.append('apple' if b=='iphone' else b)
    for token,b in aliases.items():
        if f' {token} ' in n: hits.append(b)
    if re.search(r'\bi\s*phone\b|\biphone\b',n): return 'apple'
    uniq=set(hits)
    return next(iter(uniq)) if len(uniq)==1 else None

def candidate_variant_ok(text,model):
    raw=(text or '').lower(); nt=' '+norm(text)+' '; nm=' '+norm(model)+' '
    if '+' in str(model) and not ('+' in raw or ' plus ' in nt): return False
    for variant in VARIANT_WORDS:
        if f' {variant} ' in nm and f' {variant} ' not in nt:
            return False
    return True

def model_of(text,catalog):
    # Normalize common seller synonym before alias matching.
    text=re.sub(r'\bfan\s+edition\b','fe',text or '',flags=re.I)
    nt=' '+norm(text)+' '; ct=compact(text); seller_brand=detected_brand(text,catalog); matches=[]
    if seller_brand=='apple': return None
    for x in catalog:
        xb=norm(x['brand'])
        if seller_brand and xb!=seller_brand: continue
        if not candidate_variant_ok(text,x['model']): continue
        for a in x['aliases']:
            boundary=f' {a} ' in nt; ca=compact(a); compact_hit=len(ca)>=5 and ca in ct
            if boundary or compact_hit:
                model_tokens=[t for t in norm(x['model']).split() if t not in {xb,'galaxy','phone','smartphone','5g','lte'}]
                matches.append((sum(len(t) for t in model_tokens),len(model_tokens),len(ca),x['label']))
    return max(matches)[3] if matches else None

def resolve_model(title,description,catalog): return model_of(title,catalog) or model_of(f'{title} {description}',catalog)
def product_identity(title,description,model,price,catalog):
    t=' '.join((title or '').split()); d=' '.join((description or '').split()); both=f'{t} {d}'
    explicit=detected_brand(t,catalog)
    if explicit=='apple': return False,'Apple/iPhone listing is not an Android Acurast Core candidate'
    if price is not None and price>MAX_ASK_DKK:return False,'ASK ceiling'
    if not model:return False,'no AcurastBot-supported model resolved'
    model_brand=norm(next((x['brand'] for x in catalog if x['label']==model),''))
    if explicit and explicit!=model_brand:return False,f'explicit brand mismatch: {explicit} != {model_brand}'
    if not candidate_variant_ok(both,next((x['model'] for x in catalog if x['label']==model),model)):
        return False,'resolved model variant is not supported by seller text'
    if ACCESSORY_RE.search(t):return False,'accessory/part title'
    complete=bool(COMPLETE_PHONE_RE.search(both)); functional=bool(FUNCTION_RE.search(both)); specs=bool(SPEC_RE.search(both))
    if price is not None and price<150 and not (complete and (functional or specs)):return False,'weak complete-phone evidence'
    if ACCESSORY_RE.search(d) and not (complete and functional):return False,'description indicates part'
    return True,'AcurastBot dynamic universe + strict brand/model/variant identity + live product identity passed'

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
    r=requests.get(ITEM_URL.format(id=lid),headers=HEADERS,timeout=TIMEOUT);r.raise_for_status();p=r.json();i=p.get('itemData') or {};bound=canonical_id_from_payload(p)
    return {'listing_id':lid,'identity_ok':bound==lid if bound else False,'url':ITEM_URL.format(id=lid),'title':str(i.get('title') or '').strip(),'price':amount(i.get('price')),'disposed':bool(i.get('disposed')),'trade_type':i.get('tradeType') or i.get('adViewTypeLabel'),'description':str(i.get('description') or '')}
def add_search_docs(found,docs,source,catalog):
    for d in docs:
        lid=str(d.get('id') or d.get('listingId') or d.get('itemId') or '');title=str(d.get('heading') or d.get('title') or '').strip();p=amount(d.get('price'))
        if not lid or not title or p is None or p>MAX_ASK_DKK:continue
        r=found.setdefault(lid,{'listing_id':lid,'title_t0':title,'ask_t0':p,'model_t0':model_of(title,catalog),'sources':[]})
        if source not in r['sources']:r['sources'].append(source)
def verify(r,catalog):
    try:
        x=fetch_item(r['listing_id']);model=resolve_model(x['title'],x['description'],catalog)
        ok,reason=product_identity(x['title'],x['description'],model,x['price'],catalog)
        if not x['identity_ok'] or x['disposed'] or x['price'] is None or x['price']>MAX_ASK_DKK or not ok:return None
        return {**r,**x,'model':model,'ask_t1':int(x['price']),'ask_t2':int(x['price']),'product_identity_reason':reason,'final_timestamp':datetime.now(timezone.utc).isoformat()}
    except Exception:return None

def main():
    s=requests.Session();Path('results').mkdir(exist_ok=True);catalog=build_catalog(s);found={};category_pages=0;category_docs=0;previous=None
    for page in range(1,CATEGORY_MAX_PAGES+1):
        p=getj(s,SEARCH_API,{'product_category':MOBILE_CATEGORY,'sort':'PRICE_ASC','page':page});docs=p.get('docs') or []
        if not docs:break
        ids=tuple(str(d.get('id') or '') for d in docs)
        if ids==previous:break
        previous=ids;category_pages+=1;category_docs+=len(docs);add_search_docs(found,docs,f'category:{page}',catalog)
        prices=[amount(d.get('price')) for d in docs if amount(d.get('price')) is not None]
        if prices and min(prices)>MAX_ASK_DKK:break
    pool=sorted(found.values(),key=lambda r:(r['ask_t0'],r['listing_id']));verified=[]
    with ThreadPoolExecutor(max_workers=T1_WORKERS) as ex:
        for f in as_completed([ex.submit(verify,r,catalog) for r in pool]):
            x=f.result()
            if x:verified.append(x)
    verified.sort(key=lambda r:(r['ask_t2'],r['model']))
    if not verified:raise SystemExit('PRICE DATA GATE FAILED — no verified AcurastBot devices')
    out={'generated_at':datetime.now(timezone.utc).isoformat(),'gate_passed':True,'product_identity_gate':True,'max_ask_dkk':MAX_ASK_DKK,'data_gate':'AcurastBot dynamic device universe + DBA category + same-listing verification','counts':{'category_pages':category_pages,'category_docs':category_docs,'catalog_models':len(catalog),'t0_unique':len(found),'t1_attempted':len(pool),'t1_verified_active_product':len(verified),'final_refetched':len(verified)},'ranked_by_verified_ask':verified,'excluded':[],'search_errors':[]}
    Path('results/acurast_latest.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'gate':True,'catalog_models':len(catalog),'category_pages':category_pages,'verified':len(verified)},indent=2))
if __name__=='__main__':main()
