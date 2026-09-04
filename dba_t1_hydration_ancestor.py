from __future__ import annotations

import asyncio
from collections import defaultdict

import dba_browser_v2 as v2
import dba_browser_v3 as v3

IDENTITY_KEYS = {"listingId","listing_id","itemId","item_id","adId","ad_id","sku","productID"}
URL_KEYS = {"url","canonicalUrl","canonical_url","href","link"}
TITLE_KEYS = ("title","name","subject","heading")
PRICE_KEYS = ("askingPrice","salesPrice","priceAmount","price")
PRICE_VALUE_KEYS = ("amount","value","price","askingPrice","salesPrice")
CURRENCY_KEYS = ("currency","currencyCode","priceCurrency")
STATUS_KEYS = ("availability","status","adStatus","listingStatus","lifecycleStatus","state")
TRADE_KEYS = ("tradeType","trade_type")
DESC_KEYS = ("description","body","bodyText","text")
CATEGORY_KEYS = ("categoryName","category","categoryPath")
BRAND_KEYS = ("brandName","brand")


def _walk(value, path=()):
    if isinstance(value, dict):
        yield path, value
        for k, child in value.items():
            if isinstance(child, (dict, list)):
                yield from _walk(child, path + (str(k),))
    elif isinstance(value, list):
        for i, child in enumerate(value):
            if isinstance(child, (dict, list)):
                yield from _walk(child, path + (f"[{i}]",))


def _identity_ids(value) -> set[str]:
    ids=set()
    if isinstance(value, dict):
        for k,v in value.items():
            if k in IDENTITY_KEYS and v is not None:
                s=str(v).strip()
                if s.isdigit(): ids.add(s)
            elif k in URL_KEYS and isinstance(v,str):
                m=v2.ITEM_RE.search(v)
                if m: ids.add(m.group(1))
            if isinstance(v,(dict,list)):
                ids.update(_identity_ids(v))
    elif isinstance(value,list):
        for x in value:
            if isinstance(x,(dict,list)): ids.update(_identity_ids(x))
    return ids


def _node_count(value) -> int:
    if isinstance(value,dict):
        return 1 + sum(_node_count(v) for v in value.values() if isinstance(v,(dict,list)))
    if isinstance(value,list):
        return 1 + sum(_node_count(v) for v in value if isinstance(v,(dict,list)))
    return 0


def _collect_scalars(value, keys) -> list:
    out=[]
    if isinstance(value,dict):
        for k,v in value.items():
            if k in keys and v is not None and not isinstance(v,(dict,list)):
                out.append(v)
            if isinstance(v,(dict,list)):
                out.extend(_collect_scalars(v,keys))
    elif isinstance(value,list):
        for x in value:
            if isinstance(x,(dict,list)): out.extend(_collect_scalars(x,keys))
    return out


def _unique_text(value, keys):
    vals=[]
    for v in _collect_scalars(value,keys):
        s=str(v).strip()
        if s and s not in vals: vals.append(s)
    return vals[0] if len(vals)==1 else None


def _price_candidates(value):
    vals=[]
    if isinstance(value,dict):
        for k,v in value.items():
            if k in PRICE_KEYS:
                if isinstance(v,dict):
                    for vv in _collect_scalars(v,PRICE_VALUE_KEYS):
                        n=v2.parse_number(vv)
                        if n is not None and n>0: vals.append(n)
                elif not isinstance(v,list):
                    n=v2.parse_number(v)
                    if n is not None and n>0: vals.append(n)
            if isinstance(v,(dict,list)):
                vals.extend(_price_candidates(v))
    elif isinstance(value,list):
        for x in value:
            if isinstance(x,(dict,list)): vals.extend(_price_candidates(x))
    return sorted(set(vals))


def _status(value):
    status=_unique_text(value,STATUS_KEYS)
    if not status: return None,None
    norm=status.rstrip('/').lower()
    inactive=any(x in norm for x in ("outofstock","soldout","sold","inactive","deleted","expired","discontinued","closed"))
    active=any(x in norm for x in ("instock","active","published","available","for_sale","forsale"))
    if inactive: return status,False
    if active: return status,True
    return status,None


def _candidate(obj:dict, lid:str, url:str):
    ids=_identity_ids(obj)
    if ids != {lid}: return None
    title=_unique_text(obj,TITLE_KEYS)
    prices=_price_candidates(obj)
    currencies=[]
    for v in _collect_scalars(obj,CURRENCY_KEYS):
        s=str(v).strip().upper()
        if s and s not in currencies: currencies.append(s)
    status,active=_status(obj)
    if not title or len(prices)!=1 or currencies != ["DKK"] or active is None:
        return None
    trade=_unique_text(obj,TRADE_KEYS)
    desc=_unique_text(obj,DESC_KEYS) or ""
    category=_unique_text(obj,CATEGORY_KEYS) or ""
    brand=_unique_text(obj,BRAND_KEYS) or ""
    return {
        "listing_id":lid,"canonical_url":url,"identity_ok":True,
        "identity_evidence":"PAGE_ID+HYDRATION_MINIMAL_UNIQUE_ANCESTOR",
        "title":title,"description":desc,"ask_t1":prices[0],"currency_t1":"DKK",
        "availability_t1":status if not trade else f"{status}; tradeType={trade}",
        "active_t1":active,"category":category,"brand":brand,"t1_at":v2.utcnow(),
        "t1_source":"dba_native_hydration_minimal_unique_ancestor",
        "_node_count":_node_count(obj),
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
            for _,obj in _walk(parsed):
                c=_candidate(obj,listing_id,url)
                if c: candidates.append(c)
        if not candidates: return None
        min_nodes=min(c["_node_count"] for c in candidates)
        finalists=[c for c in candidates if c["_node_count"]==min_nodes]
        core={(c["title"],c["ask_t1"],c["currency_t1"],c["availability_t1"],c["active_t1"]) for c in finalists}
        if len(core)!=1: return None
        out=dict(finalists[0]); out.pop("_node_count",None)
        return out
    finally:
        await page.close()
