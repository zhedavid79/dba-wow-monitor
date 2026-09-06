from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import dba_retail_motherboard_v22 as mb22
import dba_retail_prices_v20 as base

OUT = Path('results/retail_prices_latest.json')
DISCOVERY_OUT = Path('results/retail_discovery_v20.json')

# V20 deliberately sampled only eight products per discovery seed. V22 searches
# deeper and uses the live B850/B650 motherboard category pages so suitable mATX
# boards are not hidden by one generic-search ordering.
MAX_LINKS_PER_SEED_V22 = 20
MOTHERBOARD_SEEDS_V22 = [
    'https://prisjagt.dk/c/bundkort?615=44097',  # AMD B850
    'https://prisjagt.dk/c/bundkort?615=39813',  # AMD B650
]
ORIGINAL_INFER_CANDIDATE = base.infer_candidate
ORIGINAL_DISCOVERY_SEEDS = {k: list(v) for k, v in base.DISCOVERY_SEEDS.items()}
ORIGINAL_MAX_LINKS = base.MAX_LINKS_PER_SEED


def augment_discovery_body_v22(kind: str, body: str) -> str:
    """Normalize only explicit current Prisjagt label/value facts.

    This helper remains useful when Prisjagt actually exposes a complete spec
    set. Incomplete motherboard pages are *not* forced through the compatibility
    gate; they become non-eligible SPEC_LEAD rows and require direct retailer
    hard-spec authority later in V22.
    """
    text = str(body or '')
    if kind != 'MOTHERBOARD':
        return text

    aliases: list[str] = []
    dimm = re.search(
        r'\bhukommelsespladser\s*(?:\n|\r|:|-|\s)+\s*([1-8])\s*stk\b',
        text,
        re.I,
    )
    if dimm:
        aliases.append(f'{int(dimm.group(1))} DIMM')

    m2 = re.search(
        r'(?<![A-Za-z0-9])M\.?2\s*(?:\n|\r|:|-|\s)+\s*([1-6])\s*stk\b',
        text,
        re.I,
    )
    if m2:
        aliases.append(f'{int(m2.group(1))} x M.2')

    lan = re.search(
        r'\bmaks\.?\s*ethernet[- ]?hastighed\s*(?:\n|\r|:|-|\s)+\s*'
        r'(2[,.]5|5|10)\s*gbit/s\b',
        text,
        re.I,
    )
    if lan:
        aliases.append(f"{lan.group(1).replace(',', '.')}GbE")

    return ('\n'.join(aliases) + '\n' if aliases else '') + text


def infer_candidate_v22(
    kind: str,
    name: str,
    body: str,
    url: str,
    price: int,
    availability: str,
    verified_at: str,
):
    return ORIGINAL_INFER_CANDIDATE(
        kind,
        name,
        augment_discovery_body_v22(kind, body),
        url,
        price,
        availability,
        verified_at,
    )


def _norm_url(url: str) -> str:
    return str(url or '').split('#')[0].rstrip('/')


def append_motherboard_spec_leads(doc: dict) -> int:
    """Expose verified current products to store-resolution without admitting them.

    A SPEC_LEAD is intentionally absent from dynamic_admitted_products. It cannot
    influence optimizer coverage or ranking until dba_retail_offers_v22 verifies
    a direct retailer page and dba_self_build_v22_authoritative promotes it.
    """
    if not DISCOVERY_OUT.exists():
        return 0
    audit = json.loads(DISCOVERY_OUT.read_text(encoding='utf-8'))
    products = doc.setdefault('products', [])
    existing = {_norm_url(x.get('url')) for x in products if x.get('url')}
    added = 0
    for row in audit.get('dynamic_results') or []:
        lead = mb22.lead_from_discovery(row)
        if not lead:
            continue
        url = _norm_url(lead.get('url'))
        if not url or url in existing:
            continue
        existing.add(url)
        products.append(lead)
        added += 1
    counts = doc.setdefault('counts', {})
    counts['motherboard_spec_leads_v22'] = added
    counts['total_products_with_spec_leads_v22'] = len(products)
    doc['motherboard_spec_lead_gate_v22'] = {
        'model': 'V22_DYNAMIC_MOTHERBOARD_SPEC_LEAD',
        'leads_added': added,
        'optimizer_eligible_at_discovery': 0,
        'promotion_requirement': 'DIRECT_RETAILER_PRODUCT_PAGE_T1_HARD_SPECS_AND_DIRECT_RETAILER_PRICE_AUTHORITY',
    }
    return added


