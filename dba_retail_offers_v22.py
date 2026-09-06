from __future__ import annotations

import asyncio,json,re,statistics
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urljoin,urlparse
from playwright.async_api import async_playwright
import dba_component_market_v19 as market
import dba_retail_prices_v19 as retail19

RETAIL=Path('results/retail_prices_latest.json');OUT=Path('results/retail_offers_v22.json')
PRICE_RE=re.compile(r'(?<!\d)(\d{1,3}(?:[. ]\d{3})*|\d{3,5})(?:[,.]\d{2})?\s*(?:kr\.?|DKK)',re.I)
STOCK_RE=re.compile(r'\b(?:på lager|in stock|lagerfør|levering\s*\d|sendes|afsendes|klar til levering)\b',re.I)
FREE_SHIP_RE=re.compile(r'\b(?:fri fragt|gratis fragt|gratis levering|free shipping|0(?:[,.]00)?\s*kr\.?\s*(?:fragt|levering))\b',re.I)
PROMO_RE=re.compile(r'\b(?:tilbud|kampagne|rabat|spar|sale|specialpris|weekendpris|black friday|outlet)\b|\b\d{1,2}\s*%\b',re.I)
NORMAL_RE=re.compile(r'\b(?:før|førpris|normalpris|normal pris|vejledende pris|vejl\.?\s*pris)\D{0,20}(\d{1,3}(?:[. ]\d{3})*|\d{3,5})(?:[,.]\d{2})?\s*(?:kr\.?|DKK)',re.I)
SHIP_A=re.compile(r'\b(?:fragt|levering|shipping)\s*(?:fra\s*)?(\d{1,3}(?:[. ]\d{3})*|\d{1,4})(?:[,.](\d{1,2}))?\s*kr\.?',re.I)
SHIP_B=re.compile(r'(\d{1,3}(?:[. ]\d{3})*|\d{1,4})(?:[,.](\d{1,2}))?\s*kr\.?.{0,20}\b(?:fragt|levering|shipping)\b',re.I)
DELIVERY_INCLUDED_RE=re.compile(r'pris\s+inkl\.?\s+(?:leveringsomkostninger|fragt|levering)',re.I)
STORE_LINK_RE=re.compile(r'/go-to-shop/(\d+)/offer/(\d+)')
FINANCE_RE=re.compile(r'\b(?:pr\.?\s*(?:md|måned)|/\s*(?:md|måned)|måned(?:lig|en|er)?|afbetaling|delbetaling|finansiering|ratebetaling|kredit|per\s+month)\b',re.I)
SHIP_CONTEXT_RE=re.compile(r'\b(?:fragt|shipping|leveringsomkostning(?:er)?)\b',re.I)


def _line_context(text:str,start:int,end:int)->str:
    lo=text.rfind('\n',0,start)+1;hi=text.find('\n',end)
    if hi<0:hi=len(text)
    return text[lo:hi].strip()


def price_hits(text):
    s=str(text or '');out=[]
    for m in PRICE_RE.finditer(s):
        try:n=int(m.group(1).replace('.','').replace(' ',''))
        except:continue
        if not 100<=n<=100000:continue
        line=_line_context(s,m.start(),m.end());low=line.lower()
        # Reject monthly instalments/financing and shipping-only amounts. A true
        # delivery-inclusive product total is allowed when the line explicitly says so.
        if FINANCE_RE.search(line):continue
        if SHIP_CONTEXT_RE.search(line) and not DELIVERY_INCLUDED_RE.search(line):continue
        out.append({'value':n,'line':line[:240],'finance_rejected':False,'shipping_rejected':False})
    return out


def prices(text):return [x['value'] for x in price_hits(text)]

