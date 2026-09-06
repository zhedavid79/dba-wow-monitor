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
        product_url = str(prior.get('product_url') or c.get('comparison_url') or c.get('url') or '')
        assert product_url, f'V22 selected retail product URL missing for {sku}'
        products.append({
            'sku': sku,
            'kind': c.get('kind'),
            'name': c.get('name'),
            'url': product_url,
            'price': int(c.get('price') or 0),
        })
        expected[sku] = {
            'price': int(c.get('price') or 0),
            'url': str(c.get('url') or ''),
            'kind': c.get('kind'),
            'name': c.get('name'),
            'direct_expected': c.get('retail_offer_verified_v22') is True,
            'comparison_url': product_url,
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
        identity = r.get('identity_verified') is True
        current_price = int(r.get('delivered_price_dkk') or 0)
        current_url = str(r.get('buy_url') or '')
        external = r.get('external_url_resolved') is True
        current_ready = r.get('delivered_price_verified') is True

        if exp['direct_expected']:
            same_price = bool(current_price and current_price == exp['price'])
            same_url = bool(current_url and current_url == exp['url'])
            t1_ok = bool(identity and external and current_ready and same_price and same_url and r.get('price_sanity_ok') is True)
            status = 'IN_STOCK_DIRECT_RETAILER_T1_REVALIDATED' if t1_ok else 'DIRECT_RETAILER_OFFER_CHANGED_OR_UNPROVEN'
            reference_ok = False
        else:
            # Comparison-only candidates are deliberately not purchase-ready.
            # Re-fetching is used only to prove same-product identity/reference freshness.
            floor = int(r.get('same_page_lowest_price_dkk') or r.get('product_reference_price_dkk') or 0)
            reference_ok = bool(identity and floor > 0)
            t1_ok = False
            same_price = False
            same_url = False
            status = 'PRICE_REFERENCE_ONLY_CHECK_STORE' if reference_ok else 'PRICE_REFERENCE_UNPROVEN'

        row = {
            'kind': exp['kind'],
            'name': exp['name'],
            'sku': sku,
            'expected_price': exp['price'],
            'expected_url': exp['url'],
            'comparison_url': exp['comparison_url'],
            'direct_expected': exp['direct_expected'],
            't1_verified_at': r.get('verified_at'),
            'identity_verified': identity,
            'external_retailer_resolved': external,
            'price_verified': same_price,
            'same_offer_url_verified': same_url,
            'reference_revalidated': reference_ok,
            'current_reference_price': int(r.get('same_page_lowest_price_dkk') or r.get('product_reference_price_dkk') or 0) or None,
            'current_price': current_price or None,
            'current_url': current_url or None,
            't1_revalidated': t1_ok,
            'concrete_in_stock': t1_ok,
            'availability_status': status,
            'store_offer': ({
                'price': current_price,
                'delivered_price_dkk': current_price,
                'seller': r.get('seller'),
                'url': current_url,
                'availability': 'IN_STOCK',
            } if t1_ok else None),
        }
        rows.append(row)
        if exp['direct_expected'] and not t1_ok:
            failures.append({'sku': sku, 'name': exp['name'], 'reason': 'DIRECT_RETAILER_T1_FAILED', 'current_price': current_price or None, 'current_url': current_url or None})
        if not exp['direct_expected'] and not reference_ok:
            failures.append({'sku': sku, 'name': exp['name'], 'reason': 'COMPARISON_REFERENCE_REVALIDATION_FAILED'})

    doc = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'model': 'V22_SELECTED_RETAIL_DIRECT_OR_REFERENCE_AVAILABILITY',
        'policy': 'Only external retailer pages can be purchase-ready. Prisjagt-only prices are revalidated as same-product comparison references and remain CHECK_STORE.',
        'selected_total': len(rows),
        'identity_verified': sum(1 for x in rows if x.get('identity_verified')),
        'direct_buy_ready': sum(1 for x in rows if x.get('t1_revalidated')),
        'reference_only': sum(1 for x in rows if x.get('reference_revalidated')),
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
        'direct_buy_ready': doc['direct_buy_ready'],
        'reference_only': doc['reference_only'],
        'failures': failures,
    }, ensure_ascii=False))
    assert all(r.get('identity_verified') for r in rows), 'V22 selected retail identity not verified at T1'
    assert not failures, f'V22 selected retail verification failures: {failures}'


if __name__ == '__main__':
    asyncio.run(main())
