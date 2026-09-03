from __future__ import annotations

import asyncio
import json
from urllib.parse import quote

import dba_browser_v2 as v2


async def discover_cards_by_article(page, query: str) -> list[dict]:
    """Bind id/url/title/price from one rendered DBA search-card article."""
    url = f"{v2.BASE}/recommerce/forsale/search?q={quote(query)}"
    response = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    if response and response.status >= 400:
        return []
    await v2.dismiss_consent(page)
    try:
        await page.wait_for_selector("article.sf-search-ad", timeout=6000)
    except Exception:
        return []
    for _ in range(3):
        await page.mouse.wheel(0, 1700)
        await page.wait_for_timeout(250)

    rows = await page.locator("article.sf-search-ad").evaluate_all(
        """articles => articles.map(article => {
          const link = article.querySelector('a.sf-search-ad-link[href*="/recommerce/forsale/item/"]')
                    || article.querySelector('a[href*="/recommerce/forsale/item/"]');
          if (!link) return null;
          const m = link.href.match(/\/recommerce\/forsale\/item\/(\d+)/);
          if (!m) return null;
          return {listing_id:m[1], href:link.href, card_text:(article.innerText || '').trim()};
        }).filter(Boolean)"""
    )

    out = []
    seen = set()
    for row in rows:
        lid = str(row.get("listing_id") or "")
        if not lid or lid in seen:
            continue
        seen.add(lid)
        text = row.get("card_text") or ""
        ask = v2.parse_dkk(text)
        title = v2.card_title(text)
        if ask is None or not title or not (500 <= ask <= v2.MAX_PRICE):
            continue
        out.append(
            {
                "listing_id": lid,
                "canonical_url": v2.ITEM_URL.format(listing_id=lid),
                "title": title,
                "ask_t0": ask,
                "currency_t0": "DKK",
                "status_t0": "VISIBLE_LIVE_SEARCH_CARD",
                "card_text": text[:2400],
                "query": query,
                "t0_at": v2.utcnow(),
                "t0_source": "rendered_dba_card",
            }
        )
    return out


async def fetch_jsonld_item_all_scripts(page, listing_id: str) -> dict | None:
    """Read the same listing's Product JSON-LD for T1 with fail-closed identity binding.

    DBA has historically exposed both sku/productID and a canonical item URL, but either
    field may disappear independently during schema changes. The requested rendered page
    URL must always still resolve to the same listing ID, and at least one Product-level
    identifier must independently match that ID. This preserves same-ID binding without
    requiring two redundant JSON-LD fields to exist forever.
    """
    url = v2.ITEM_URL.format(listing_id=listing_id)
    response = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    if response and response.status >= 400:
        return None
    await v2.dismiss_consent(page)
    await page.wait_for_timeout(300)

    page_match = v2.ITEM_RE.search(page.url or "")
    page_id = page_match.group(1) if page_match else ""
    if page_id != listing_id:
        return None

    scripts = await page.locator("script").evaluate_all(
        "els => els.map(s => s.textContent || '').filter(x => x && x.includes('Product') && x.includes('offers'))"
    )

    products: list[dict] = []
    for raw in scripts:
        try:
            parsed = json.loads(raw)
        except Exception:
            continue
        for obj in v2._flatten_jsonld(parsed):
            typ = obj.get("@type")
            types = typ if isinstance(typ, list) else [typ]
            if any(str(x).lower() == "product" for x in types if x is not None):
                products.append(obj)

    for product in products:
        sku = str(product.get("sku") or product.get("productID") or "").strip()
        product_url = str(product.get("url") or "").strip()
        match = v2.ITEM_RE.search(product_url)
        canonical_id = match.group(1) if match else ""

        sku_match = sku == listing_id
        canonical_match = canonical_id == listing_id
        if not (sku_match or canonical_match):
            continue

        offer = v2._offer_from_product(product)
        if not offer:
            continue
        ask = v2.parse_number(offer.get("price"))
        currency = str(offer.get("priceCurrency") or "").upper()
        availability = str(offer.get("availability") or "")
        normalized = availability.rstrip("/").lower()
        active = normalized.endswith("instock")
        inactive = any(normalized.endswith(x) for x in ("outofstock", "discontinued", "soldout"))

        canonical = product_url if canonical_match else url
        identity_evidence = (
            "PAGE_ID+SKU+PRODUCT_URL"
            if sku_match and canonical_match
            else "PAGE_ID+SKU"
            if sku_match
            else "PAGE_ID+PRODUCT_URL"
        )

        return {
            "listing_id": listing_id,
            "canonical_url": canonical,
            "identity_ok": True,
            "identity_evidence": identity_evidence,
            "title": str(product.get("name") or "").strip(),
            "description": str(product.get("description") or ""),
            "ask_t1": ask,
            "currency_t1": currency,
            "availability_t1": availability,
            "active_t1": bool(active and not inactive and ask is not None and currency == "DKK"),
            "category": v2._category_from_product(product),
            "brand": str(product.get("brand") or ""),
            "t1_at": v2.utcnow(),
            "t1_source": "dba_jsonld_product_all_scripts",
        }
    return None


v2.discover_cards = discover_cards_by_article
v2.fetch_jsonld_item = fetch_jsonld_item_all_scripts


if __name__ == "__main__":
    asyncio.run(v2.main())
