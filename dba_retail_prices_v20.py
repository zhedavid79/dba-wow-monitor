from __future__ import annotations

import asyncio
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

from playwright.async_api import async_playwright

import dba_component_market_v19 as market
import dba_retail_prices_v19 as base

OUT = Path('results/retail_prices_latest.json')
DISCOVERY_OUT = Path('results/retail_discovery_v20.json')

# These are search/category pages, not product IDs. Product URLs are discovered each run.
DISCOVERY_SEEDS = {
    'MOTHERBOARD':['https://prisjagt.dk/s/650-600/'],
    'PSU':['https://prisjagt.dk/s/atx-31/'],
    'COOLER':['https://prisjagt.dk/s/pc-koler/'],
    'RAM':['https://prisjagt.dk/s/ddr5-6000mhz-32gb/'],
    'STORAGE':['https://prisjagt.dk/s/nvme-ssd-1tb/'],
}
MAX_LINKS_PER_SEED = 8


def _norm(s: str) -> str:
    return re.sub(r'\s+',' ',str(s or '')).strip()


def _sku(url: str) -> str:
    return 'DISC_' + hashlib.sha1(url.encode('utf-8')).hexdigest()[:12].upper()


def _int(pattern: str, text: str, default=0, flags=re.I|re.S):
    m = re.search(pattern,text,flags)
    return int(m.group(1)) if m else default


def _float(pattern: str, text: str, default=0.0, flags=re.I|re.S):
    m = re.search(pattern,text,flags)
    return float(m.group(1).replace(',','.')) if m else default


def infer_candidate(kind: str, name: str, body: str, url: str, price: int, availability: str, verified_at: str) -> tuple[dict|None,list[str]]:
    text = _norm(name + '\n' + body[:30000])
    low = text.lower()
    common = {
        'sku':_sku(url),'name':_norm(name),'price':int(price),'url':url,'identity_aliases':[_norm(name)],
        'source':'NEW RETAIL','verified_at':verified_at,'availability':availability,
        'price_evidence':'LIVE_RETAIL_DISCOVERY','dynamic_discovery_v20':True,
    }
    missing=[]
    if kind == 'RAM':
        cap = 32 if re.search(r'\b32\s*gb\b',text,re.I) else 64 if re.search(r'\b64\s*gb\b',text,re.I) else 0
        speed = _int(r'\b(5[6-9]00|6[0-9]00|7[0-9]00)\s*(?:mhz|mt)',text)
        kit = 2 if re.search(r'\b2\s*[x×]\s*16\s*gb\b|\b2\s*(?:stk|modules?).*?16\s*gb\b',text,re.I) else 0
        cl = _int(r'\bcl\s*([2345]\d)\b',text,0)
        desktop = bool('ddr5' in low and not re.search(r'\bso[- ]?dimm|sodimm|rdimm|registered|server\b',text,re.I))
        if cap < 32: missing.append('<32GB')
        if speed < 5600: missing.append('speed<5600/unproven')
        if kit != 2: missing.append('2x16 kit unproven')
        if not desktop: missing.append('desktop DDR5 unproven')
        if missing: return None,missing
        return common | {'kind':'RAM','capacity_gb':cap,'speed_mt':speed,'cl':cl or None,'kit_dimms':kit,'expo':bool(re.search(r'\bexpo\b',text,re.I)),'desktop_ddr5':True},[]

    if kind == 'STORAGE':
        cap = 2000 if re.search(r'\b2\s*tb\b',text,re.I) else 1000 if re.search(r'\b1\s*tb\b|\b1000\s*gb\b',text,re.I) else 0
        nvme = bool(re.search(r'\bnvme\b',text,re.I))
        if cap < 1000: missing.append('<1TB')
        if not nvme: missing.append('NVMe unproven')
        if missing: return None,missing
        seq = _int(r'(\d{4,5})\s*mb/s',text,0)
        warranty = _int(r'(\d)\s*(?:års?|year)\s*(?:garanti|warranty)',text,0)
        tbw = _int(r'\b(\d{3,4})\s*tbw\b',text,0)
        return common | {'kind':'STORAGE','capacity_gb':cap,'nvme':True,'seq_read_mb':seq,'warranty_years':warranty,'tbw':tbw},[]

    if kind == 'MOTHERBOARD':
        model_ok = bool(re.search(r'\b(?:b650m|b850m)\b',text,re.I))
        matx = bool(re.search(r'\bmicro[- ]?atx\b|\bm-?atx\b',text,re.I))
        am5 = bool(re.search(r'\bam5\b|amd socket am5',text,re.I))
        ddr5 = bool(re.search(r'\bddr5\b',text,re.I))
        wifi = '7' if re.search(r'wi-?fi\s*7',text,re.I) else '6E' if re.search(r'wi-?fi\s*6e',text,re.I) else '6' if re.search(r'wi-?fi|wifi|wireless',text,re.I) else ''
        dimm = 4 if re.search(r'\b4\s*(?:x|stk)?\s*(?:dimm|ram(?: slots?)?)\b|(?:dimm|ram slots?).{0,20}\b4\b',text,re.I) else 0
        m2 = _int(r'\b([234])\s*(?:x|stk)?\s*m\.?2\b',text,0)
        lan = 2.5 if re.search(r'\b2[.,]5\s*(?:g|gbe|gbps)',text,re.I) else 0.0
        for ok,label in ((model_ok,'B650M/B850M'),(matx,'mATX'),(am5,'AM5'),(ddr5,'DDR5'),(bool(wifi),'Wi-Fi'),(dimm>=4,'4 DIMM'),(m2>=2,'>=2 M.2'),(lan>=2.5,'2.5GbE')):
            if not ok: missing.append(label+' unproven')
        if missing: return None,missing
        tier = 2 if re.search(r'\bdrmos\b|power phase|vrm',text,re.I) else 1
        return common | {'kind':'MOTHERBOARD','socket':'AM5','form_factor':'mATX','ddr':'DDR5','dimm_slots':dimm,'wifi':wifi,'lan_gbps':lan,'m2_count':m2,'pcie5_m2':bool(re.search(r'pcie\s*5(?:\.0)?.{0,40}m\.?2|m\.?2.{0,40}pcie\s*5',text,re.I)),'pcie5_x16':bool(re.search(r'pcie\s*5(?:\.0)?.{0,20}x16',text,re.I)),'power_tier':tier,'drmos':bool(re.search(r'\bdrmos\b',text,re.I)),'bios_flashback':bool(re.search(r'flashback|flash bios|q-flash plus',text,re.I)),'front_usb_c':bool(re.search(r'front.{0,20}(?:usb[- ]?c|type[- ]?c)|(?:usb[- ]?c|type[- ]?c).{0,20}front',text,re.I))},[]

    if kind == 'PSU':
        watt = _int(r'\b(750|850|1000|1200)\s*w\b',text,0)
        atx31 = bool(re.search(r'\batx\s*3[.,]?[01]\b',text,re.I))
        modular = bool(re.search(r'helmodul|fully\s+modular|full\s+modular',text,re.I))
        length = _int(r'(?:length|længde|dybde|depth).{0,20}\b(1[23456]\d)\s*mm\b',text,0)
        if watt < 750: missing.append('<750W')
        if not atx31: missing.append('ATX3.x unproven')
        if not modular: missing.append('modular unproven')
        if not length or length > 160: missing.append('<=160mm length unproven')
        if missing: return None,missing
        return common | {'kind':'PSU','watt':watt,'atx31':True,'modular':True,'length_mm':length,'gold':bool(re.search(r'\bgold\b|\bguld\b',text,re.I))},[]

    if kind == 'COOLER':
        am5 = bool(re.search(r'\bam5\b',text,re.I))
        height = _int(r'(?:height|højde|højde på|dimensions?).{0,30}\b(1[0-6]\d)\s*mm\b',text,0)
        if not am5: missing.append('AM5 unproven')
        if not height or height > 163: missing.append('<=163mm height unproven')
        if missing: return None,missing
        return common | {'kind':'COOLER','am5':True,'height_mm':height,'cooling_tier':2},[]

    return None,['unsupported category']


