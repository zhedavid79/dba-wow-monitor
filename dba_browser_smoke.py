from __future__ import annotations
import asyncio, json
from pathlib import Path
from playwright.async_api import async_playwright
from dba_browser_v3 import fetch_jsonld_item_all_scripts

TARGET='24520901'
SEARCH='https://www.dba.dk/recommerce/forsale/search?q=gaming%20pc'

async def main():
    Path('results').mkdir(exist_ok=True)
    async with async_playwright() as pw:
        b=await pw.chromium.launch(headless=True)
        c=await b.new_context(locale='da-DK', viewport={'width':1440,'height':1100})
        search=await c.new_page(); item=await c.new_page()
        await search.goto(SEARCH,wait_until='domcontentloaded',timeout=30000)
        await search.wait_for_timeout(2500)
        diag=await search.evaluate("""(target)=>{
          const a=[...document.querySelectorAll('a[href*="/recommerce/forsale/item/"]')].find(x=>x.href.includes('/item/'+target));
          if(!a) return {found:false};
          const ancestors=[]; let n=a;
          for(let i=0;i<22&&n;i++,n=n.parentElement){ancestors.push({i,tag:n.tagName,cls:n.className||'',role:n.getAttribute('role'),text:(n.innerText||'').trim().slice(0,3500),html:n.outerHTML.slice(0,1200)});}
          return {found:true,href:a.href,anchorText:(a.innerText||'').trim(),ancestors};
        }""",TARGET)
        t1=await fetch_jsonld_item_all_scripts(item,TARGET)
        out={'target':TARGET,'dom':diag,'t1':t1}
        Path('results/dba_smoke.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'found':diag.get('found'),'ancestor_count':len(diag.get('ancestors',[])),'t1_ok':bool(t1)},ensure_ascii=False))
        await b.close()

if __name__=='__main__': asyncio.run(main())
