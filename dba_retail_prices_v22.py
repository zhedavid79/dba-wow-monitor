from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import dba_retail_prices_v20 as base

OUT = Path('results/retail_prices_latest.json')

# V20 deliberately sampled only eight products per discovery seed. V22 searches
# deeper in every proven category page so sale/outlet-priced substitutes have a
# realistic chance to enter the compatible candidate universe before scoring.
MAX_LINKS_PER_SEED_V22 = 20
ORIGINAL_INFER_CANDIDATE = base.infer_candidate


def augment_discovery_body_v22(kind: str, body: str) -> str:
    """Normalize equivalent Prisjagt spec labels before V20 hard-gate inference.

    Prisjagt's Danish product-spec table commonly renders a label first and the
    value on the next line (for example ``Hukommelsespladser / 4 stk`` and
    ``M.2 / 3 stk``).  The V20 parser only recognizes the inverse English-style
    forms.  V22 adds canonical aliases only when the concrete value is present
    in the current product page; no specification is guessed from model names.
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

    return text + ('\n' + '\n'.join(aliases) if aliases else '')


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
    assert '4 DIMM' in augmented
    assert '3 x M.2' in augmented
    assert '2.5GbE' in augmented
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


async def main() -> None:
    regression()
    base.MAX_LINKS_PER_SEED = MAX_LINKS_PER_SEED_V22
    base.infer_candidate = infer_candidate_v22
    try:
        await base.main()
    finally:
        base.infer_candidate = ORIGINAL_INFER_CANDIDATE
    doc = json.loads(OUT.read_text(encoding='utf-8'))
    doc['deal_discovery_v22'] = {
        'active': True,
        'max_product_links_per_seed': MAX_LINKS_PER_SEED_V22,
        'seed_count': sum(len(v) for v in base.DISCOVERY_SEEDS.values()),
        'prisjagt_spec_normalization': 'CURRENT_PRODUCT_PAGE_EXPLICIT_VALUES_ONLY',
        'policy': 'Actively inspect a deeper live retail universe before store-level offer comparison. Compatibility evidence remains fail-closed; a cheap product cannot win without the category hard gates.',
    }
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({
        'V22_RETAIL_DISCOVERY': True,
        'dynamic_inspected': (doc.get('counts') or {}).get('dynamic_inspected'),
        'dynamic_admitted': (doc.get('counts') or {}).get('dynamic_admitted'),
        'max_links_per_seed': MAX_LINKS_PER_SEED_V22,
        'spec_normalization': 'CURRENT_PRODUCT_PAGE_EXPLICIT_VALUES_ONLY',
    }, ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(main())
