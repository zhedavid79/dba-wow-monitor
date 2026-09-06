from __future__ import annotations

import asyncio
import json
import re
import statistics
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

from playwright.async_api import async_playwright

import dba_retail_prices_v19 as retail19

RETAIL = Path('results/retail_prices_latest.json')
OUT = Path('results/retail_offers_v22.json')
PRICE_RE = re.compile(r'(?<!\d)(\d{1,3}(?:[. ]\d{3})*|\d{3,5})(?:[,.]\d{2})?\s*(?:kr\.?|DKK)', re.I)
STOCK_RE = re.compile(r'\b(?:på lager|in stock|lagerfør|levering\s*\d|sendes|afsendes|klar til levering)\b', re.I)
FREE_SHIP_RE = re.compile(r'\b(?:fri fragt|gratis fragt|gratis levering|free shipping|0(?:[,.]00)?\s*kr\.?\s*(?:fragt|levering))\b', re.I)
PROMO_RE = re.compile(r'\b(?:tilbud|kampagne|rabat|spar|sale|specialpris|weekendpris|black friday|outlet)\b|\b\d{1,2}\s*%\b', re.I)
NORMAL_RE = re.compile(r'\b(?:før|førpris|normalpris|normal pris|vejledende pris|vejl\.?\s*pris)\D{0,20}(\d{1,3}(?:[. ]\d{3})*|\d{3,5})(?:[,.]\d{2})?\s*(?:kr\.?|DKK)', re.I)
SHIP_A = re.compile(r'\b(?:fragt|levering|shipping)\s*(?:fra\s*)?(\d{1,3}(?:[. ]\d{3})*|\d{1,4})(?:[,.](\d{1,2}))?\s*kr\.?', re.I)
SHIP_B = re.compile(r'(\d{1,3}(?:[. ]\d{3})*|\d{1,4})(?:[,.](\d{1,2}))?\s*kr\.?.{0,20}\b(?:fragt|levering|shipping)\b', re.I)


def money_value(a: str, decimals: str | None = None) -> int:
    whole = int(str(a).replace('.', '').replace(' ', ''))
    if decimals and int(decimals) >= 50:
        whole += 1
    return whole


def prices(text: str) -> list[int]:
    vals = []
    for m in PRICE_RE.finditer(str(text or '')):
        try:
            n = int(m.group(1).replace('.', '').replace(' ', ''))
        except Exception:
            continue
        if 100 <= n <= 100000:
            vals.append(n)
    return vals


def shipping(text: str) -> tuple[int | None, bool, str]:
    s = str(text or '')
    if FREE_SHIP_RE.search(s):
        return 0, True, 'EXPLICIT_FREE_SHIPPING'
    for rx in (SHIP_A, SHIP_B):
        m = rx.search(s)
        if not m:
            continue
        try:
            value = money_value(m.group(1), m.group(2))
        except Exception:
            continue
        # 'fra 49 kr' is useful as a lead but is not an exact mandatory shipping charge.
        prefix = s[max(0, m.start() - 15):m.end() + 5].lower()
        exact = 'fra' not in prefix
        return value, exact, 'EXPLICIT_SHIPPING' if exact else 'SHIPPING_FROM'
    return None, False, 'SHIPPING_UNPROVEN'


def normal_price(text: str) -> int | None:
    m = NORMAL_RE.search(str(text or ''))
    if not m:
        return None
    try:
        return int(m.group(1).replace('.', '').replace(' ', ''))
    except Exception:
        return None


def is_stock(text: str) -> bool:
    return bool(STOCK_RE.search(str(text or '')))


def identity_ok(expected: str, actual: str) -> bool:
    return retail19.identity_ok(expected, actual)


async def card_text(anchor) -> str:
    best = ''
    for level in range(0, 6):
        try:
            loc = anchor if level == 0 else anchor.locator('xpath=' + '/..' * level)
            txt = (await loc.inner_text(timeout=500)).strip()
        except Exception:
            continue
        if not txt:
            continue
        if not best:
            best = txt
        if prices(txt) and (STOCK_RE.search(txt) or 'fragt' in txt.lower() or 'levering' in txt.lower() or PROMO_RE.search(txt)):
            return txt[:1800]
        if len(txt) < 1800:
            best = txt
    return best[:1800]


