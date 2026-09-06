from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlparse

import dba_component_optimizer_v19 as core
import dba_self_build_v20 as v20
import dba_self_build_v20_authoritative as auth20

RETAIL = Path('results/retail_prices_latest.json')
STRATEGY = Path('results/wow_strategy_latest.json')
ORIGINAL_SNAPSHOT = core._snapshot_candidates
ORIGINAL_NEW32 = v20.best_new_32gb_price


def offer_index() -> dict[str, dict]:
    doc = json.loads(RETAIL.read_text(encoding='utf-8'))
    return {
        str(p.get('sku')): (p.get('retail_offer_v22') or {})
        for p in doc.get('products') or []
        if p.get('sku')
    }


def _is_external_direct_offer(offer: dict) -> bool:
    if offer.get('delivered_price_verified') is not True:
        return False
    if offer.get('external_url_resolved') is not True:
        return False
    url = str(offer.get('buy_url') or '')
    seller = str(offer.get('seller') or '')
    if not url or not seller:
        return False
    host = urlparse(url).netloc.lower()
    if not host or 'prisjagt.dk' in host:
        return False
    return int(offer.get('delivered_price_dkk') or 0) > 0


def safe_snapshot_candidates(kind: str) -> list[dict]:
    """Use a real retailer-delivered price only when the external retailer
    itself was resolved. Otherwise retain the independently same-product-
    verified comparison price as a non-buy-ready market reference.
    """
    idx = offer_index()
    rows = []
    for c in deepcopy(ORIGINAL_SNAPSHOT(kind)):
        sku = str(c.get('sku') or '')
        offer = idx.get(sku) or {}
        if _is_external_direct_offer(offer):
            delivered = int(offer['delivered_price_dkk'])
            item = offer.get('item_price_dkk')
            shipping = offer.get('shipping_dkk')
            method = str(offer.get('delivered_price_method') or '')
            if method == 'ITEM_PLUS_EXACT_SHIPPING':
                if item is None or shipping is None or delivered != int(item) + int(shipping):
                    continue
            elif method != 'PRISJAGT_PRICE_INCL_DELIVERY':
                continue
            c.update({
                'price': delivered,
                'delivered_price_dkk': delivered,
                'item_price_dkk': item,
                'shipping_dkk': shipping,
                'delivered_price_method_v22': method,
                'seller': offer.get('seller'),
                'comparison_url': c.get('url'),
                'url': offer.get('buy_url'),
                'deal_type_v22': offer.get('deal_type'),
                'normal_price_dkk_v22': offer.get('normal_price_dkk'),
                'market_reference_delivered_dkk_v22': offer.get('market_reference_delivered_dkk'),
                'price_evidence': 'LIVE_DIRECT_RETAILER_DELIVERED_OFFER_V22',
                'availability': 'IN_STOCK_DIRECT_RETAILER_VERIFIED',
                'retail_offer_verified_v22': True,
                'external_url_resolved_v22': True,
            })
        else:
            c.update({
                'comparison_url': c.get('url'),
                'price_evidence': 'LIVE_RETAIL_COMPARISON_REFERENCE_V22',
                'availability': 'PRICE_REFERENCE_ONLY_CHECK_STORE',
                'retail_offer_verified_v22': False,
                'external_url_resolved_v22': False,
                'seller': None,
            })
        rows.append(c)
    return rows


def validate_selected(data: dict) -> dict:
    rec = data.get('recommended_self_build') or {}
    new = [c for c in rec.get('components') or [] if c.get('source') == 'NEW RETAIL']
    assert new, 'V22 selected no NEW RETAIL components'
    direct = 0
    reference = 0
    for c in new:
        if c.get('retail_offer_verified_v22') is True:
            direct += 1
            assert c.get('external_url_resolved_v22') is True
            assert c.get('price_evidence') == 'LIVE_DIRECT_RETAILER_DELIVERED_OFFER_V22'
            assert c.get('seller') and c.get('url')
            assert c.get('availability') == 'IN_STOCK_DIRECT_RETAILER_VERIFIED'
        else:
            reference += 1
            assert c.get('external_url_resolved_v22') is False
            assert c.get('price_evidence') == 'LIVE_RETAIL_COMPARISON_REFERENCE_V22'
            assert c.get('availability') == 'PRICE_REFERENCE_ONLY_CHECK_STORE'
    return {
        'selected_new_count': len(new),
        'selected_direct_buy_ready': direct,
        'selected_reference_only': reference,
        'selected_price_reference_total': sum(int(c.get('price') or 0) for c in new),
    }


def main() -> None:
    retail = json.loads(RETAIL.read_text(encoding='utf-8'))
    gate = retail.get('offer_gate_v22') or {}
    assert gate.get('model') == 'V22_STORE_LEVEL_DELIVERED_PRICE_AND_DEALS'

    core._snapshot_candidates = safe_snapshot_candidates
    # RAM bridge economics may use the live same-product retail snapshot, but
    # Prisjagt-only store-card amounts never become buy-ready acquisition costs.
    v20.best_new_32gb_price = ORIGINAL_NEW32
    try:
        auth20.main()
    finally:
        core._snapshot_candidates = ORIGINAL_SNAPSHOT
        v20.best_new_32gb_price = ORIGINAL_NEW32

    data = json.loads(STRATEGY.read_text(encoding='utf-8'))
    stats = validate_selected(data)
    coverage = ((data.get('component_market_coverage_v20') or {}).get('v19_coverage') or {})
    assert coverage.get('passed') is True, 'V22 retail reference candidate coverage below minimums'

    data['offer_optimizer_v22'] = {
        'active': True,
        'price_basis': 'DIRECT_RETAILER_DELIVERED_IF_VERIFIED_ELSE_LIVE_COMPARISON_REFERENCE',
        'selection_rule': (
            'A store offer may change the authoritative acquisition price only when the external retailer URL, '
            'same product, current price and stock are verified. Prisjagt-only offer cards are discovery/comparison '
            'leads and can never become BUY_NOW or a purchase-ready delivered price.'
        ),
        'prisjagt_only_policy': 'REFERENCE_ONLY_NEVER_BUY_READY',
        'retail_offer_gate': gate,
        **stats,
    }
    data['procurement_core_version'] = 'V22_DIRECT_RETAILER_FAIL_CLOSED'
    STRATEGY.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

    rec = data.get('recommended_self_build') or {}
    print(json.dumps({
        'V22_SELF_BUILD': True,
        'recommended_tcwp': rec.get('tcwp'),
        'cpu': rec.get('cpu'),
        'gpu': rec.get('gpu'),
        'selected_new_count': stats['selected_new_count'],
        'direct_buy_ready': stats['selected_direct_buy_ready'],
        'reference_only': stats['selected_reference_only'],
        'coverage': coverage.get('passed'),
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
