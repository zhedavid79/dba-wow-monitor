from __future__ import annotations

import asyncio
import json
import re
import statistics
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

from playwright.async_api import async_playwright

import dba_component_market_v19 as market
import dba_retail_prices_v19 as retail19

RETAIL = Path('results/retail_prices_latest.json')
OUT = Path('results/retail_offers_v22.json')
PRICE_RE = re.compile(r'(?<!\d)(\d{1,3}(?:[. ]\d{3})*|\d{3,5})(?:[,.]\d{2})?\s*(?:kr\.?|DKK)', re.I)
STOCK_RE = re.compile(r'\b(?:på lager|in stock|lagerfør|levering\s*\d|sendes|afsendes|klar til levering)\b', re.I)
FREE_SHIP_RE = re.compile(r'\b(?:fri fragt|gratis fragt|gratis levering|free shipping|0(?:[,.]00)?\s*kr\.?\s*(?:fragt|levering))\b', re.I)
PROMO_RE = re.compile(r'\b(?:tilbud|kampagne|rabat|spar|sale|specialpris|weekendpris|black friday|outlet)\b|\b\d{1,2}\s*%\b', re.I)
NORMAL_RE = re.compile(r'\b(?:før|førpris|normalpris|normal pris|vejledende pris|vejl\.?\s*pris)\D{0,20}(\d{1,3}(?:[. ]\d{3})*|\d{3,5})(?:[,.]\d{2})?\s*(?:kr\.?|DKK)', re.I)
SHIP_A = re.compile(r'\b(?:fragt|levering|shipping)\s*(?:fra\s*)?(\d{1,3}(?:[. ]\d{3})*|\d{1,4})(?:[,.](\d{1,2}))?\s*kr\.?', re.I)
SHIP_B = re.compile(r'(\d{1,3}(?:[. ]\d{3})*|\d{1,4})(?:[,.](\d{1,2}))?\s*kr\.?.{0,20}\b(?:fragt|levering|shipping)\b', re.I)
DELIVERY_INCLUDED_RE = re.compile(r'pris\s+inkl\.?\s+(?:leveringsomkostninger|fragt|levering)', re.I)


def prices(text: str) -> list[int]:
    vals=[]
    for m in PRICE_RE.finditer(str(text or '')):
        try:n=int(m.group(1).replace('.','').replace(' ',''))
        except Exception:continue
        if 100 <= n <= 100000: vals.append(n)
    return vals


def money_value(a: str, decimals: str | None=None) -> int:
    n=int(str(a).replace('.','').replace(' ',''))
    if decimals and int(decimals)>=50:n+=1
    return n


def shipping(text: str) -> tuple[int|None,bool,str]:
    s=str(text or '')
    if FREE_SHIP_RE.search(s):return 0,True,'EXPLICIT_FREE_SHIPPING'
    for rx in (SHIP_A,SHIP_B):
        m=rx.search(s)
        if not m:continue
        try:value=money_value(m.group(1),m.group(2))
        except Exception:continue
        context=s[max(0,m.start()-18):m.end()+8].lower()
        exact='fra' not in context
        return value,exact,'EXPLICIT_SHIPPING' if exact else 'SHIPPING_FROM'
    return None,False,'SHIPPING_UNPROVEN'


def normal_price(text: str) -> int|None:
    m=NORMAL_RE.search(str(text or ''))
    if not m:return None
    try:return int(m.group(1).replace('.','').replace(' ',''))
    except Exception:return None


def identity_ok(expected: str, actual: str) -> bool:
    return retail19.identity_ok(expected,actual)


def kind_by_sku() -> dict[str,str]:
    out={}
    for kind,rows in market.RETAIL_CANDIDATES.items():
        for r in rows:out[str(r.get('sku') or '')]=kind
    return out


async def evidence_blob(anchor) -> str:
    best=''
    for level in range(0,7):
        try:
            loc=anchor if level==0 else anchor.locator('xpath='+'/..'*level)
            txt=(await loc.inner_text(timeout=500)).strip()
        except Exception:continue
        if not txt:continue
        if not best or len(txt)>len(best):best=txt
        if prices(txt) and ('på lager' in txt.lower() or 'til butik' in txt.lower()):return txt[:2200]
    return best[:2200]


async def resolve_redirect(context,href: str) -> dict:
    out={'redirect_url':href,'direct_url':None,'seller':None,'redirect_ok':False}
    try:
        resp=await context.request.get(href,timeout=15000,max_redirects=10,fail_on_status_code=False)
        out['http_status']=int(resp.status);out['direct_url']=str(resp.url)
        host=urlparse(str(resp.url)).netloc.lower().removeprefix('www.')
        out['seller']=host or None;out['redirect_ok']=bool(host and 'prisjagt.dk' not in host)
        try:out['direct_body']=(await resp.text())[:60000]
        except Exception:out['direct_body']=''
    except Exception as exc:
        out['resolve_error']=f'{type(exc).__name__}: {str(exc)[:180]}'
        out['direct_body']=''
    return out