async def resolve_offer(context, href: str, row_text: str) -> dict:
    out = {'redirect_url': href, 'direct_url': None, 'seller': None, 'redirect_ok': False}
    try:
        resp = await context.request.get(href, timeout=15000, max_redirects=10, fail_on_status_code=False)
        out['http_status'] = int(resp.status)
        out['direct_url'] = str(resp.url)
        host = urlparse(str(resp.url)).netloc.lower().removeprefix('www.')
        out['seller'] = host or None
        out['redirect_ok'] = bool(host and 'prisjagt.dk' not in host)
        # If shipping was not visible in the comparison card, a direct retailer page
        # can prove explicit free/exact shipping. We never infer 0 from silence.
        try:
            body = (await resp.text())[:60000]
        except Exception:
            body = ''
        ship, exact, method = shipping(row_text)
        if not exact and body:
            d_ship, d_exact, d_method = shipping(body)
            if d_exact:
                ship, exact, method = d_ship, d_exact, 'DIRECT_' + d_method
        out['shipping_dkk'] = ship
        out['shipping_exact'] = exact
        out['shipping_method'] = method
        out['direct_stock_text'] = bool(body and STOCK_RE.search(body))
    except Exception as exc:
        out['resolve_error'] = f'{type(exc).__name__}: {str(exc)[:180]}'
        ship, exact, method = shipping(row_text)
        out['shipping_dkk'] = ship
        out['shipping_exact'] = exact
        out['shipping_method'] = method
    return out


async def inspect_product(context, product: dict, sem: asyncio.Semaphore) -> dict:
    async with sem:
        page = await context.new_page()
        now = datetime.now(timezone.utc).isoformat()
        expected_name = str(product.get('name') or '')
        product_url = str(product.get('url') or '')
        out = {
            'sku': product.get('sku'), 'kind': product.get('kind'), 'name': expected_name,
            'product_url': product_url, 'verified_at': now, 'identity_verified': False,
            'offers': [], 'best_delivered_offer': None, 'best_lead': None,
            'delivered_price_verified': False,
        }
        try:
            response = await page.goto(product_url, wait_until='domcontentloaded', timeout=45000)
            out['http_status'] = int(response.status) if response else None
            title = await page.title()
            h1 = ''
            try:
                h1 = (await page.locator('h1').first.inner_text(timeout=2500)).strip()
            except Exception:
                pass
            if not identity_ok(expected_name, ' '.join([title, h1])):
                out['error'] = 'PRODUCT_IDENTITY_MISMATCH'
                return out
            out['identity_verified'] = True

            anchors = page.locator('a[href*="/go-to-shop/"]')
            n = min(await anchors.count(), 80)
            raw = []
            seen = set()
            for i in range(n):
                a = anchors.nth(i)
                try:
                    href = await a.get_attribute('href') or ''
                except Exception:
                    continue
                if not href:
                    continue
                href = urljoin(product_url, href)
                txt = await card_text(a)
                vals = prices(txt)
                if not vals:
                    continue
                # Store-card item price is the smallest plausible product price;
                # shipping amounts under 100 DKK are intentionally excluded by prices().
                item = min(vals)
                if item < 100:
                    continue
                key = (href, item)
                if key in seen:
                    continue
                seen.add(key)
                ship, ship_exact, ship_method = shipping(txt)
                normal = normal_price(txt)
                raw.append({
                    'item_price_dkk': item,
                    'shipping_dkk': ship,
                    'shipping_exact': ship_exact,
                    'shipping_method': ship_method,
                    'in_stock_card': is_stock(txt),
                    'promo_evidence': bool(PROMO_RE.search(txt)),
                    'normal_price_dkk': normal,
                    'redirect_url': href,
                    'evidence_text': txt[:500],
                })

            # Resolve only the economically relevant first offers to keep the run bounded.
            raw.sort(key=lambda x: (x['item_price_dkk'], 0 if x['in_stock_card'] else 1))
            resolved = []
            for row in raw[:12]:
                r = dict(row)
                r.update(await resolve_offer(context, str(row['redirect_url']), str(row.get('evidence_text') or '')))
                stock = bool(r.get('in_stock_card') or r.get('direct_stock_text'))
                ship_exact = r.get('shipping_exact') is True
                ship = r.get('shipping_dkk')
                direct = r.get('redirect_ok') is True
                r['in_stock_verified'] = stock
                r['delivered_price_dkk'] = int(r['item_price_dkk']) + int(ship) if ship_exact and ship is not None else None
                r['buy_ready_offer'] = bool(stock and ship_exact and direct and r['delivered_price_dkk'] is not None)
                if r.get('normal_price_dkk') and r['normal_price_dkk'] > r['item_price_dkk']:
                    r['explicit_discount_pct'] = round((1 - r['item_price_dkk'] / r['normal_price_dkk']) * 100, 1)
                resolved.append(r)

            verified = [r for r in resolved if r.get('buy_ready_offer')]
            delivered_vals = [int(r['delivered_price_dkk']) for r in verified]
            median_delivered = int(round(statistics.median(delivered_vals))) if delivered_vals else None
            for r in resolved:
                r['market_reference_delivered_dkk'] = median_delivered
                dp = r.get('delivered_price_dkk')
                if r.get('explicit_discount_pct'):
                    r['deal_type'] = 'EXPLICIT_SALE'
                elif dp is not None and median_delivered and dp <= median_delivered * 0.90:
                    r['deal_type'] = 'MARKET_DEAL'
                elif r.get('promo_evidence'):
                    r['deal_type'] = 'PROMOTION_EVIDENCE'
                else:
                    r['deal_type'] = 'BEST_CURRENT_PRICE'
            verified.sort(key=lambda x: (int(x['delivered_price_dkk']), int(x['item_price_dkk'])))
            leads = [r for r in resolved if r.get('in_stock_verified') and r.get('redirect_ok')]
            leads.sort(key=lambda x: (int(x.get('delivered_price_dkk') or 10**9), int(x['item_price_dkk'])))
            out['offers'] = resolved
            if verified:
                out['best_delivered_offer'] = verified[0]
                out['delivered_price_verified'] = True
                out['delivered_price_dkk'] = int(verified[0]['delivered_price_dkk'])
                out['item_price_dkk'] = int(verified[0]['item_price_dkk'])
                out['shipping_dkk'] = int(verified[0]['shipping_dkk'])
                out['buy_url'] = verified[0].get('direct_url') or verified[0].get('redirect_url')
                out['seller'] = verified[0].get('seller')
                out['deal_type'] = verified[0].get('deal_type')
                out['normal_price_dkk'] = verified[0].get('normal_price_dkk')
                out['market_reference_delivered_dkk'] = median_delivered
            elif leads:
                out['best_lead'] = leads[0]
            return out
        except Exception as exc:
            out['error'] = f'{type(exc).__name__}: {str(exc)[:240]}'
            return out
        finally:
            await page.close()


