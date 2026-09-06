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


def _strict_direct(r: dict, expected_ask: int) -> bool:
    if r.get('delivered_price_verified') is not True:
        return False
    for key in (
        'external_url_resolved',
        'retailer_page_verified',
        'retailer_identity_verified',
        'retailer_price_verified',
        'retailer_stock_verified',
        'retailer_shipping_verified',
    ):
        if r.get(key) is not True:
            return False
    if r.get('retailer_authority') != 'DIRECT_RETAILER_T1':
        return False
    url = str(r.get('buy_url') or '')
    if not _external(url):
        return False
    delivered = int(r.get('delivered_price_dkk') or 0)
    item = r.get('item_price_dkk')
    shipping = r.get('shipping_dkk')
    if not delivered or item is None or shipping is None:
        return False
    if delivered != int(item) + int(shipping):
        return False
    if delivered != int(expected_ask or 0):
        return False
    return r.get('delivered_price_method') == 'DIRECT_RETAILER_ITEM_PLUS_MANDATORY_SHIPPING'


def main() -> None:
    data = json.loads(STRATEGY.read_text(encoding='utf-8'))
    p = json.loads(PLAN21.read_text(encoding='utf-8'))
    offers = json.loads(OFFERS.read_text(encoding='utf-8'))
    assert (data.get('offer_optimizer_v22') or {}).get('active') is True
    assert (data.get('offer_optimizer_v22') or {}).get('retail_authority_model') == 'V22_DIRECT_RETAILER_PAGE_T1'
    assert p.get('version') == 'V21'
    assert offers.get('authority_model') == 'V22_DIRECT_RETAILER_PAGE_T1'

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
        direct = _strict_direct(r, int(a.get('ask') or 0))

        row = {
            'kind': a.get('kind'),
            'sku': sku,
            'name': a.get('name'),
            'comparison_url': r.get('product_url') or a.get('url'),
            'comparison_price_dkk': int(a.get('ask') or 0),
            'comparison_price_method': r.get('same_page_price_floor_method'),
            'purchase_ready': direct,
            'external_retailer_verified': direct,
            'retailer_page_verified': direct,
            'retailer_authority': 'DIRECT_RETAILER_T1' if direct else 'RETAIL_LEAD',
        }

        if direct:
            item = int(r['item_price_dkk'])
            shipping = int(r['shipping_dkk'])
            delivered = int(r['delivered_price_dkk'])
            a['procurement_action'] = 'BUY_NOW'
            a['actionable_now'] = True
            a['availability_status'] = 'IN_STOCK_DIRECT_RETAILER_VERIFIED'
            a['retailer_authority'] = 'DIRECT_RETAILER_T1'
            a['reason'] = (
                'External retailer product page verified same product, current DKK item price, InStock, '
                'mandatory shipping and delivered total in this run; selected offer must still pass immediate T1.'
            )
            a['store_offer'] = {
                'seller': r.get('seller'),
                'url': r.get('buy_url'),
                'price': delivered,
                'delivered_price_dkk': delivered,
                'item_price_dkk': item,
                'shipping_dkk': shipping,
                'delivered_price_method': r.get('delivered_price_method'),
                'deal_type': r.get('deal_type'),
                'external_resolved': True,
                'retailer_page_verified': True,
                'retailer_identity_verified': True,
                'retailer_price_verified': True,
                'retailer_stock_verified': True,
                'retailer_shipping_verified': True,
                'retailer_authority': 'DIRECT_RETAILER_T1',
            }
            row.update({
                'seller': r.get('seller'),
                'buy_url': r.get('buy_url'),
                'item_price_dkk': item,
                'shipping_dkk': shipping,
                'delivered_price_dkk': delivered,
                'deal_type': r.get('deal_type'),
            })
        else:
            assert r.get('same_page_price_floor_method') == 'LIVE_OFFER_LIST_CURRENT_CARD_MIN', (
                f'Selected RETAIL_LEAD lacks live offer-list reference for {sku}'
            )
            a['procurement_action'] = 'CHECK_STORE'
            a['actionable_now'] = False
            a['availability_status'] = 'PRICE_REFERENCE_ONLY_CHECK_STORE'
            a['retailer_authority'] = 'RETAIL_LEAD'
            a['reason'] = (
                'RETAIL_LEAD only: current Prisjagt live-offer-list reference exists, but the external retailer '
                'product page did not prove the same product, current DKK price, stock and mandatory shipping. '
                'This is not KØB NU and not an authoritative ASK acquisition price.'
            )
            a['store_offer'] = None
            unresolved.append({
                'kind': a.get('kind'),
                'sku': sku,
                'name': a.get('name'),
                'comparison_price_dkk': int(a.get('ask') or 0),
                'comparison_price_method': r.get('same_page_price_floor_method'),
                'retailer_authority': 'RETAIL_LEAD',
            })

        retail_rows.append(row)

    if unresolved:
        blockers.append({
            'kind': 'RETAIL_DIRECT_VERIFY',
            'procurement_action': 'CHECK_STORE',
            'actionable_now': False,
            'reason': (
                'One or more selected new parts are RETAIL_LEAD only. A direct retailer page must prove '
                'same-product identity, item price, stock and mandatory shipping at T1 before KØBSKLAR.'
            ),
            'parts': unresolved,
        })

    p['blockers'] = blockers
    p.setdefault('headline', {})['ready_to_buy_complete_build_today'] = bool(not blockers and fit == 'VERIFIED')
    p['headline']['z20_fit'] = fit
    p['headline']['authoritative_purchase_total'] = (
        p['headline'].get('ask_total') if not unresolved else None
    )
    p['headline']['ask_total_is_reference_only'] = bool(unresolved)
    p['headline']['ask_total_authority'] = (
        'DIRECT_RETAILER_T1' if not unresolved else 'MIXED_WITH_RETAIL_LEAD_NOT_AUTHORITATIVE'
    )

    p['retail_offers_v22'] = {
        'model': offers.get('model'),
        'authority_model': offers.get('authority_model'),
        'products_total': offers.get('products_total'),
        'retail_leads': offers.get('retail_leads'),
        'comparison_offer_candidates': offers.get('retail_leads'),
        'external_routes_resolved': offers.get('external_routes_resolved'),
        'externally_resolved_candidates': offers.get('external_urls_resolved'),
        'retailer_pages_verified': offers.get('retailer_pages_verified'),
        'selected': retail_rows,
        'direct_buy_ready_selected': sum(1 for x in retail_rows if x.get('purchase_ready')),
        'reference_only_selected': sum(1 for x in retail_rows if not x.get('purchase_ready')),
        'rule': (
            'Prisjagt-only prices are RETAIL_LEAD references. BUY_NOW requires direct retailer T1 authority: '
            'same product, current DKK item price, InStock, mandatory shipping, delivered total and direct URL.'
        ),
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
