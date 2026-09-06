from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlparse

import dba_component_optimizer_v19 as core
import dba_retail_motherboard_v22 as mb22
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
    for key in (
        'external_url_resolved',
        'retailer_page_verified',
        'retailer_identity_verified',
        'retailer_price_verified',
        'retailer_stock_verified',
        'retailer_shipping_verified',
    ):
        if offer.get(key) is not True:
            return False
    if offer.get('retailer_authority') != 'DIRECT_RETAILER_T1':
        return False
    url = str(offer.get('buy_url') or '')
    seller = str(offer.get('seller') or '')
    if not url or not seller:
        return False
    host = urlparse(url).netloc.lower()
    if not host or 'prisjagt.dk' in host:
        return False
    delivered = int(offer.get('delivered_price_dkk') or 0)
    item = offer.get('item_price_dkk')
    shipping = offer.get('shipping_dkk')
    if delivered <= 0 or item is None or shipping is None:
        return False
    if delivered != int(item) + int(shipping):
        return False
    return offer.get('delivered_price_method') == 'DIRECT_RETAILER_ITEM_PLUS_MANDATORY_SHIPPING'


def _live_lead_price(offer: dict) -> int | None:
    if offer.get('same_page_price_floor_method') != 'LIVE_OFFER_LIST_CURRENT_CARD_MIN':
        return None
    value = int(offer.get('retail_lead_price_dkk') or offer.get('same_page_lowest_price_dkk') or 0)
    return value or None