def shipping(text):
    s=str(text or '')
    if FREE_SHIP_RE.search(s):return 0,True,'EXPLICIT_FREE_SHIPPING'
    for rx in (SHIP_A,SHIP_B):
        m=rx.search(s)
        if not m:continue
        n=int(m.group(1).replace('.','').replace(' ',''));ctx=s[max(0,m.start()-18):m.end()+8].lower();exact='fra' not in ctx
        return n,exact,'EXPLICIT_SHIPPING' if exact else 'SHIPPING_FROM'
    return None,False,'SHIPPING_UNPROVEN'

def normal_price(text):
    m=NORMAL_RE.search(str(text or ''))
    if not m:return None
    try:return int(m.group(1).replace('.','').replace(' ',''))
    except:return None

def kinds():
    d={}
    for k,rows in market.RETAIL_CANDIDATES.items():
        for r in rows:d[str(r.get('sku') or '')]=k
    return d

async def evidence(anchor):
    best=''
    for level in range(7):
        try:
            loc=anchor if level==0 else anchor.locator('xpath='+'/..'*level);txt=(await loc.inner_text(timeout=500)).strip()
        except:continue
        if len(txt)>len(best):best=txt
        if prices(txt) and ('på lager' in txt.lower() or 'til butik' in txt.lower()):return txt[:2200]
    return best[:2200]

async def resolve(context,href):
    m=STORE_LINK_RE.search(href);sid=m.group(1) if m else None;oid=m.group(2) if m else None
    out={'redirect_url':href,'store_id':sid,'offer_id':oid,'store_offer_link_verified':bool(sid and oid),'direct_url':None,'external_resolved':False}
    try:
        resp=await context.request.get(href,timeout=12000,max_redirects=10,fail_on_status_code=False);out['http_status']=int(resp.status);u=str(resp.url);host=urlparse(u).netloc.lower().removeprefix('www.')
        if host and 'prisjagt.dk' not in host:out.update({'direct_url':u,'seller':host,'external_resolved':True})
    except Exception as exc:out['resolve_error']=f'{type(exc).__name__}: {str(exc)[:160]}'
    if not out.get('seller') and sid:out['seller']=f'Prisjagt butik #{sid}'
    out['buy_url']=out.get('direct_url') or href if out.get('store_offer_link_verified') else None
    out['concrete_store_offer']=bool(out.get('store_offer_link_verified') or out.get('external_resolved'))
    return out


def sane_offer(row:dict,anchor_price:int|None)->tuple[bool,str]:
    delivered=row.get('delivered_price_dkk')
    if delivered is None:return False,'NO_DELIVERED_PRICE'
    d=int(delivered);ref=int(anchor_price or 0)
    if not ref:return True,'NO_ANCHOR_PRICE'
    ratio=d/ref
    if ratio>=0.60:return True,'WITHIN_40PCT_OF_SAME_PRODUCT_REFERENCE'
    normal=row.get('normal_price_dkk');promo=bool(row.get('promo_evidence'))
    if normal:
        normal=int(normal)
        # Deep discounts can pass only when the same offer card explicitly proves
        # a promotion/normal price and the normal price is consistent with the
        # independently verified same-product price.
        if promo and normal>=int(ref*.75) and d>=int(normal*.35):return True,'EXPLICIT_DEEP_DISCOUNT_CORROBORATED'
    return False,f'IMPLAUSIBLE_LOW_PRICE_VS_SAME_PRODUCT_REFERENCE:{d}/{ref}'

