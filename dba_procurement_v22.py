from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

STRATEGY = Path('results/wow_strategy_latest.json')
PLAN21 = Path('results/procurement_plan_v21.json')
OFFERS = Path('results/retail_offers_v22.json')
OUT = Path('results/procurement_plan_v22.json')


def _external(url: str) -> bool:
    host = urlparse(str(url or '')).netloc.lower()
    return bool(host and 'prisjagt.dk' not in host)


def main() -> None:
    data = json.loads(STRATEGY.read_text(encoding='utf-8'))
    p = json.loads(PLAN21.read_text(encoding='utf-8'))
    offers = json.loads(OFFERS.read_text(encoding='utf-8'))
    assert (data.get('offer_optimizer_v22') or {}).get('active') is True
    assert p.get('version') == 'V21'

    p['version'] = 'V22'
    p['generated_at'] = datetime.now(timezone.utc).isoformat()
    p['core_model'] = 'DBA-WOW-SELF-BUILD-FIRST-V20 + V22_DIRECT_RETAILER_FAIL_CLOSED'
    fit = (p.get('z20_fit_authoritative') or {}).get('status', 'UNKNOWN')
    blockers = [b for b in (p.get('blockers') or []) if b.get('kind') not in {'GPU_FIT', 'RETAIL_DIRECT_VERIFY'}]
    if fit != 'VERIFIED':
        blockers.append({
            'kind': 'GPU_FIT',
            'procurement_action': 'VERIFY_FIT',
            'actionable_now': False,
            'reason': 'Exact board-partner GPU model/dimensions must be proven before the complete Z20 build is buy-ready.',
        })

    by_sku = {str(r.get('sku')): r for r in offers.get('rows') or [] if r.get('sku')}
    retail_rows = []
    unresolved = []

    for a in p.get('actions') or []:
        if a.get('source') != 'NEW RETAIL':
            continue
        sku = str(a.get('sku') or '')
        r = by_sku.get(sku) or {}
        direct = bool(
            r.get('delivered_price_verified') is True
            and r.get('external_url_resolved') is True
            and _external(str(r.get('buy_url') or ''))
            and int(r.get('delivered_price_dkk') or 0) == int(a.get('ask') or 0)
        )

        row = {
            'kind': a.get('kind'),
            'sku': sku,
            'name': a.get('name'),
            'comparison_url': r.get('product_url') or a.get('url'),
            'comparison_price_dkk': int(a.get('ask') or 0),
            'purchase_ready': direct,
            'external_retailer_verified': direct,
        }

        if direct:
            a['procurement_action'] = 'BUY_NOW'
            a['actionable_now'] = True
            a['availability_status'] = 'IN_STOCK_DIRECT_RETAILER_VERIFIED'
            a['reason'] = 'External retailer, same product, live price, stock and delivered total verified in the same run.'
            a['store_offer'] = {
                'seller': r.get('seller'),
                'url': r.get('buy_url'),
                'price': r.get('delivered_price_dkk'),
                'delivered_price_dkk': r.get('delivered_price_dkk'),
                'item_price_dkk': r.get('item_price_dkk'),
                'shipping_dkk': r.get('shipping_dkk'),
                'delivered_price_method': r.get('delivered_price_method'),
                'deal_type': r.get('deal_type'),
            }
            row.update({
                'seller': r.get('seller'),
                'buy_url': r.get('buy_url'),
                'delivered_price_dkk': r.get('delivered_price_dkk'),
                'deal_type': r.get('deal_type'),
            })
        else:
            a['procurement_action'] = 'CHECK_STORE'
            a['actionable_now'] = False
            a['availability_status'] = 'PRICE_REFERENCE_ONLY_CHECK_STORE'
            a['reason'] = 'Prisjagt/current comparison price is a market reference only. The external retailer page, same price and stock were not verified in the same run, so this is not KØB NU.'
            a['store_offer'] = None
            unresolved.append({'kind': a.get('kind'), 'sku': sku, 'name': a.get('name'), 'comparison_price_dkk': int(a.get('ask') or 0)})

        retail_rows.append(row)

    if unresolved:
        blockers.append({
            'kind': 'RETAIL_DIRECT_VERIFY',
            'procurement_action': 'CHECK_STORE',
            'actionable_now': False,
            'reason': 'One or more selected new parts have only comparison-site price evidence. A direct retailer page with the same product, price and stock is required before KØBSKLAR.',
            'parts': unresolved,
        })

    p['blockers'] = blockers
    p.setdefault('headline', {})['ready_to_buy_complete_build_today'] = bool(not blockers and fit == 'VERIFIED')
    p['headline']['z20_fit'] = fit
    p['headline']['authoritative_purchase_total'] = (
        p['headline'].get('ask_total') if not unresolved else None
    )
    p['headline']['ask_total_is_reference_only'] = bool(unresolved)

    p['retail_offers_v22'] = {
        'model': offers.get('model'),
        'products_total': offers.get('products_total'),
        'comparison_offer_candidates': offers.get('delivered_price_verified'),
        'externally_resolved_candidates': offers.get('external_urls_resolved'),
        'selected': retail_rows,
        'direct_buy_ready_selected': sum(1 for x in retail_rows if x.get('purchase_ready')),
        'reference_only_selected': sum(1 for x in retail_rows if not x.get('purchase_ready')),
        'rule': 'Prisjagt-only prices are leads/references. BUY_NOW requires an external retailer URL plus same-run verification of product, price and stock.',
    }

    OUT.write_text(json.dumps(p, ensure_ascii=False, indent=2), encoding='utf-8')
    data['procurement_v22'] = p
    data['procurement_version'] = 'V22'
    data['z20_fit_authoritative_v22'] = p.get('z20_fit_authoritative')
    STRATEGY.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

    print(json.dumps({
        'V22_PROCUREMENT': True,
        'ask_total_reference': p['headline'].get('ask_total'),
        'authoritative_purchase_total': p['headline'].get('authoritative_purchase_total'),
        'fit': fit,
        'ready_today': p['headline'].get('ready_to_buy_complete_build_today'),
        'direct_buy_ready_new': p['retail_offers_v22']['direct_buy_ready_selected'],
        'reference_only_new': p['retail_offers_v22']['reference_only_selected'],
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
