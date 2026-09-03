from __future__ import annotations

import asyncio
import json
from urllib.parse import quote

import dba_browser_v2 as v2


def flatten_jsonld(value):
    """Yield every dict contained in arbitrary JSON-LD list/graph nesting."""
    if isinstance(value, dict):
        yield value
        graph = value.get("@graph")
        if isinstance(graph, (dict, list)):
            yield from flatten_jsonld(graph)
        for key, child in value.items():
            if key == "@graph":
                continue
            if isinstance(child, (dict, list)):
                yield from flatten_jsonld(child)
    elif isinstance(value, list):
        for child in value:
            yield from flatten_jsonld(child)


def offer_from_product(product: dict) -> dict | None:
    """Return one concrete Offer/AggregateOffer-like dict without guessing values."""
    offers = product.get("offers")
    if isinstance(offers, dict):
        return offers
    if isinstance(offers, list):
        for offer in offers:
            if isinstance(offer, dict):
                return offer
    return None


def category_from_product(product: dict) -> str:
    """Normalize only explicit Product category evidence."""
    category = product.get("category")
    if isinstance(category, str):
        return category.strip()
    if isinstance(category, dict):
        for key in ("name", "value", "@id"):
            value = category.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    if isinstance(category, list):
        values = []
        for item in category:
            if isinstance(item, str) and item.strip():
                values.append(item.strip())
            elif isinstance(item, dict):
                value = item.get("name") or item.get("value") or item.get("@id")
                if isinstance(value, str) and value.strip():
                    values.append(value.strip())
        return " > ".join(values)
    return ""


async def discover_cards_by_article(page, query: str) -> list[dict]:
    """Bind id/url/title/price from one rendered DBA result container.

    CSS class names are not evidence. Starting at each live item link, select the nearest
    ancestor that remains exclusive to exactly one unique DBA listing ID. Title and price
    are then parsed only from that same self-contained container.
    """
    url = f"{v2.BASE}/recommerce/forsale/search?q={quote(query)}"
    response = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    if response and response.status >= 400:
        return []
    await v2.dismiss_consent(page)

    item_selector = 'a[href*="/recommerce/forsale/item/"]'
    try:
        await page.wait_for_selector(item_selector, timeout=10000)
    except Exception:
        return []

    rows = await page.locator(item_selector).evaluate_all(
        """links => {
          const itemRe = /\/recommerce\/forsale\/item\/(\d+)/;
          const uniqueIds = node => {
            const ids = new Set();
            for (const a of node.querySelectorAll('a[href*="/recommerce/forsale/item/"]')) {
              const m = (a.href || '').match(itemRe);
              if (m) ids.add(m[1]);
            }
            return [...ids];
          };
          const out = [];
          const seen = new Set();
          for (const link of links) {
            const m = (link.href || '').match(itemRe);
            if (!m || seen.has(m[1])) continue;
            const listingId = m[1];
            let node = link;
            let chosen = null;
            for (let depth = 0; depth < 10 && node; depth++, node = node.parentElement) {
              const ids = uniqueIds(node);
              if (ids.length === 1 && ids[0] === listingId) {
                const text = (node.innerText || '').trim();
                if (text.length >= 8) chosen = node;
              } else if (ids.length > 1) {
                break;
              }
            }
            if (!chosen) continue;
            const ids = uniqueIds(chosen);
            if (ids.length !== 1 || ids[0] !== listingId) continue;
            seen.add(listingId);
            out.push({
              listing_id: listingId,
              href: link.href,
              card_text: (chosen.innerText || '').trim(),
              container_tag: chosen.tagName,
              container_class: String(chosen.className || '').slice(0, 300),
              container_item_id_count: ids.length
            });
          }
          return out;
        }"""
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
                "t0_container_evidence": {
                    "tag": row.get("container_tag"),
                    "class": row.get("container_class"),
                    "unique_listing_ids": row.get("container_item_id_count"),
                },
            }
        )
    return out


async def fetch_jsonld_item_all_scripts(page, listing_id: str) -> dict | None:
    """Read the same listing's Product JSON-LD for T1 with fail-closed identity binding."""
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
        for obj in flatten_jsonld(parsed):
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

        offer = offer_from_product(product)
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
            "category": category_from_product(product),
            "brand": str(product.get("brand") or ""),
            "t1_at": v2.utcnow(),
            "t1_source": "dba_jsonld_product_all_scripts",
        }
    return None


v2.discover_cards = discover_cards_by_article
v2.fetch_jsonld_item = fetch_jsonld_item_all_scripts


if __name__ == "__main__":
    asyncio.run(v2.main())
