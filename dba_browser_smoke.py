from __future__ import annotations
import asyncio, json
from pathlib import Path
from playwright.async_api import async_playwright

URL='https://www.dba.dk/recommerce/forsale/item/24520901'

async def main():
    Path('results').mkdir(exist_ok=True)
    async with async_playwright() as pw:
        b=await pw.chromium.launch(headless=True)
        c=await b.new_context(locale='da-DK', viewport={'width':1440,'height':1100})
        p=await c.new_page()
        r=await p.goto(URL, wait_until='domcontentloaded', timeout=30000)
        await p.wait_for_timeout(2500)
        title=await p.title()
        body=(await p.locator('body').inner_text())[:18000]
        scripts=await p.locator('script').evaluate_all("els=>els.map(s=>s.textContent||'').filter(x=>x.includes('24520901')||x.includes('itemData')||x.includes('listingId')||x.includes('price')).slice(0,12).map(x=>x.slice(0,6000))")
        metas=await p.locator('meta').evaluate_all("els=>els.map(m=>({name:m.name,prop:m.getAttribute('property'),content:m.content})).filter(x=>x.content&&(/24520901|kr|dkk|price/i.test(x.content)||/price|title|url/i.test((x.name||'')+' '+(x.prop||''))))")
        out={'status':r.status if r else None,'url':p.url,'title':title,'body':body,'scripts':scripts,'metas':metas}
        Path('results/dba_smoke.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:out[k] for k in ('status','url','title')},ensure_ascii=False))
        print(body[:4000])
        await b.close()

if __name__=='__main__': asyncio.run(main())
