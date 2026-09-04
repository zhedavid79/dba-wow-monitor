from __future__ import annotations

import asyncio
import re

import dba_browser_v2 as v2
import dba_browser_v3 as v3

DKK_TEXT_RE = re.compile(r"(?:\bkr\.?\b|DKK)", re.I)


def _find_item_recommerce(parsed):
    if not isinstance(parsed, dict):
        return None
    loader = parsed.get("loaderData")
    if not isinstance(loader, dict):
        return None
    record = loader.get("item-recommerce")
    return record if isinstance(record, dict) else None


def _price_texts(record: dict) -> list[str]:
    """Return only explicit UI price labels from the same item-recommerce record."""
    ui = record.get("transactableUiData")
    if not isinstance(ui, dict):
        return []
    sections = ui.get("sections")
    if not isinstance(sections, dict):
        return []
    sidebar = sections.get("sidebar")
    if not isinstance(sidebar, dict):
        return []

    out = []
    for branch_name in ("optedIn", "notOptedIn"):
        branch = sidebar.get(branch_name)
        if not isinstance(branch, dict):
            continue
        value = branch.get("priceText")
        if isinstance(value, str) and value.strip():
            out.append(value.strip())
    return out


def _trade_type_texts(record: dict) -> list[str]:
    ui = record.get("transactableUiData")
    if not isinstance(ui, dict):
        return []
    sections = ui.get("sections")
    if not isinstance(sections, dict):
        return []
    sidebar = sections.get("sidebar")
    if not isinstance(sidebar, dict):
        return []

    out = []
    for branch_name in ("optedIn", "notOptedIn"):
        branch = sidebar.get(branch_name)
        if not isinstance(branch, dict):
            continue
        for key in ("tradeType", "tradeTypeText"):
            value = branch.get(key)
            if isinstance(value, str) and value.strip():
                out.append(value.strip())
    return out


def _candidate_from_item_recommerce(parsed: dict, lid: str, url: str):
    """Parse the documented DBA loaderData.item-recommerce listing record fail-closed.

    Identity/status/price/title/canonical all come from the same item-recommerce record.
    The authoritative numeric ASK is itemData.price. Currency is accepted as DKK only
    when an explicit same-record priceText contains kr./DKK and parses to the same ASK.
    """
    record = _find_item_recommerce(parsed)
    if not record:
        return None

    item_data = record.get("itemData")
    item_meta = item_data.get("meta") if isinstance(item_data, dict) else None
    page_meta = record.get("meta")
    if not isinstance(item_data, dict) or not isinstance(item_meta, dict) or not isinstance(page_meta, dict):
        return None

    ad_id = str(item_meta.get("adId") or "").strip()
    canonical = str(page_meta.get("canonical") or "").strip()
    cm = v2.ITEM_RE.search(canonical)
    canonical_id = cm.group(1) if cm else ""
    if ad_id != lid or canonical_id != lid:
        return None

    title = str(item_data.get("title") or page_meta.get("title") or "").strip()
    if title.endswith(" | DBA"):
        title = title[:-6].rstrip()
    description = str(page_meta.get("description") or "")
    if not title:
        return None

    inactive = item_meta.get("isInactive")
    published = item_meta.get("hasBeenPublished")
    if not isinstance(inactive, bool) or not isinstance(published, bool):
        return None

    ask = v2.parse_number(item_data.get("price"))
    if ask is None or ask <= 0 or ask > 100000:
        return None

    price_texts = _price_texts(record)
    if not price_texts:
        return None

    verified_price_texts = []
    for text in price_texts:
        if not DKK_TEXT_RE.search(text):
            continue
        parsed_text_price = v2.parse_dkk(text)
        if parsed_text_price == ask:
            verified_price_texts.append(text)

    if not verified_price_texts:
        return None

    active = bool(published and not inactive)
    trade_texts = _trade_type_texts(record)
    status = f"hasBeenPublished={published}; isInactive={inactive}"
    if trade_texts:
        status += "; " + "; ".join(trade_texts)

    return {
        "listing_id": lid,
        "canonical_url": canonical,
        "identity_ok": True,
        "identity_evidence": "PAGE_ID+ITEM_RECOMMERCE_ITEMDATA_META_ADID+RECORD_META_CANONICAL",
        "title": title,
        "description": description,
        "ask_t1": ask,
        "currency_t1": "DKK",
        "availability_t1": status,
        "active_t1": active,
        "category": str((item_data.get("category") or {}).get("value") or "") if isinstance(item_data.get("category"), dict) else "",
        "brand": "",
        "t1_at": v2.utcnow(),
        "t1_source": "dba_native_hydration_item_recommerce_itemdata_price",
        "t1_price_evidence": {
            "numeric_path": "loaderData.item-recommerce.itemData.price",
            "price_text": verified_price_texts[0],
        },
    }


async def fetch_hydration_ancestor(context, listing_id: str):
    page = await context.new_page()
    url = v2.ITEM_URL.format(listing_id=listing_id)
    try:
        response = await asyncio.wait_for(
            page.goto(url, wait_until="domcontentloaded", timeout=30000), timeout=35
        )
        if response and response.status >= 400:
            return None
        await v2.dismiss_consent(page)
        await page.wait_for_timeout(300)

        m = v2.ITEM_RE.search(page.url or "")
        if not m or m.group(1) != listing_id:
            return None

        scripts = await page.locator("script").evaluate_all(
            "els => els.map(s => s.textContent || '').filter(x => x && (x.includes('__staticRouterHydrationData') || x.includes('JSON.parse(')))"
        )
        candidates = []
        for raw in scripts:
            parsed = v3._decode_hydration_script(raw)
            if parsed is None:
                continue
            candidate = _candidate_from_item_recommerce(parsed, listing_id, url)
            if candidate:
                candidates.append(candidate)

        if not candidates:
            return None

        core = {
            (
                c["title"],
                c["ask_t1"],
                c["currency_t1"],
                c["availability_t1"],
                c["active_t1"],
                c["canonical_url"],
            )
            for c in candidates
        }
        if len(core) != 1:
            return None
        return candidates[0]
    finally:
        await page.close()