async def discover_seed(context, kind: str, url: str, sem: asyncio.Semaphore) -> dict:
    async with sem:
        page = await context.new_page()
        out={'kind':kind,'seed':url,'ok':False,'links':[],'error':None}
        try:
            response=await page.goto(url,wait_until='domcontentloaded',timeout=45000)
            out['http_status']=int(response.status) if response else None
            hrefs=await page.locator('a').evaluate_all("els => els.map(a => a.href).filter(Boolean)")
            links=[]
            for href in hrefs:
                if 'prisjagt.dk/product.php?p=' not in href: continue
                clean=href.split('#')[0]
                if clean not in links: links.append(clean)
                if len(links)>=MAX_LINKS_PER_SEED: break
            out['links']=links; out['ok']=bool(links) and (out['http_status'] or 500)<400
        except Exception as exc:
            out['error']=f'{type(exc).__name__}: {str(exc)[:200]}'
        finally:
            await page.close()
        return out


async def inspect_dynamic(context, kind: str, url: str, sem: asyncio.Semaphore) -> dict:
    async with sem:
        page=await context.new_page(); now=datetime.now(timezone.utc).isoformat()
        result={'kind':kind,'url':url,'verified':False,'admitted':False,'verified_at':now}
        try:
            response=await page.goto(url,wait_until='domcontentloaded',timeout=45000)
            result['http_status']=int(response.status) if response else None
            scripts=await page.locator('script[type="application/ld+json"]').all_text_contents(); products=[]
            for text in scripts:
                try: blob=json.loads(text)
                except Exception: continue
                for d in base.walk(blob):
                    typ=d.get('@type'); types=typ if isinstance(typ,list) else [typ]
                    if any(str(x).lower()=='product' for x in types if x): products.append(d)
            if not products:
                result['error']='NO_JSON_LD_PRODUCT'; return result
            chosen=None
            for prod in products:
                offers=prod.get('offers'); objs=offers if isinstance(offers,list) else [offers] if isinstance(offers,dict) else []
                prices=[]
                for o in objs:
                    p=base.numeric_price(o.get('price')) or base.numeric_price(o.get('lowPrice'))
                    if p: prices.append((p,o))
                if prices:
                    prices.sort(key=lambda x:x[0]); chosen=(prod,prices[0][0],prices[0][1]); break
            if not chosen:
                result['error']='NO_LIVE_OFFER'; return result
            prod,price,offer=chosen; name=str(prod.get('name') or await page.title())
            body=(await page.locator('body').inner_text(timeout=7000))[:40000]
            availability=str(offer.get('availability') or 'AVAILABLE_COMPARISON')
            cand,missing=infer_candidate(kind,name,body,url,price,availability,now)
            result.update({'verified':True,'name':name,'price':price,'availability':availability,'missing_evidence':missing})
            if cand:
                result['admitted']=True; result['candidate']=cand
            return result
        except Exception as exc:
            result['error']=f'{type(exc).__name__}: {str(exc)[:200]}'; return result
        finally:
            await page.close()