def safe_snapshot_candidates(kind: str) -> list[dict]:
    """Direct retailer totals are authoritative; Prisjagt stays RETAIL_LEAD.

    A non-direct candidate may remain in economic comparison only when its
    reference amount comes from the current live comparison-offer list. The
    older product-page/JSON-LD bootstrap price is never allowed to survive as
    the V22 reference because it may represent history/low-price metadata.
    """
    idx = offer_index()
    rows = []
    for c in deepcopy(ORIGINAL_SNAPSHOT(kind)):
        sku = str(c.get('sku') or '')
        offer = idx.get(sku) or {}
        if _is_external_direct_offer(offer):
            delivered = int(offer['delivered_price_dkk'])
            item = int(offer['item_price_dkk'])
            shipping = int(offer['shipping_dkk'])
            c.update({
                'price': delivered,
                'delivered_price_dkk': delivered,
                'item_price_dkk': item,
                'shipping_dkk': shipping,
                'delivered_price_method_v22': offer.get('delivered_price_method'),
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
                'retailer_page_verified_v22': True,
                'retailer_authority_v22': 'DIRECT_RETAILER_T1',
                'same_page_price_floor_method_v22': offer.get('same_page_price_floor_method'),
            })
        else:
            lead = _live_lead_price(offer)
            if lead is None:
                continue
            c.update({
                'price': lead,
                'comparison_url': c.get('url'),
                'price_evidence': 'LIVE_RETAIL_COMPARISON_REFERENCE_V22',
                'availability': 'PRICE_REFERENCE_ONLY_CHECK_STORE',
                'retail_offer_verified_v22': False,
                'external_url_resolved_v22': False,
                'retailer_page_verified_v22': False,
                'retailer_authority_v22': 'RETAIL_LEAD',
                'seller': None,
                'retail_lead_price_dkk_v22': lead,
                'same_page_price_floor_method_v22': offer.get('same_page_price_floor_method'),
            })
        rows.append(c)

    if kind == 'MOTHERBOARD':
        retail_doc = json.loads(RETAIL.read_text(encoding='utf-8'))
        existing = {str(x.get('sku') or '') for x in rows}
        for product in retail_doc.get('products') or []:
            if product.get('motherboard_spec_lead_v22') is not True:
                continue
            promoted = mb22.promoted_candidate(product, product.get('retail_offer_v22') or {})
            if not promoted or str(promoted.get('sku') or '') in existing:
                continue
            ok, failures = core.hard_gate('MOTHERBOARD', promoted)
            assert ok, f'V22 retailer-promoted motherboard failed hard gate: {failures}'
            existing.add(str(promoted.get('sku') or ''))
            rows.append(promoted)
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
            assert c.get('retailer_page_verified_v22') is True
            assert c.get('retailer_authority_v22') == 'DIRECT_RETAILER_T1'
            assert c.get('price_evidence') == 'LIVE_DIRECT_RETAILER_DELIVERED_OFFER_V22'
            assert c.get('seller') and c.get('url')
            assert c.get('availability') == 'IN_STOCK_DIRECT_RETAILER_VERIFIED'
            assert int(c.get('delivered_price_dkk') or 0) == int(c.get('item_price_dkk') or 0) + int(c.get('shipping_dkk') or 0)
            if c.get('dynamic_retailer_promoted_v22') is True:
                assert c.get('retailer_component_spec_gate_passed_v22') is True
                assert c.get('retailer_component_spec_authority_v22') == 'DIRECT_RETAILER_PRODUCT_PAGE_T1'
                assert (c.get('spec_evidence_v22') or {}).get('url')
        else:
            reference += 1
            assert c.get('external_url_resolved_v22') is False
            assert c.get('retailer_page_verified_v22') is False
            assert c.get('retailer_authority_v22') == 'RETAIL_LEAD'
            assert c.get('price_evidence') == 'LIVE_RETAIL_COMPARISON_REFERENCE_V22'
            assert c.get('availability') == 'PRICE_REFERENCE_ONLY_CHECK_STORE'
            assert c.get('same_page_price_floor_method_v22') == 'LIVE_OFFER_LIST_CURRENT_CARD_MIN'
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
    assert gate.get('authority_model') == 'V22_DIRECT_RETAILER_PAGE_T1'
    assert gate.get('required_price_basis') == 'DIRECT_RETAILER_PAGE_ONLY'
    assert gate.get('same_page_floor_basis') == 'LIVE_OFFER_LIST_ONLY'
    assert gate.get('whole_page_floor_forbidden') is True
    assert gate.get('retailer_page_required_for_buy_now') is True
    assert gate.get('mandatory_shipping_required_for_buy_now') is True

    core._snapshot_candidates = safe_snapshot_candidates
    v20.best_new_32gb_price = ORIGINAL_NEW32
    try:
        auth20.main()
    finally:
        core._snapshot_candidates = ORIGINAL_SNAPSHOT
        v20.best_new_32gb_price = ORIGINAL_NEW32

    data = json.loads(STRATEGY.read_text(encoding='utf-8'))
    stats = validate_selected(data)
    coverage = ((data.get('component_market_coverage_v20') or {}).get('v19_coverage') or {})
    coverage_categories = coverage.get('categories') or {}
    print(json.dumps({'V22_LIVE_RETAIL_COVERAGE': coverage_categories}, ensure_ascii=False))
    assert coverage.get('passed') is True, (
        'V22 live retail-lead candidate coverage below minimums: '
        + json.dumps(coverage_categories, ensure_ascii=False, sort_keys=True)
    )

    data['offer_optimizer_v22'] = {
        'active': True,
        'price_basis': 'DIRECT_RETAILER_DELIVERED_IF_VERIFIED_ELSE_LIVE_OFFER_LIST_RETAIL_LEAD',
        'selection_rule': (
            'A new-part acquisition price is authoritative only when the external retailer product page proves '
            'same-product identity, current DKK Offer.price, stock, mandatory shipping and delivered arithmetic. '
            'Prisjagt exact offer cards are RETAIL_LEAD comparison evidence only and can never become BUY_NOW.'
        ),
        'prisjagt_only_policy': 'REFERENCE_ONLY_NEVER_BUY_READY',
        'retail_authority_model': 'V22_DIRECT_RETAILER_PAGE_T1',
        'retail_offer_gate': gate,
        **stats,
    }
    data['procurement_core_version'] = 'V22_DIRECT_RETAILER_FAIL_CLOSED'
    STRATEGY.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

    rec = data.get('recommended_self_build') or {}
    print(json.dumps({
        'V22_SELF_BUILD': True,
        'recommended_tcwp_reference': rec.get('tcwp'),
        'cpu': rec.get('cpu'),
        'gpu': rec.get('gpu'),
        'selected_new_count': stats['selected_new_count'],
        'direct_buy_ready': stats['selected_direct_buy_ready'],
        'reference_only': stats['selected_reference_only'],
        'coverage': coverage.get('passed'),
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
