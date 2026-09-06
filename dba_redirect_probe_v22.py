from __future__ import annotations

import asyncio
import json
import re
from playwright.async_api import async_playwright

PRODUCTS = [
    ('ASUS_TUF_B850M', 'https://prisjagt.dk/product.php?p=14022121'),
    ('MSI_A850GL', 'https://prisjagt.dk/product.php?p=15147757'),
]
PRICE_RE = re.compile(r'(?<!\d)(\d{1,3}(?:[. ]\d{3})*|\d{3,5})(?:[,.]\d{2})?\s*kr', re.I)


def vals(text: str) -> list[int]:
    out=[]
    for m in PRICE_RE.finditer(text or ''):
        try: out.append(int(m.group(1).replace('.','').replace(' ','')))
        except Exception: pass
    return out


async def summarize(a, label: str, href: str):
    levels=[]
    for level in range(0,8):
        loc=a if level==0 else a.locator('xpath=' + '/../'*level)
        try:
            text=' '.join((await loc.inner_text(timeout=500)).split())
            hrefs=await loc.locator('a[href*="go-to-shop"]').count()
            imgs=loc.locator('img'); alts=[]
            for i in range(min(await imgs.count(),6)):
                alt=await imgs.nth(i).get_attribute('alt')
                if alt: alts.append(alt)
            tag=await loc.evaluate('(e)=>e.tagName')
            cls=await loc.get_attribute('class')
            role=await loc.get_attribute('role')
            levels.append({
                'level':level,'tag':tag,'class':cls,'role':role,
                'go_links':hrefs,'prices':vals(text),
                'text':text[:700],'img_alts':alts[:6],
            })
        except Exception as exc:
            levels.append({'level':level,'error':f'{type(exc).__name__}:{str(exc)[:100]}'})
    print(json.dumps({'product':label,'href':href,'ancestors':levels},ensure_ascii=False),flush=True)


async def main():
    async with async_playwright() as p:
        b=await p.chromium.launch(headless=True)
        c=await b.new_context(locale='da-DK')
        for label,url in PRODUCTS:
            page=await c.new_page()
            await page.goto(url,wait_until='domcontentloaded',timeout=45000)
            await page.wait_for_timeout(800)
            links=page.locator('a[href*="go-to-shop"]')
            n=min(await links.count(),8)
            print(json.dumps({'product':label,'url':url,'go_to_shop_count':n},ensure_ascii=False),flush=True)
            seen=set()
            for i in range(n):
                a=links.nth(i)
                href=await a.get_attribute('href') or ''
                if not href or href in seen: continue
                seen.add(href)
                await summarize(a,label,href)
                if len(seen)>=3: break
            await page.close()
        await c.close();await b.close()

if __name__=='__main__':
    asyncio.run(main())
