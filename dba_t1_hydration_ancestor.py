from __future__ import annotations

import asyncio

import dba_browser_v2 as v2
import dba_browser_v3 as v3

PRICE_KEY_TOKENS=("price","amount","askingprice","salesprice")
CURRENCY_KEYS={"currency","currencycode","pricecurrency"}


def _walk(value,path=()):
    if isinstance(value,dict):
        yield path,value
        for k,v in value.items():
            if isinstance(v,(dict,list)):
                yield from _walk(v,path+(str(k),))
    elif isinstance(value,list):
        for i,v in enumerate(value):
            if isinstance(v,(dict,list)):
                yield from _walk(v,path+(f"[{i}]",))


def _collect_price_values(value):
    vals=[]
    if isinstance(value,dict):
        for k,v in value.items():
            lk=str(k).lower()
            if any(tok in lk for tok in PRICE_KEY_TOKENS):
                if isinstance(v,(str,int,float)):
                    n=v2.parse_number(v)
                    if n is not None and 0 < n <= 100000:
                        vals.append(n)
                elif isinstance(v,dict):
                    for kk,vv in v.items():
                        if str(kk).lower() in {"amount","value","price","askingprice","salesprice"} and isinstance(vv,(str,int,float)):
                            n=v2.parse_number(vv)
                            if n is not None and 0 < n <= 100000:
                                vals.append(n)
            if isinstance(v,(dict,list)):
                vals.extend(_collect_price_values(v))
    elif isinstance(value,list):
        for v in value:
            if isinstance(v,(dict,list)):
                vals.extend(_collect_price_values(v))
    return sorted(set(vals))


def _collect_currencies(value):
    vals=[]
    if isinstance(value,dict):
        for k,v in value.items():
            if str(k).lower() in CURRENCY_KEYS and isinstance(v,str):
                s=v.strip().upper()
                if s and s not in vals:
                    vals.append(s)
            if isinstance(v,(dict,list)):
                for s in _collect_currencies(v):
                    if s not in vals: vals.append(s)
    elif isinstance(value,list):
        for v in value:
            if isinstance(v,(dict,list)):
                for s in _collect_currencies(v):
                    if s not in vals: vals.append(s)
    return vals


def _find_item_recommerce(parsed):
    if not isinstance(parsed,dict): return None
    loader=parsed.get("loaderData")
    if not isinstance(loader,dict): return None
    record=loader.get("item-recommerce")
    return record if isinstance(record,dict) else None


def _candidate_from_item_recommerce(parsed:dict,lid:str,url:str):
    record=_find_item_recommerce(parsed)
    if not record: return None
    item_data=record.get("itemData")
    item_meta=item_data.get("meta") if isinstance(item_data,dict) else None
    page_meta=record.get("meta")
    if not isinstance(item_meta,dict) or not isinstance(page_meta,dict): return None

    ad_id=str(item_meta.get("adId") or "").strip()
    canonical=str(page_meta.get("canonical") or "").strip()
    cm=v2.ITEM_RE.search(canonical)
    canonical_id=cm.group(1) if cm else ""
    if ad_id != lid or canonical_id != lid:
        return None

    title=str(page_meta.get("title") or "").strip()
    if title.endswith(" | DBA"):
        title=title[:-6].rstrip()
    description=str(page_meta.get("description") or "")
    inactive=item_meta.get("isInactive")
    published=item_meta.get("hasBeenPublished")
    if not isinstance(inactive,bool) or not isinstance(published,bool):
        return None

    prices=_collect_price_values(record)
    currencies=_collect_currencies(record)
    if len(prices) != 1:
        return None
    if currencies != ["DKK"]:
        return None
    if not title:
        return None

    active=bool(published and not inactive)
    status=f"hasBeenPublished={published}; isInactive={inactive}"
    return {
        "listing_id":lid,
        "canonical_url":canonical,
        "identity_ok":True,
        "identity_evidence":"PAGE_ID+ITEM_RECOMMERCE_ITEMDATA_META_ADID+RECORD_META_CANONICAL",
        "title":title,
        "description":description,
        "ask_t1":prices[0],
        "currency_t1":"DKK",
        "availability_t1":status,
        "active_t1":active,
        "category":"",
        "brand":"",
        "t1_at":v2.utcnow(),
        "t1_source":"dba_native_hydration_item_recommerce_same_record",
    }


async def fetch_hydration_ancestor(context, listing_id:str):
    page=await context.new_page()
    url=v2.ITEM_URL.format(listing_id=listing_id)
    try:
        response=await asyncio.wait_for(page.goto(url,wait_until="domcontentloaded",timeout=30000),timeout=35)
        if response and response.status>=400: return None
        await v2.dismiss_consent(page)
        await page.wait_for_timeout(300)
        m=v2.ITEM_RE.search(page.url or "")
        if not m or m.group(1)!=listing_id: return None
        scripts=await page.locator("script").evaluate_all(
            "els => els.map(s => s.textContent || '').filter(x => x && (x.includes('__staticRouterHydrationData') || x.includes('JSON.parse(')))"
        )
        candidates=[]
        for raw in scripts:
            parsed=v3._decode_hydration_script(raw)
            if parsed is None: continue
            c=_candidate_from_item_recommerce(parsed,listing_id,url)
            if c: candidates.append(c)
        if not candidates: return None
        core={(c["title"],c["ask_t1"],c["currency_t1"],c["availability_t1"],c["active_t1"],c["canonical_url"]) for c in candidates}
        if len(core)!=1: return None
        return candidates[0]
    finally:
        await page.close()