async def main() -> None:
    doc = json.loads(RETAIL.read_text(encoding='utf-8'))
    products = []
    seen = set()
    for p in doc.get('products') or []:
        url = str(p.get('url') or '')
        sku = str(p.get('sku') or url)
        if not url or sku in seen:
            continue
        seen.add(sku)
        products.append(dict(p))

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(locale='da-DK')
        sem = asyncio.Semaphore(5)
        rows = await asyncio.gather(*(inspect_product(context, x, sem) for x in products))
        await context.close()
        await browser.close()

    by_sku = {str(r.get('sku')): r for r in rows if r.get('sku')}
    ready = [r for r in rows if r.get('delivered_price_verified')]
    explicit = [r for r in ready if r.get('deal_type') in {'EXPLICIT_SALE', 'MARKET_DEAL', 'PROMOTION_EVIDENCE'}]
    result = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'model': 'V22_STORE_LEVEL_DELIVERED_PRICE_AND_DEALS',
        'policy': 'A new retail candidate is purchase-ready only when same-product identity, concrete retailer, stock and exact mandatory shipping are proven. Selection uses delivered price = item price + mandatory shipping. Unknown shipping remains a lead and cannot define the authoritative delivered price.',
        'products_total': len(rows),
        'delivered_price_verified': len(ready),
        'deal_candidates': len(explicit),
        'rows': rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')

    # Attach offer evidence to the retail snapshot without replacing the original
    # same-product item-price evidence. V22 optimization reads delivered_price_dkk.
    for p in doc.get('products') or []:
        r = by_sku.get(str(p.get('sku') or ''))
        if not r:
            continue
        p['retail_offer_v22'] = {
            'delivered_price_verified': r.get('delivered_price_verified') is True,
            'delivered_price_dkk': r.get('delivered_price_dkk'),
            'item_price_dkk': r.get('item_price_dkk'),
            'shipping_dkk': r.get('shipping_dkk'),
            'buy_url': r.get('buy_url'),
            'seller': r.get('seller'),
            'deal_type': r.get('deal_type'),
            'normal_price_dkk': r.get('normal_price_dkk'),
            'market_reference_delivered_dkk': r.get('market_reference_delivered_dkk'),
        }
    doc['offer_gate_v22'] = {
        'model': result['model'],
        'products_total': len(rows),
        'delivered_price_verified': len(ready),
        'deal_candidates': len(explicit),
        'required_price_basis': 'DELIVERED_PRICE_DKK',
    }
    RETAIL.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({
        'V22_RETAIL_OFFERS': True,
        'products': len(rows),
        'delivered_verified': len(ready),
        'deals': len(explicit),
    }, ensure_ascii=False))
    assert rows, 'V22 offer engine inspected no products'


if __name__ == '__main__':
    asyncio.run(main())
