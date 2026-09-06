from __future__ import annotations
import asyncio,json
from playwright.async_api import async_playwright

URL='https://prisjagt.dk/product.php?p=14356470'

async def main():
    async with async_playwright() as p:
        b=await p.chromium.launch(headless=True);c=await b.new_context(locale='da-DK')
        page=await c.new_page();await page.goto(URL,wait_until='domcontentloaded',timeout=45000)
        links=page.locator('a');n=min(await links.count(),500);found=[]
        for i in range(n):
            a=links.nth(i)
            try:
                href=await a.get_attribute('href') or '';txt=(await a.inner_text(timeout=300)).strip()
            except Exception:continue
            if 'go-to-shop' in href:
                found.append((href,txt))
                if len(found)>=3:break
        print(json.dumps({'found':found},ensure_ascii=False),flush=True)
        for href,txt in found[:1]:
            q=await c.new_page()
            try:
                resp=await q.goto(href,wait_until='domcontentloaded',timeout=30000)
                await q.wait_for_timeout(1500)
                print(json.dumps({'href':href,'final_url':q.url,'title':await q.title(),'status':resp.status if resp else None},ensure_ascii=False),flush=True)
            except Exception as e:print(json.dumps({'href':href,'error':f'{type(e).__name__}:{e}','final_url':q.url},ensure_ascii=False),flush=True)
            finally:await q.close()
        await c.close();await b.close()
if __name__=='__main__':asyncio.run(main())
