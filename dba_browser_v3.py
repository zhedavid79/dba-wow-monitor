from __future__ import annotations

import asyncio
import json

import dba_browser_v2 as v2


async def fetch_jsonld_item_all_scripts(page, listing_id: str) -> dict | None:
    """Read DBA's Product JSON from any script element.

    DBA currently emits the canonical Product payload as valid JSON containing
    @type=Product, sku, canonical url and nested offers. The script's `type`
    attribute is not stable in headless rendering, so source validation is based
    on the JSON object's own schema/identity, not a DOM attribute.
    """
    url = v2.ITEM_URL.format(listing_id=listing_id)
    response = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    if response and response.status >= 400:
        return None
    await v2.dismiss_consent(page)
    await page.wait_for_timeout(300)

    scripts = await page.locator("script").evaluate_all(
        "els => els.map(s => s.textContent || '').filter(x => x && x.includes('Product') && (x.includes('sku') || x.includes('productID')) && x.includes('offers'))"
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
        sku = str(product.get("sku") or product.get("productID") or "")
        canonical = str(product.get("url") or "")
        match = v2.ITEM_RE.search(canonical)
        canonical_id = match.group(1) if match else ""
        if sku != listing_id or canonical_id != listing_id:
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

        return {
            "listing_id": listing_id,
            "canonical_url": canonical,
            "identity_ok": True,
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


v2.fetch_jsonld_item = fetch_jsonld_item_all_scripts


if __name__ == "__main__":
    asyncio.run(v2.main())
