from __future__ import annotations
import asyncio, json, re
from pathlib import Path
from playwright.async_api import async_playwright

URL='https://www.dba.dk/recommerce/forsale/search?q=gaming%20pc'

async def main():
    Path('results').mkdir(exist_ok=True)
    async with async_playwright() as pw:
        b=await pw.chromium.launch(headless=True)
        c=await b.new_context(locale='da-DK', viewport={'width':1440,'height':1100})
        p=await c.new_page()
        r=await p.goto(URL, wait_until='domcontentloaded', timeout=30000)
        await p.wait_for_timeout(2500)
        title=await p.title()
        body=(await p.locator('body').inner_text())[:12000]
        links=await p.locator('a[href*="/recommerce/forsale/item/"]').evaluate_all("els=>els.slice(0,40).map(a=>({href:a.href,text:(a.innerText||'').trim()}))")
        scripts=await p.locator('script').evaluate_all("els=>els.map(s=>s.textContent||'').filter(x=>x.includes('/recommerce/forsale/item/')||x.includes('itemData')||x.includes('listingId')).slice(0,8).map(x=>x.slice(0,4000))")
        out={'status':r.status if r else None,'url':p.url,'title':title,'item_link_count':len(links),'links':links,'body':body,'scripts':scripts}
        Path('results/dba_smoke.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:out[k] for k in ('status','url','title','item_link_count')},ensure_ascii=False))
        print(body[:2500])
        await b.close()

if __name__=='__main__': asyncio.run(main())
