from __future__ import annotations

import asyncio
import json

from playwright.async_api import async_playwright

import dba_browser_v2 as v2
from dba_browser_v3 import discover_cards_by_article, flatten_jsonld, offer_from_product


async def diagnose_item(page, row: dict) -> dict:
    listing_id = str(row["listing_id"])
    url = v2.ITEM_URL.format(listing_id=listing_id)
    diagnostic = {
        "listing_id": listing_id,
        "t0_title": row.get("title"),
        "t0_price": row.get("ask_t0"),
        "requested_url": url,
    }
    try:
        response = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    except Exception as exc:
        return {**diagnostic, "result": "NAVIGATION_ERROR", "detail": f"{type(exc).__name__}: {str(exc)[:200]}"}

    diagnostic["http_status"] = response.status if response else None
    diagnostic["rendered_url"] = page.url
    await v2.dismiss_consent(page)
    await page.wait_for_timeout(300)

    page_match = v2.ITEM_RE.search(page.url or "")
    diagnostic["rendered_page_id"] = page_match.group(1) if page_match else None
    if diagnostic["rendered_page_id"] != listing_id:
        return {**diagnostic, "result": "PAGE_ID_MISMATCH"}

    script_meta = await page.locator("script").evaluate_all(
        """els => els.map((s, i) => {
          const x = s.textContent || '';
          return {
            i,
            type: s.type || '',
            len: x.length,
            hasProduct: x.includes('Product'),
            hasOffers: x.includes('offers'),
            hasSku: x.includes('sku'),
            hasProductID: x.includes('productID'),
            hasPriceCurrency: x.includes('priceCurrency'),
            prefix: x.slice(0, 120)
          };
        }).filter(x => x.hasProduct || x.hasOffers || x.hasSku || x.hasProductID || x.hasPriceCurrency)"""
    )
    diagnostic["interesting_scripts"] = len(script_meta)
    diagnostic["script_meta"] = script_meta[:12]

    raw_scripts = await page.locator("script").evaluate_all("els => els.map(s => s.textContent || '')")
    products = []
    parseable_json_scripts = 0
    for raw in raw_scripts:
        if not raw.strip():
            continue
        try:
            parsed = json.loads(raw)
        except Exception:
            continue
        parseable_json_scripts += 1
        for obj in flatten_jsonld(parsed):
            typ = obj.get("@type")
            types = typ if isinstance(typ, list) else [typ]
            if any(str(x).lower() == "product" for x in types if x is not None):
                products.append(obj)

    diagnostic["parseable_json_scripts"] = parseable_json_scripts
    diagnostic["product_objects"] = len(products)
    diagnostic["products"] = []

    for product in products[:10]:
        sku = str(product.get("sku") or product.get("productID") or "").strip()
        product_url = str(product.get("url") or "").strip()
        m = v2.ITEM_RE.search(product_url)
        product_url_id = m.group(1) if m else None
        offer = offer_from_product(product)
        product_diag = {
            "sku_or_productID": sku or None,
            "product_url": product_url or None,
            "product_url_id": product_url_id,
            "name": str(product.get("name") or "")[:120],
            "has_offer": bool(offer),
        }
        if offer:
            product_diag.update({
                "offer_price_raw": offer.get("price"),
                "offer_price_parsed": v2.parse_number(offer.get("price")),
                "offer_currency": str(offer.get("priceCurrency") or ""),
                "offer_availability": str(offer.get("availability") or ""),
            })
        diagnostic["products"].append(product_diag)

        id_match = sku == listing_id or product_url_id == listing_id
        if not id_match or not offer:
            continue
        ask = v2.parse_number(offer.get("price"))
        currency = str(offer.get("priceCurrency") or "").upper()
        availability = str(offer.get("availability") or "")
        normalized = availability.rstrip("/").lower()
        active = normalized.endswith("instock") and not any(normalized.endswith(x) for x in ("outofstock", "discontinued", "soldout"))
        if ask is not None and currency == "DKK" and active:
            return {**diagnostic, "result": "PASS"}

    if not products:
        diagnostic["result"] = "NO_PRODUCT_JSON_OBJECT"
    elif not any((p.get("sku_or_productID") == listing_id or p.get("product_url_id") == listing_id) for p in diagnostic["products"]):
        diagnostic["result"] = "NO_SAME_ID_PRODUCT"
    elif not any(p.get("has_offer") for p in diagnostic["products"]):
        diagnostic["result"] = "NO_OFFER"
    else:
        diagnostic["result"] = "OFFER_NOT_ACTIVE_NUMERIC_DKK"
    return diagnostic


async def main() -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(locale="da-DK", viewport={"width": 1440, "height": 1100})
        search_page = await context.new_page()
        item_page = await context.new_page()
        try:
            rows = []
            errors = []
            seen = set()
            for query in ("gaming pc", "rtx 3070", "rtx 3060 ti"):
                try:
                    discovered = await discover_cards_by_article(search_page, query)
                except Exception as exc:
                    errors.append({"query": query, "error": f"{type(exc).__name__}: {str(exc)[:200]}"})
                    continue
                for row in discovered:
                    if row["listing_id"] not in seen:
                        seen.add(row["listing_id"])
                        rows.append(row)
                if len(rows) >= 6:
                    break

            report = {"t0_candidates": len(rows), "search_errors": errors, "items": []}
            for row in rows[:6]:
                item = await diagnose_item(item_page, row)
                report["items"].append(item)
                if item.get("result") == "PASS":
                    report["ok"] = True
                    print(json.dumps(report, ensure_ascii=False))
                    return

            report["ok"] = False
            print(json.dumps(report, ensure_ascii=False))
            raise SystemExit("DBA T1 PREFLIGHT FAILED — focused diagnostics printed above")
        finally:
            await search_page.close()
            await item_page.close()
            await context.close()
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
