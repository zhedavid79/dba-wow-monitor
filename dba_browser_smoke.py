from __future__ import annotations
import asyncio, json
from pathlib import Path
from playwright.async_api import async_playwright
import dba_browser_v2 as v2
from dba_browser_v3 import fetch_jsonld_item_all_scripts

TARGET='24520901'

async def main():
    Path('results').mkdir(exist_ok=True)
    async with async_playwright() as pw:
        b=await pw.chromium.launch(headless=True)
        c=await b.new_context(locale='da-DK', viewport={'width':1440,'height':1100})
        search=await c.new_page()
        item=await c.new_page()
        cards=await v2.discover_cards(search,'gaming pc')
        card=next((x for x in cards if x.get('listing_id')==TARGET), None)
        t1=await fetch_jsonld_item_all_scripts(item,TARGET)
        out={'target':TARGET,'card_count':len(cards),'t0':card,'t1':t1}
        Path('results/dba_smoke.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(out,ensure_ascii=False))
        await b.close()

if __name__=='__main__': asyncio.run(main())