async def inspect(context,p,sem,kmap):
    async with sem:
        page=await context.new_page();sku=str(p.get('sku') or '');name=str(p.get('name') or '');url=str(p.get('url') or '');anchor_price=int(p.get('price') or 0) or None
        out={'sku':sku,'kind':p.get('kind') or kmap.get(sku),'name':name,'product_url':url,'product_reference_price_dkk':anchor_price,'verified_at':datetime.now(timezone.utc).isoformat(),'identity_verified':False,'offers':[],'delivered_price_verified':False}
        try:
            resp=await page.goto(url,wait_until='domcontentloaded',timeout=45000);out['http_status']=int(resp.status) if resp else None;title=await page.title();h1=''
            try:h1=(await page.locator('h1').first.inner_text(timeout=2500)).strip()
            except:pass
            if not retail19.identity_ok(name,' '.join([title,h1])):out['error']='PRODUCT_IDENTITY_MISMATCH';return out
            out['identity_verified']=True;body=(await page.locator('body').inner_text(timeout=7000))[:50000];inclusive=bool(DELIVERY_INCLUDED_RE.search(body));out['comparison_delivery_included']=inclusive
            anchors=page.locator('a');n=min(await anchors.count(),600);raw=[];seen=set()
            for i in range(n):
                a=anchors.nth(i)
                try:href=await a.get_attribute('href') or ''
                except:continue
                if 'go-to-shop' not in href:continue
                href=urljoin(url,href);txt=await evidence(a);hits=price_hits(txt);vals=[x['value'] for x in hits]
                if not vals:continue
                displayed=min(vals);line=next((x['line'] for x in hits if x['value']==displayed),'');key=(href,displayed)
                if key in seen:continue
                seen.add(key);ship,se,sm=shipping(txt)
                raw.append({'displayed_price_dkk':displayed,'displayed_price_line':line,'price_candidates_dkk':vals,'shipping_dkk':ship,'shipping_exact':se,'shipping_method':sm,'in_stock_card':bool(STOCK_RE.search(txt)),'promo_evidence':bool(PROMO_RE.search(txt)),'normal_price_dkk':normal_price(txt),'redirect_url':href,'evidence_text':txt[:650]})
            raw.sort(key=lambda x:(x['displayed_price_dkk'],0 if x['in_stock_card'] else 1));resolved=[]
            for row in raw[:12]:
                r=dict(row);r.update(await resolve(context,row['redirect_url']));stock=bool(r.get('in_stock_card'))
                if inclusive:
                    delivered=int(r['displayed_price_dkk']);method='PRISJAGT_PRICE_INCL_DELIVERY';total_exact=True;ship=r.get('shipping_dkk') if r.get('shipping_exact') else None;item=delivered-int(ship) if ship is not None and delivered>=int(ship) else None
                else:
                    ship,se,sm=shipping(r.get('evidence_text'));r.update({'shipping_dkk':ship,'shipping_exact':se,'shipping_method':sm});item=int(r['displayed_price_dkk']);total_exact=bool(se and ship is not None);delivered=item+int(ship) if total_exact else None;method='ITEM_PLUS_EXACT_SHIPPING' if total_exact else 'UNPROVEN'
                r.update({'item_price_dkk':item,'delivered_price_dkk':delivered,'delivered_price_method':method,'in_stock_verified':stock})
                sane,sanity=sane_offer(r,anchor_price);r['price_sanity_ok']=sane;r['price_sanity_method']=sanity
                r['buy_ready_offer']=bool(stock and r.get('concrete_store_offer') and total_exact and delivered is not None and r.get('buy_url') and sane)
                if r.get('normal_price_dkk') and delivered and int(r['normal_price_dkk'])>delivered:r['explicit_discount_pct']=round((1-delivered/int(r['normal_price_dkk']))*100,1)
                resolved.append(r)
            verified=[r for r in resolved if r.get('buy_ready_offer')];vals=[int(r['delivered_price_dkk']) for r in verified];median=int(round(statistics.median(vals))) if vals else None
            for r in resolved:
                r['market_reference_delivered_dkk']=median;dp=r.get('delivered_price_dkk')
                r['deal_type']='EXPLICIT_SALE' if r.get('explicit_discount_pct') and r.get('price_sanity_ok') else 'MARKET_DEAL' if dp and median and dp<=median*.90 else 'PROMOTION_EVIDENCE' if r.get('promo_evidence') and r.get('price_sanity_ok') else 'BEST_CURRENT_PRICE'
            verified.sort(key=lambda r:int(r['delivered_price_dkk']));out['offers']=resolved
            if verified:
                b=verified[0];out.update({'best_delivered_offer':b,'delivered_price_verified':True,'delivered_price_dkk':int(b['delivered_price_dkk']),'item_price_dkk':b.get('item_price_dkk'),'shipping_dkk':b.get('shipping_dkk'),'delivered_price_method':b.get('delivered_price_method'),'buy_url':b.get('buy_url'),'seller':b.get('seller'),'store_id':b.get('store_id'),'offer_id':b.get('offer_id'),'external_url_resolved':b.get('external_resolved') is True,'deal_type':b.get('deal_type'),'normal_price_dkk':b.get('normal_price_dkk'),'market_reference_delivered_dkk':median,'price_sanity_ok':True,'price_sanity_method':b.get('price_sanity_method')})
            return out
        except Exception as exc:out['error']=f'{type(exc).__name__}: {str(exc)[:220]}';return out
        finally:await page.close()

