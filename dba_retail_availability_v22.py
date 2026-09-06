from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright

import dba_retail_offers_v22 as offers22

STRATEGY = Path('results/wow_strategy_latest.json')
OFFERS = Path('results/retail_offers_v22.json')
OUT = Path('results/retail_availability_v22.json')
COMPAT = Path('results/retail_availability_v21.json')


async def main() -> None:
    data = json.loads(STRATEGY.read_text(encoding='utf-8'))
    offers = json.loads(OFFERS.read_text(encoding='utf-8'))
    rec = data.get('recommended_self_build') or {}
    by_sku = {str(r.get('sku')): r for r in offers.get('rows') or [] if r.get('sku')}
    selected = [c for c in rec.get('components') or [] if c.get('source') == 'NEW RETAIL']
    assert selected, 'V22 selected no new retail components'

    products = []
    expected = {}
    for c in selected:
        sku = str(c.get('sku') or '')
        prior = by_sku.get(sku) or {}
        product_url = prior.get('product_url')
        assert product_url, f'V22 selected retail product URL missing for {sku}'
        products.append({
            'sku': sku,
            'kind': c.get('kind'),
            'name': c.get('name'),
            'url': product_url,
            'price': prior.get('same_page_lowest_price_dkk') or prior.get('product_reference_price_dkk') or c.get('price'),
        })
        expected[sku] = {
            'price': int(c.get('price') or 0),
            'url': str(c.get('url') or ''),
            'kind': c.get('kind'),
            'name': c.get('name'),
        }

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(locale='da-DK')
        sem = asyncio.Semaphore(3)
        fresh = await asyncio.gather(*(offers22.inspect(context, p, sem, offers22.kinds()) for p in products))
        await context.close()
        await browser.close()

    fresh_by_sku = {str(r.get('sku')): r for r in fresh if r.get('sku')}
    rows = []
    failures = []
    for sku, exp in expected.items():
        r = fresh_by_sku.get(sku) or {}
        current_price = int(r.get('delivered_price_dkk') or 0)
        current_url = str(r.get('buy_url') or '')
        same_price = bool(current_price and current_price == int(exp['price']))
        same_url = bool(current_url and current_url == exp['url'])
        identity = r.get('identity_verified') is True
        current_ready = r.get('delivered_price_verified') is True
        t1_ok = bool(identity and current_ready and same_price and same_url and r.get('price_sanity_ok') is True)
        row = {
            'kind': exp['kind'],
            'name': exp['name'],
            'sku': sku,
            'expected_price': int(exp['price']),
            'expected_url': exp['url'],
            't1_verified_at': r.get('verified_at'),
            'identity_verified': identity,
            'price_verified': same_price,
            'same_offer_url_verified': same_url,
            'price_sanity_ok': r.get('price_sanity_ok') is True,
            'same_page_lowest_price_dkk': r.get('same_page_lowest_price_dkk'),
            'same_page_price_floor_method': r.get('same_page_price_floor_method'),
            'current_price': current_price or None,
            'current_url': current_url or None,
            't1_revalidated': t1_ok,
            'concrete_in_stock': t1_ok,
            'availability_status': 'IN_STOCK_DELIVERED_PRICE_T1_REVALIDATED' if t1_ok else 'SELECTED_OFFER_CHANGED_OR_UNPROVEN',
            'delivered_price_method': r.get('delivered_price_method'),
            'item_price_dkk': r.get('item_price_dkk'),
            'shipping_dkk': r.get('shipping_dkk'),
            'store_offer': ({
                'price': current_price,
                'delivered_price_dkk': current_price,
                'item_price_dkk': r.get('item_price_dkk'),
                'shipping_dkk': r.get('shipping_dkk'),
                'seller': r.get('seller'),
                'url': current_url,
                'availability': 'IN_STOCK',
                'deal_type': r.get('deal_type'),
                'normal_price_dkk': r.get('normal_price_dkk'),
                'delivered_price_method': r.get('delivered_price_method'),
            } if t1_ok else None),
        }
        rows.append(row)
        if not t1_ok:
            failures.append({
                'sku': sku,
                'name': exp['name'],
                'expected_price': exp['price'],
                'current_price': current_price or None,
                'expected_url': exp['url'],
                'current_url': current_url or None,
                'same_price': same_price,
                'same_url': same_url,
                'identity': identity,
                'current_ready': current_ready,
                'same_page_lowest_price_dkk': r.get('same_page_lowest_price_dkk'),
                'error': r.get('error'),
            })

    doc = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'model': 'V22_SELECTED_DELIVERED_RETAIL_AVAILABILITY',
        'policy': 'Every selected new retail component is re-fetched immediately before publication. The same SKU, same selected offer URL, same delivered price, identity and same-page price-floor sanity must all still hold.',
        'selected_total': len(rows),
        'identity_verified': sum(1 for x in rows if x.get('identity_verified')),
        'concrete_in_stock': sum(1 for x in rows if x.get('concrete_in_stock')),
        't1_revalidated': sum(1 for x in rows if x.get('t1_revalidated')),
        'failures': failures,
        'rows': rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(doc, ensure_ascii=False, indent=2)
    OUT.write_text(text, encoding='utf-8')
    COMPAT.write_text(text, encoding='utf-8')

    print(json.dumps({
        'V22_RETAIL_AVAILABILITY': True,
        'selected': len(rows),
        't1_revalidated': doc['t1_revalidated'],
        'failures': failures,
        'delivered_total': sum(int(x.get('expected_price') or 0) for x in rows),
    }, ensure_ascii=False))
    assert all(r.get('identity_verified') for r in rows), 'V22 selected retail identity not verified at T1'
    assert all(r.get('t1_revalidated') for r in rows), f'V22 selected retail offer changed before publish: {failures}'


if __name__ == '__main__':
    asyncio.run(main())