def regression() -> None:
    sample = '''
    Asus Example B850M WiFi
    Formfaktor\nMicro ATX
    Stikkontakt\nAMD Socket AM5
    Hukommelsestype\nDDR5
    Trådløst netværk (Wi-Fi)\nJa
    Hukommelsespladser\n4 stk
    M.2\n3 stk
    Maks. Ethernet-hastighed\n2.5 Gbit/s
    '''
    augmented = augment_discovery_body_v22('MOTHERBOARD', sample)
    assert augmented.startswith('4 DIMM\n3 x M.2\n2.5GbE\n')
    candidate, missing = infer_candidate_v22(
        'MOTHERBOARD',
        'Asus Example B850M WiFi',
        sample,
        'https://prisjagt.dk/product.php?p=1',
        1200,
        'InStock',
        '2026-09-06T00:00:00+00:00',
    )
    assert candidate is not None, missing
    assert candidate['dimm_slots'] == 4
    assert candidate['m2_count'] == 3
    assert candidate['lan_gbps'] == 2.5

    lead = mb22.lead_from_discovery({
        'kind': 'MOTHERBOARD',
        'verified': True,
        'name': 'MSI MAG B850M Mortar WIFI',
        'url': 'https://prisjagt.dk/product.php?p=99',
        'price': 1500,
        'verified_at': '2026-09-06T00:00:00+00:00',
        'availability': 'InStock',
    })
    assert lead and lead['optimizer_eligible_v22'] is False


async def main() -> None:
    regression()
    used_seeds = {k: list(v) for k, v in ORIGINAL_DISCOVERY_SEEDS.items()}
    used_seeds['MOTHERBOARD'] = list(MOTHERBOARD_SEEDS_V22)
    base.MAX_LINKS_PER_SEED = MAX_LINKS_PER_SEED_V22
    base.DISCOVERY_SEEDS = used_seeds
    base.infer_candidate = infer_candidate_v22
    try:
        await base.main()
    finally:
        base.infer_candidate = ORIGINAL_INFER_CANDIDATE
        base.DISCOVERY_SEEDS = ORIGINAL_DISCOVERY_SEEDS
        base.MAX_LINKS_PER_SEED = ORIGINAL_MAX_LINKS

    doc = json.loads(OUT.read_text(encoding='utf-8'))
    spec_leads = append_motherboard_spec_leads(doc)
    doc['deal_discovery_v22'] = {
        'active': True,
        'max_product_links_per_seed': MAX_LINKS_PER_SEED_V22,
        'seed_count': sum(len(v) for v in used_seeds.values()),
        'motherboard_seed_model': 'B850_AND_B650_CATEGORY_PAGES',
        'prisjagt_spec_normalization': 'CURRENT_PRODUCT_PAGE_EXPLICIT_VALUES_ONLY',
        'motherboard_spec_leads': spec_leads,
        'policy': (
            'Actively inspect a deeper live retail universe before store-level offer comparison. '
            'Incomplete current motherboard specs remain non-eligible SPEC_LEADs. Only a direct external '
            'retailer page that independently proves all motherboard hard specs and direct price authority '
            'may promote a lead into the optimizer universe.'
        ),
    }
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({
        'V22_RETAIL_DISCOVERY': True,
        'dynamic_inspected': (doc.get('counts') or {}).get('dynamic_inspected'),
        'dynamic_admitted': (doc.get('counts') or {}).get('dynamic_admitted'),
        'motherboard_spec_leads': spec_leads,
        'products_for_offer_resolution': len(doc.get('products') or []),
        'max_links_per_seed': MAX_LINKS_PER_SEED_V22,
        'motherboard_seed_model': 'B850_AND_B650_CATEGORY_PAGES',
    }, ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(main())