async def main() -> None:
    static_products=[]
    for kind,rows in market.RETAIL_CANDIDATES.items():
        for row in rows:
            x=dict(row); x['kind']=kind; static_products.append(x)

    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True); context=await browser.new_context(locale='da-DK')
        verify_sem=asyncio.Semaphore(4)
        static_rows=await asyncio.gather(*(base.verify_one(context,x,verify_sem) for x in static_products))
        seed_sem=asyncio.Semaphore(3)
        seed_rows=await asyncio.gather(*(discover_seed(context,kind,url,seed_sem) for kind,urls in DISCOVERY_SEEDS.items() for url in urls))
        discovered=[]; seen=set()
        for seed in seed_rows:
            for url in seed.get('links') or []:
                if url in seen: continue
                seen.add(url); discovered.append((seed['kind'],url))
        dyn_sem=asyncio.Semaphore(5)
        dynamic_rows=await asyncio.gather(*(inspect_dynamic(context,kind,url,dyn_sem) for kind,url in discovered))
        await context.close(); await browser.close()

    static_ok=all(r.get('verified') is True and int(r.get('price') or 0)>0 for r in static_rows)
    discovery_ok=all(r.get('ok') is True for r in seed_rows)
    admitted=[r['candidate'] for r in dynamic_rows if r.get('admitted') and r.get('candidate')]

    # Products remains compatible with the V19 same-product snapshot reader: static
    # verifier rows plus fully admitted dynamic rows. Unresolved discovery is kept only
    # in the audit sidecar and can never win.
    product_rows=list(static_rows)
    for c in admitted:
        product_rows.append({**c,'verified':True,'method':'JSON_LD_DISCOVERED_PRODUCT'})

    counts={'static_total':len(static_rows),'static_verified':sum(1 for r in static_rows if r.get('verified')),'seed_total':len(seed_rows),'seed_ok':sum(1 for r in seed_rows if r.get('ok')),'dynamic_inspected':len(dynamic_rows),'dynamic_admitted':len(admitted),'total_products':len(product_rows)}
    doc={'generated_at':datetime.now(timezone.utc).isoformat(),'model':'V20_DYNAMIC_RETAIL_SAME_PRODUCT_GATE','required_motherboard_gate_passed':all(r.get('verified') for r in static_rows if r.get('sku') in {str(x['sku']) for x in market.RETAIL_CANDIDATES.get('MOTHERBOARD') or []}),'all_catalog_products_verified':static_ok,'dynamic_discovery_gate_passed':discovery_ok,'products':product_rows,'dynamic_admitted_products':admitted,'counts':counts}
    audit={'generated_at':doc['generated_at'],'model':'V20_RETAIL_DISCOVERY_AUDIT','seeds':seed_rows,'dynamic_results':dynamic_rows,'counts':counts,'gate_passed':discovery_ok}
    OUT.parent.mkdir(parents=True,exist_ok=True); OUT.write_text(json.dumps(doc,ensure_ascii=False,indent=2),encoding='utf-8'); DISCOVERY_OUT.write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'V20_RETAIL':True,**counts,'static_gate':static_ok,'discovery_gate':discovery_ok},ensure_ascii=False),flush=True)
    if not static_ok: raise SystemExit('V20 RETAIL GATE FAILED: static known catalog same-product verification incomplete')
    if not discovery_ok: raise SystemExit('V20 RETAIL DISCOVERY GATE FAILED: at least one required market discovery seed produced no product links')


if __name__=='__main__':
    asyncio.run(main())