async def inspect_product(context,product: dict,sem: asyncio.Semaphore,kinds:dict[str,str]) -> dict:
    async with sem:
        page=await context.new_page();now=datetime.now(timezone.utc).isoformat()
        sku=str(product.get('sku') or '');expected=str(product.get('name') or '');url=str(product.get('url') or '')
        out={'sku':sku,'kind':product.get('kind') or kinds.get(sku),'name':expected,'product_url':url,'verified_at':now,'identity_verified':False,'offers':[],'best_delivered_offer':None,'best_lead':None,'delivered_price_verified':False}
        try:
            response=await page.goto(url,wait_until='domcontentloaded',timeout=45000)
            out['http_status']=int(response.status) if response else None
            title=await page.title();h1=''
            try:h1=(await page.locator('h1').first.inner_text(timeout=2500)).strip()
            except Exception:pass
            if not identity_ok(expected,' '.join([title,h1])):
                out['error']='PRODUCT_IDENTITY_MISMATCH';return out
            out['identity_verified']=True
            body=(await page.locator('body').inner_text(timeout=7000))[:50000]
            inclusive=bool(DELIVERY_INCLUDED_RE.search(body))
            out['comparison_delivery_included']=inclusive

            anchors=page.locator('a[href*="/go-to-shop/"]');n=min(await anchors.count(),80)
            raw=[];seen=set()
            for i in range(n):
                a=anchors.nth(i)
                try:href=await a.get_attribute('href') or ''
                except Exception:continue
                if not href:continue
                href=urljoin(url,href);txt=await evidence_blob(a);vals=prices(txt)
                if not vals:continue
                displayed=min(vals)
                key=(href,displayed)
                if key in seen:continue
                seen.add(key)
                ship,ship_exact,ship_method=shipping(txt)
                raw.append({'displayed_price_dkk':displayed,'shipping_dkk':ship,'shipping_exact':ship_exact,'shipping_method':ship_method,'in_stock_card':bool(STOCK_RE.search(txt)),'promo_evidence':bool(PROMO_RE.search(txt)),'normal_price_dkk':normal_price(txt),'redirect_url':href,'evidence_text':txt[:600]})

            raw.sort(key=lambda x:(x['displayed_price_dkk'],0 if x['in_stock_card'] else 1))
            resolved=[]
            for row in raw[:12]:
                r=dict(row);r.update(await resolve_redirect(context,str(row['redirect_url'])))
                direct_body=str(r.pop('direct_body','') or '')
                stock=bool(r.get('in_stock_card') or (direct_body and STOCK_RE.search(direct_body)))
                # Prisjagt explicitly labels the offer list as price including delivery.
                # In that state the displayed card total itself is the authoritative
                # delivered price; separate shipping is optional audit detail.
                if inclusive:
                    delivered=int(r['displayed_price_dkk']);basis='PRISJAGT_PRICE_INCL_DELIVERY'
                    ship=r.get('shipping_dkk') if r.get('shipping_exact') else None
                    item=delivered-int(ship) if ship is not None and delivered>=int(ship) else None
                    total_exact=True
                else:
                    ship,ship_exact,ship_method=shipping(str(r.get('evidence_text') or ''))
                    if not ship_exact and direct_body:
                        ds,de,dm=shipping(direct_body)
                        if de:ship,ship_exact,ship_method=ds,de,'DIRECT_'+dm
                    r['shipping_dkk']=ship;r['shipping_exact']=ship_exact;r['shipping_method']=ship_method
                    total_exact=bool(ship_exact and ship is not None)
                    item=int(r['displayed_price_dkk']);delivered=item+int(ship) if total_exact else None;basis='ITEM_PLUS_EXACT_SHIPPING' if total_exact else 'UNPROVEN'
                r['item_price_dkk']=item;r['delivered_price_dkk']=delivered;r['delivered_price_method']=basis;r['in_stock_verified']=stock
                r['buy_ready_offer']=bool(stock and r.get('redirect_ok') and total_exact and delivered is not None)
                if r.get('normal_price_dkk') and int(r['normal_price_dkk'])>int(delivered or 0):r['explicit_discount_pct']=round((1-int(delivered)/int(r['normal_price_dkk']))*100,1)
                resolved.append(r)

            verified=[r for r in resolved if r.get('buy_ready_offer')]
            vals=[int(r['delivered_price_dkk']) for r in verified]
            median=int(round(statistics.median(vals))) if vals else None
            for r in resolved:
                r['market_reference_delivered_dkk']=median;dp=r.get('delivered_price_dkk')
                if r.get('explicit_discount_pct'):r['deal_type']='EXPLICIT_SALE'
                elif dp is not None and median and dp<=median*0.90:r['deal_type']='MARKET_DEAL'
                elif r.get('promo_evidence'):r['deal_type']='PROMOTION_EVIDENCE'
                else:r['deal_type']='BEST_CURRENT_PRICE'
            verified.sort(key=lambda x:(int(x['delivered_price_dkk']),int(x['displayed_price_dkk'])))
            leads=[r for r in resolved if r.get('in_stock_verified') and r.get('redirect_ok')]
            leads.sort(key=lambda x:(int(x.get('delivered_price_dkk') or 10**9),int(x['displayed_price_dkk'])))
            out['offers']=resolved
            if verified:
                b=verified[0];out.update({'best_delivered_offer':b,'delivered_price_verified':True,'delivered_price_dkk':int(b['delivered_price_dkk']),'item_price_dkk':b.get('item_price_dkk'),'shipping_dkk':b.get('shipping_dkk'),'delivered_price_method':b.get('delivered_price_method'),'buy_url':b.get('direct_url') or b.get('redirect_url'),'seller':b.get('seller'),'deal_type':b.get('deal_type'),'normal_price_dkk':b.get('normal_price_dkk'),'market_reference_delivered_dkk':median})
            elif leads:out['best_lead']=leads[0]
            return out
        except Exception as exc:
            out['error']=f'{type(exc).__name__}: {str(exc)[:240]}';return out
        finally:await page.close()


