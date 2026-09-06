from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright

import dba_retail_prices_v19 as retail19

STRATEGY=Path('results/wow_strategy_latest.json')
OUT=Path('results/retail_availability_v21.json')
PRICE_RE=re.compile(r'(?<!\d)(\d{1,3}(?:[. ]\d{3})*|\d{3,5})(?:[,.]\d{2})?\s*(?:kr\.?|DKK)',re.I)
STOCK_RE=re.compile(r'\b(?:på lager|lagerfør|in stock|tilgængelig|levering|afsend|shipping|sendes)\b',re.I)


def norm(s:str)->str:
    return re.sub(r'[^a-z0-9]+',' ',str(s or '').lower()).strip()


def identity_ok(expected:str,actual:str)->bool:
    return retail19.identity_ok(expected,actual)


def money_int(raw:str)->int|None:
    m=PRICE_RE.search(str(raw or ''))
    if not m:return None
    try:return int(m.group(1).replace('.','').replace(' ',''))
    except Exception:return None


def walk(obj):
    if isinstance(obj,dict):
        yield obj
        for v in obj.values():yield from walk(v)
    elif isinstance(obj,list):
        for v in obj:yield from walk(v)


def selected_retail_components(data:dict)->list[dict]:
    rec=data.get('recommended_self_build') or {}
    rows=[];seen=set()
    for c in rec.get('components') or []:
        if str(c.get('source') or '').upper()!='NEW RETAIL':continue
        url=str(c.get('url') or '')
        if not url or url in seen:continue
        seen.add(url)
        rows.append({'kind':c.get('kind'),'name':c.get('name'),'url':url,'expected_price':int(c.get('price') or 0),'sku':c.get('sku')})
    return rows


def structured_offers(blobs:list,expected_name:str)->list[dict]:
    out=[]
    for blob in blobs:
        for d in walk(blob):
            typ=d.get('@type');types=typ if isinstance(typ,list) else [typ]
            if not any(str(x).lower()=='product' for x in types if x):continue
            name=str(d.get('name') or '')
            if not identity_ok(expected_name,name):continue
            offers=d.get('offers')
            for o in walk(offers):
                if not isinstance(o,dict):continue
                price=retail19.numeric_price(o.get('price')) or retail19.numeric_price(o.get('lowPrice'))
                if not price:continue
                seller=o.get('seller') or o.get('offeredBy') or {}
                if isinstance(seller,dict):seller_name=str(seller.get('name') or '')
                else:seller_name=str(seller or '')
                availability=str(o.get('availability') or '')
                offer_url=str(o.get('url') or '')
                out.append({'price':price,'seller':seller_name,'availability':availability,'url':offer_url,'method':'JSON_LD_OFFER'})
    uniq=[];seen=set()
    for r in sorted(out,key=lambda x:x['price']):
        key=(r['price'],r['seller'],r['url'],r['availability'])
        if key in seen:continue
        seen.add(key);uniq.append(r)
    return uniq


async def dom_store_rows(page,expected_price:int)->list[dict]:
    rows=[]
    anchors=page.locator('a')
    count=min(await anchors.count(),500)
    for i in range(count):
        a=anchors.nth(i)
        try:
            href=await a.get_attribute('href') or ''
            text=(await a.inner_text(timeout=300)).strip()
            parent=(await a.locator('xpath=..').inner_text(timeout=300)).strip()
        except Exception:continue
        blob=' '.join([text,parent])[:1000]
        p=money_int(blob)
        if not p or abs(p-expected_price)>max(25,int(expected_price*0.03)):continue
        if not STOCK_RE.search(blob):continue
        host=urlparse(href).netloc
        seller=text.strip() or host or 'Ukendt butik'
        rows.append({'price':p,'seller':seller[:120],'availability':'DOM_STOCK_TEXT','url':href,'method':'DOM_STORE_ROW','evidence_text':blob[:300]})
    uniq=[];seen=set()
    for r in rows:
        key=(r['price'],r['seller'],r['url'])
        if key in seen:continue
        seen.add(key);uniq.append(r)
    return uniq