async def main():
    doc=json.loads(RETAIL.read_text(encoding='utf-8'));kmap=kinds();ps=[];seen=set()
    for p in doc.get('products') or []:
        key=str(p.get('sku') or p.get('url') or '')
        if not p.get('url') or key in seen:continue
        seen.add(key);ps.append(dict(p))
    async with async_playwright() as pw:
        b=await pw.chromium.launch(headless=True);c=await b.new_context(locale='da-DK');sem=asyncio.Semaphore(5);rows=await asyncio.gather(*(inspect(c,p,sem,kmap) for p in ps));await c.close();await b.close()
    ready=[r for r in rows if r.get('delivered_price_verified')];deals=[r for r in ready if r.get('deal_type') in {'EXPLICIT_SALE','MARKET_DEAL','PROMOTION_EVIDENCE'}];by={str(r.get('sku')):r for r in rows if r.get('sku')}
    result={'generated_at':datetime.now(timezone.utc).isoformat(),'model':'V22_STORE_LEVEL_DELIVERED_PRICE_AND_DEALS','policy':'Purchase-ready new retail requires same-product identity, a store-specific Prisjagt offer_id/store_id, in-stock evidence, an authoritative delivery-inclusive total, rejection of financing/shipping-only amounts, and a sanity check against the independently verified same-product reference price. If the external retailer redirect is Cloudflare-blocked in GitHub Actions, the verified Prisjagt Til butik redirect is retained as the purchase link and explicitly marked as not externally resolved.','products_total':len(rows),'delivered_price_verified':len(ready),'deal_candidates':len(deals),'external_urls_resolved':sum(1 for r in ready if r.get('external_url_resolved')),'rows':rows};OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    for p in doc.get('products') or []:
        r=by.get(str(p.get('sku') or ''))
        if not r:continue
        p['retail_offer_v22']={k:r.get(k) for k in ('delivered_price_verified','delivered_price_dkk','item_price_dkk','shipping_dkk','delivered_price_method','buy_url','seller','store_id','offer_id','external_url_resolved','deal_type','normal_price_dkk','market_reference_delivered_dkk','price_sanity_ok','price_sanity_method')}
    doc['offer_gate_v22']={'model':result['model'],'products_total':len(rows),'delivered_price_verified':len(ready),'deal_candidates':len(deals),'external_urls_resolved':result['external_urls_resolved'],'required_price_basis':'DELIVERED_PRICE_DKK','financing_shipping_filter':True,'same_product_price_sanity':True};RETAIL.write_text(json.dumps(doc,ensure_ascii=False,indent=2),encoding='utf-8')
    bykind={k:sum(1 for r in ready if r.get('kind')==k) for k in ('MOTHERBOARD','PSU','CASE','COOLER','RAM','STORAGE')};print(json.dumps({'V22_RETAIL_OFFERS':True,'products':len(rows),'delivered_verified':len(ready),'deals':len(deals),'external_resolved':result['external_urls_resolved'],'by_kind':bykind},ensure_ascii=False));assert rows

if __name__=='__main__':asyncio.run(main())