async def main()->None:
    doc=json.loads(RETAIL.read_text(encoding='utf-8'));kinds=kind_by_sku();products=[];seen=set()
    for p in doc.get('products') or []:
        url=str(p.get('url') or '');sku=str(p.get('sku') or url)
        if not url or sku in seen:continue
        seen.add(sku);products.append(dict(p))
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True);context=await browser.new_context(locale='da-DK');sem=asyncio.Semaphore(5)
        rows=await asyncio.gather(*(inspect_product(context,x,sem,kinds) for x in products));await context.close();await browser.close()
    by_sku={str(r.get('sku')):r for r in rows if r.get('sku')};ready=[r for r in rows if r.get('delivered_price_verified')];deals=[r for r in ready if r.get('deal_type') in {'EXPLICIT_SALE','MARKET_DEAL','PROMOTION_EVIDENCE'}]
    result={'generated_at':datetime.now(timezone.utc).isoformat(),'model':'V22_STORE_LEVEL_DELIVERED_PRICE_AND_DEALS','policy':'A new retail candidate is purchase-ready only when same-product identity, concrete retailer, stock and a delivery-inclusive total are proven. Prisjagt offer rows explicitly shown under Pris inkl. leveringsomkostninger are accepted as delivered totals. Otherwise exact mandatory shipping must be separately evidenced. Unknown delivery cost remains a lead.','products_total':len(rows),'delivered_price_verified':len(ready),'deal_candidates':len(deals),'resolved_direct':sum(1 for r in rows for o in r.get('offers') or [] if o.get('redirect_ok')),'rows':rows}
    OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    for p in doc.get('products') or []:
        r=by_sku.get(str(p.get('sku') or ''))
        if not r:continue
        p['retail_offer_v22']={'delivered_price_verified':r.get('delivered_price_verified') is True,'delivered_price_dkk':r.get('delivered_price_dkk'),'item_price_dkk':r.get('item_price_dkk'),'shipping_dkk':r.get('shipping_dkk'),'delivered_price_method':r.get('delivered_price_method'),'buy_url':r.get('buy_url'),'seller':r.get('seller'),'deal_type':r.get('deal_type'),'normal_price_dkk':r.get('normal_price_dkk'),'market_reference_delivered_dkk':r.get('market_reference_delivered_dkk')}
    doc['offer_gate_v22']={'model':result['model'],'products_total':len(rows),'delivered_price_verified':len(ready),'deal_candidates':len(deals),'resolved_direct':result['resolved_direct'],'required_price_basis':'DELIVERED_PRICE_DKK'}
    RETAIL.write_text(json.dumps(doc,ensure_ascii=False,indent=2),encoding='utf-8')
    by_kind={k:sum(1 for r in ready if r.get('kind')==k) for k in ('MOTHERBOARD','PSU','CASE','COOLER','RAM','STORAGE')}
    print(json.dumps({'V22_RETAIL_OFFERS':True,'products':len(rows),'delivered_verified':len(ready),'deals':len(deals),'resolved_direct':result['resolved_direct'],'by_kind':by_kind},ensure_ascii=False))
    assert rows,'V22 offer engine inspected no products'


if __name__=='__main__':asyncio.run(main())