async def verify_one(context,c:dict,sem:asyncio.Semaphore)->dict:
    async with sem:
        page=await context.new_page();now=datetime.now(timezone.utc).isoformat()
        out={**c,'verified_at':now,'identity_verified':False,'price_verified':False,'concrete_in_stock':False,'store_offer':None,'offers':[]}
        try:
            response=await page.goto(c['url'],wait_until='domcontentloaded',timeout=45000)
            out['http_status']=int(response.status) if response else None
            title=await page.title();h1=''
            try:h1=(await page.locator('h1').first.inner_text(timeout=2500)).strip()
            except Exception:pass
            out['rendered_title']=title;out['rendered_h1']=h1
            if not identity_ok(str(c.get('name') or ''),' '.join([title,h1])):
                out['error']='PRODUCT_IDENTITY_MISMATCH';return out
            out['identity_verified']=True
            scripts=await page.locator('script[type="application/ld+json"]').all_text_contents();blobs=[]
            for text in scripts:
                try:blobs.append(json.loads(text))
                except Exception:pass
            offers=structured_offers(blobs,str(c.get('name') or ''))
            expected=int(c.get('expected_price') or 0)
            close=[x for x in offers if abs(int(x['price'])-expected)<=max(25,int(expected*0.03))]
            dom=await dom_store_rows(page,expected)
            merged=close+dom
            out['offers']=merged[:20]
            out['price_verified']=bool(close or dom)
            stock=[]
            for x in merged:
                av=str(x.get('availability') or '').lower()
                if 'instock' in av or 'in_stock' in av or x.get('method')=='DOM_STORE_ROW':stock.append(x)
            concrete=[x for x in stock if str(x.get('seller') or '').strip()]
            if concrete:
                concrete.sort(key=lambda x:int(x.get('price') or 10**9))
                out['concrete_in_stock']=True;out['store_offer']=concrete[0];out['availability_status']='IN_STOCK_VERIFIED'
            elif out['price_verified']:
                out['availability_status']='PRICE_VERIFIED_STOCK_UNPROVEN'
            else:
                # Existing same-product retail price remains the price truth; this layer only adds stock proof.
                out['availability_status']='STOCK_UNPROVEN'
            return out
        except Exception as exc:
            out['error']=f'{type(exc).__name__}: {str(exc)[:240]}';out['availability_status']='ERROR';return out
        finally:
            await page.close()


async def main()->None:
    data=json.loads(STRATEGY.read_text(encoding='utf-8'))
    assert data.get('model_version')=='DBA-WOW-SELF-BUILD-FIRST-V20'
    selected=selected_retail_components(data)
    assert selected,'No selected NEW RETAIL components'
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True);context=await browser.new_context(locale='da-DK');sem=asyncio.Semaphore(4)
        rows=await asyncio.gather(*(verify_one(context,c,sem) for c in selected))
        await context.close();await browser.close()
    doc={'generated_at':datetime.now(timezone.utc).isoformat(),'model':'V21_SELECTED_RETAIL_AVAILABILITY','selected_total':len(rows),'identity_verified':sum(1 for x in rows if x.get('identity_verified')),'concrete_in_stock':sum(1 for x in rows if x.get('concrete_in_stock')),'rows':rows}
    OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(doc,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'V21_RETAIL_AVAILABILITY':True,'selected':len(rows),'identity_verified':doc['identity_verified'],'concrete_in_stock':doc['concrete_in_stock'],'statuses':{str(x.get('kind')):x.get('availability_status') for x in rows}},ensure_ascii=False))
    assert doc['identity_verified']==len(rows),'V21 availability identity gate failed'


if __name__=='__main__':asyncio.run(main())
