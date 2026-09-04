from __future__ import annotations

import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright

import dba_browser_v2 as v2
import dba_browser_v3 as v3

TARGET_IDS = ["13706404", "24293467", "24486076", "24490427", "24490663", "24590649"]


def walk(value, path="$", depth=0, max_depth=14):
    if depth > max_depth:
        return
    if isinstance(value, dict):
        yield path, value
        for k, child in value.items():
            if isinstance(child, (dict, list)):
                yield from walk(child, f"{path}.{k}", depth + 1, max_depth)
    elif isinstance(value, list):
        for i, child in enumerate(value):
            if isinstance(child, (dict, list)):
                yield from walk(child, f"{path}[{i}]", depth + 1, max_depth)


def scalar_preview(obj: dict):
    keep = {}
    for k, v in obj.items():
        if isinstance(v, (dict, list)):
            continue
        s = str(v)
        if len(s) > 280:
            s = s[:280] + "…"
        keep[k] = s
    return keep


def contains_listing_id(obj: dict, lid: str) -> bool:
    for v in obj.values():
        if isinstance(v, (dict, list)):
            continue
        s = str(v)
        if s == lid or f"/item/{lid}" in s:
            return True
    return False


async def probe_one(context, lid: str):
    page = await context.new_page()
    url = v2.ITEM_URL.format(listing_id=lid)
    try:
        response = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await v2.dismiss_consent(page)
        await page.wait_for_timeout(300)
        scripts = await page.locator("script").evaluate_all(
            "els => els.map((s,i) => ({i, type:s.type||'', text:s.textContent||''})).filter(x => x.text && (x.text.includes('__staticRouterHydrationData') || x.text.includes('JSON.parse(')))"
        )
        decoded=[]
        matches=[]
        for script in scripts:
            parsed=v3._decode_hydration_script(script.get("text") or "")
            if parsed is None:
                decoded.append({"script_index":script.get("i"),"decoded":False,"len":len(script.get("text") or "")})
                continue
            decoded.append({"script_index":script.get("i"),"decoded":True,"len":len(script.get("text") or ""),"root_type":type(parsed).__name__})
            for path,obj in walk(parsed):
                if contains_listing_id(obj,lid):
                    matches.append({"script_index":script.get("i"),"path":path,"keys":list(obj.keys())[:80],"scalars":scalar_preview(obj)})
        return {
            "listing_id":lid,
            "http_status":response.status if response else None,
            "rendered_url":page.url,
            "script_count":len(scripts),
            "decoded":decoded,
            "identity_object_matches":matches[:40],
        }
    finally:
        await page.close()


async def main():
    Path("results").mkdir(exist_ok=True)
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(headless=True)
        context=await browser.new_context(locale="da-DK", viewport={"width":1440,"height":1100})
        try:
            out=[]
            for lid in TARGET_IDS:
                row=await probe_one(context,lid)
                out.append(row)
                print(json.dumps({"stage":"T1_SCHEMA_PROBE","result":row},ensure_ascii=False),flush=True)
        finally:
            await context.close(); await browser.close()
    Path("results/t1_schema_probe.json").write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")

if __name__ == "__main__":
    asyncio.run(main())
