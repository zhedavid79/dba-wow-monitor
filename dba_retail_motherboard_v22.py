from __future__ import annotations

import hashlib
import re
from urllib.parse import urlparse

import dba_retail_authority_v22 as retail_auth


MODEL_RE = re.compile(r'\b(?:B650M|B850M)\b', re.I)
MATX_RE = re.compile(r'\bMicro[- ]?ATX\b|\bm-?ATX\b', re.I)
AM5_RE = re.compile(r'\bAM5\b|AMD\s+Socket\s+AM5', re.I)
DDR5_RE = re.compile(r'\bDDR5\b', re.I)
WIFI7_RE = re.compile(r'\bWi-?Fi\s*7\b|\b802\.11be\b', re.I)
WIFI6E_RE = re.compile(r'\bWi-?Fi\s*6E\b', re.I)
WIFI6_RE = re.compile(r'\bWi-?Fi\s*6\b|\b802\.11ax\b', re.I)
WIFI_ANY_RE = re.compile(r'\bWi-?Fi\b|\bWireless\b|\bTrådløs(?:t|e)?\b', re.I)
LAN_25_RE = re.compile(
    r'\b(?:2[,.]5\s*(?:Gbit/s|Gbps|GbE|Gigabit(?:\s+Ethernet|\s+LAN)?|G\s*LAN)|'
    r'2500\s*(?:Mbit/s|Mbps))\b',
    re.I,
)


def _norm(value: str) -> str:
    return re.sub(r'\s+', ' ', str(value or '')).strip()


def _sku(url: str) -> str:
    return 'DISC_' + hashlib.sha1(str(url).encode('utf-8')).hexdigest()[:12].upper()


def _first_int(patterns: tuple[str, ...], text: str) -> int | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.I | re.S)
        if match:
            try:
                return int(match.group(1))
            except Exception:
                continue
    return None


def is_motherboard_spec_lead_name(name: str) -> bool:
    return bool(MODEL_RE.search(str(name or '')))


def lead_from_discovery(row: dict) -> dict | None:
    """Turn a verified current comparison product into a non-eligible spec lead.

    The row is intentionally not a component candidate yet.  It merely gives the
    store-offer stage a current exact product URL/name to resolve.  Compatibility
    is established later from a direct external retailer product page.
    """
    if row.get('kind') != 'MOTHERBOARD' or row.get('verified') is not True:
        return None
    name = _norm(row.get('name') or '')
    url = str(row.get('url') or '')
    price = int(row.get('price') or 0)
    if not name or not url or price <= 0 or not is_motherboard_spec_lead_name(name):
        return None
    return {
        'sku': _sku(url),
        'kind': 'MOTHERBOARD',
        'name': name,
        'price': price,
        'url': url,
        'identity_aliases': [name],
        'source': 'NEW RETAIL',
        'verified': True,
        'verified_at': row.get('verified_at'),
        'availability': row.get('availability'),
        'method': 'V22_MOTHERBOARD_SPEC_LEAD',
        'price_evidence': 'LIVE_RETAIL_DISCOVERY_LEAD_NOT_ACQUISITION_AUTHORITY',
        'motherboard_spec_lead_v22': True,
        'optimizer_eligible_v22': False,
        'retailer_authority_v22': 'RETAIL_LEAD',
    }


def extract_retailer_motherboard_specs(expected_name: str, page_text: str) -> dict:
    """Extract hard motherboard facts from one direct retailer product page.

    Facts are label/value or unit-bound and fail closed.  No product-model lookup,
    brand-specific table parser, or inferred Ethernet speed is used.
    """
    text = str(page_text or '')
    model_ok = bool(MODEL_RE.search(str(expected_name or '')))
    matx = bool(MATX_RE.search(text))
    am5 = bool(AM5_RE.search(text))
    ddr5 = bool(DDR5_RE.search(text))

    if WIFI7_RE.search(text):
        wifi = '7'
    elif WIFI6E_RE.search(text):
        wifi = '6E'
    elif WIFI6_RE.search(text):
        wifi = '6'
    elif WIFI_ANY_RE.search(text):
        wifi = 'YES'
    else:
        wifi = ''

    dimm = _first_int((
        r'\b([1-8])\s*(?:x|stk\.?)\s*(?:DDR5\s*)?DIMM\b',
        r'\b(?:DIMM(?:\s+slots?)?|memory\s+slots?|hukommelsespladser)\b.{0,36}?\b([1-8])\b',
        r'\b([1-8])\s*(?:memory\s+slots?|RAM\s+slots?)\b',
    ), text)

    m2 = _first_int((
        r'\b([2-6])\s*(?:x|stk\.?)\s*M\.?2\b',
        r'\bM\.?2\s*(?:slots?|sockets?|porte?|stik)?\s*[:\-]?\s*([2-6])\b',
        r'\bM\.?2\b.{0,28}?\b(?:antal|slots?|sockets?|porte?|stik)\b.{0,18}?\b([2-6])\b',
    ), text)

    lan = 2.5 if LAN_25_RE.search(text) else 0.0
    pcie5_m2 = bool(
        re.search(r'PCI(?:e| Express)?\s*5(?:\.0)?.{0,60}M\.?2', text, re.I | re.S)
        or re.search(r'M\.?2.{0,60}PCI(?:e| Express)?\s*5(?:\.0)?', text, re.I | re.S)
    )
    pcie5_x16 = bool(re.search(r'PCI(?:e| Express)?\s*5(?:\.0)?.{0,30}x16', text, re.I | re.S))
    bios_flashback = bool(re.search(r'BIOS\s+Flashback|Flash\s+BIOS|Q-Flash\s+Plus', text, re.I))
    front_usb_c = bool(
        re.search(r'(?:front|frontpanel|front panel).{0,45}(?:USB[- ]?C|Type[- ]?C)', text, re.I | re.S)
        or re.search(r'(?:USB[- ]?C|Type[- ]?C).{0,45}(?:front|frontpanel|front panel)', text, re.I | re.S)
    )

    checks = (
        (model_ok, 'B650M/B850M'),
        (matx, 'mATX'),
        (am5, 'AM5'),
        (ddr5, 'DDR5'),
        (bool(wifi), 'Wi-Fi'),
        (int(dimm or 0) >= 4, '4 DIMM'),
        (int(m2 or 0) >= 2, '>=2 M.2'),
        (lan >= 2.5, '2.5GbE'),
    )
    missing = [label for ok, label in checks if not ok]
    return {
        'passed': not missing,
        'missing': missing,
        'socket': 'AM5' if am5 else None,
        'form_factor': 'mATX' if matx else None,
        'ddr': 'DDR5' if ddr5 else None,
        'dimm_slots': int(dimm or 0),
        'wifi': wifi or None,
        'lan_gbps': lan,
        'm2_count': int(m2 or 0),
        'pcie5_m2': pcie5_m2,
        'pcie5_x16': pcie5_x16,
        'bios_flashback': bios_flashback,
        'front_usb_c': front_usb_c,
        'evidence_model': 'DIRECT_RETAILER_PRODUCT_PAGE_HARD_SPEC_TEXT_V22',
    }


async def verify_retailer_motherboard_specs(context, direct_url: str, expected_name: str) -> dict:
    result = {
        'retailer_component_spec_gate_passed': False,
        'retailer_component_spec_authority': 'UNPROVEN',
        'retailer_component_specs': None,
        'retailer_component_spec_url': None,
    }
    parsed = urlparse(str(direct_url or ''))
    if not parsed.scheme.startswith('http') or not parsed.netloc or 'prisjagt.dk' in parsed.netloc.lower():
        result['retailer_component_spec_error'] = 'NO_EXTERNAL_RETAILER_URL'
        return result

    page = await context.new_page()
    try:
        response = await page.goto(direct_url, wait_until='domcontentloaded', timeout=35000)
        status = int(response.status) if response else None
        final_url = str(page.url)
        host = urlparse(final_url).netloc.lower().removeprefix('www.')
        if not host or 'prisjagt.dk' in host or (status is not None and status >= 400):
            result['retailer_component_spec_error'] = 'RETAILER_SPEC_PAGE_UNREACHABLE'
            return result

        title = await page.title()
        try:
            h1 = (await page.locator('h1').first.inner_text(timeout=2500)).strip()
        except Exception:
            h1 = ''
        identity_text = ' '.join([title, h1])
        if not retail_auth._same_product_identity(expected_name, identity_text):
            result['retailer_component_spec_error'] = 'RETAILER_SPEC_PRODUCT_IDENTITY_UNPROVEN'
            return result

        try:
            visible = await page.locator('body').inner_text(timeout=7000)
        except Exception:
            visible = ''
        try:
            dom_text = await page.locator('body').text_content(timeout=7000) or ''
        except Exception:
            dom_text = ''
        evidence = (visible + '\n' + dom_text)[:220000]
        specs = extract_retailer_motherboard_specs(expected_name, evidence)
        result.update({
            'retailer_component_spec_gate_passed': specs['passed'],
            'retailer_component_spec_authority': (
                'DIRECT_RETAILER_PRODUCT_PAGE_T1' if specs['passed'] else 'UNPROVEN'
            ),
            'retailer_component_specs': specs,
            'retailer_component_spec_url': final_url,
        })
        if not specs['passed']:
            result['retailer_component_spec_error'] = 'MOTHERBOARD_HARD_SPECS_UNPROVEN:' + ','.join(specs['missing'])
        return result
    except Exception as exc:
        result['retailer_component_spec_error'] = f'{type(exc).__name__}: {str(exc)[:200]}'
        return result
    finally:
        await page.close()


def promoted_candidate(product: dict, offer: dict) -> dict | None:
    """Promote a spec lead only when the same direct retailer is fully authoritative."""
    if product.get('motherboard_spec_lead_v22') is not True:
        return None
    if offer.get('delivered_price_verified') is not True:
        return None
    if offer.get('retailer_authority') != 'DIRECT_RETAILER_T1':
        return None
    if offer.get('retailer_component_spec_gate_passed') is not True:
        return None
    if offer.get('retailer_component_spec_authority') != 'DIRECT_RETAILER_PRODUCT_PAGE_T1':
        return None
    for key in (
        'external_url_resolved',
        'retailer_page_verified',
        'retailer_identity_verified',
        'retailer_price_verified',
        'retailer_stock_verified',
        'retailer_shipping_verified',
    ):
        if offer.get(key) is not True:
            return None

    url = str(offer.get('buy_url') or '')
    if not url or 'prisjagt.dk' in urlparse(url).netloc.lower():
        return None
    delivered = int(offer.get('delivered_price_dkk') or 0)
    item = offer.get('item_price_dkk')
    shipping = offer.get('shipping_dkk')
    if delivered <= 0 or item is None or shipping is None or delivered != int(item) + int(shipping):
        return None
    specs = offer.get('retailer_component_specs') or {}
    if not specs.get('passed'):
        return None

    return {
        'sku': str(product.get('sku') or _sku(product.get('url') or url)),
        'kind': 'MOTHERBOARD',
        'name': _norm(product.get('name') or ''),
        'identity_aliases': [_norm(product.get('name') or '')],
        'source': 'NEW RETAIL',
        'price': delivered,
        'delivered_price_dkk': delivered,
        'item_price_dkk': int(item),
        'shipping_dkk': int(shipping),
        'url': url,
        'comparison_url': product.get('url'),
        'seller': offer.get('seller'),
        'availability': 'IN_STOCK_DIRECT_RETAILER_VERIFIED',
        'price_evidence': 'LIVE_DIRECT_RETAILER_DELIVERED_OFFER_V22',
        'retail_offer_verified_v22': True,
        'external_url_resolved_v22': True,
        'retailer_page_verified_v22': True,
        'retailer_authority_v22': 'DIRECT_RETAILER_T1',
        'same_page_price_floor_method_v22': offer.get('same_page_price_floor_method'),
        'delivered_price_method_v22': offer.get('delivered_price_method'),
        'socket': specs.get('socket'),
        'form_factor': specs.get('form_factor'),
        'ddr': specs.get('ddr'),
        'dimm_slots': int(specs.get('dimm_slots') or 0),
        'wifi': specs.get('wifi'),
        'lan_gbps': float(specs.get('lan_gbps') or 0),
        'm2_count': int(specs.get('m2_count') or 0),
        'pcie5_m2': bool(specs.get('pcie5_m2')),
        'pcie5_x16': bool(specs.get('pcie5_x16')),
        'power_tier': 1,
        'drmos': False,
        'bios_flashback': bool(specs.get('bios_flashback')),
        'front_usb_c': bool(specs.get('front_usb_c')),
        'dynamic_discovery_v22': True,
        'dynamic_retailer_promoted_v22': True,
        'retailer_component_spec_gate_passed_v22': True,
        'retailer_component_spec_authority_v22': 'DIRECT_RETAILER_PRODUCT_PAGE_T1',
        'spec_evidence_v22': {
            'source': 'DIRECT_RETAILER_PRODUCT_PAGE_T1',
            'url': offer.get('retailer_component_spec_url') or url,
            'specs': specs,
        },
    }


def regression() -> None:
    sample = '''
    ASRock B850M Pro RS WiFi
    Motherboard - AMD B850 - AMD AM5 socket - DDR5 RAM - Micro-ATX
    Hukommelse: 4 x DIMM DDR5
    M.2 Socket 3
    Wi-Fi 6E
    Netværk 2.5 Gigabit Ethernet
    PCI Express 5.0 x16
    '''
    specs = extract_retailer_motherboard_specs('ASRock B850M Pro RS WiFi', sample)
    assert specs['passed'], specs
    assert specs['dimm_slots'] == 4
    assert specs['m2_count'] == 3
    assert specs['lan_gbps'] == 2.5
    assert specs['wifi'] == '6E'

    weak = sample.replace('4 x DIMM DDR5', '2 x DIMM DDR5')
    weak_specs = extract_retailer_motherboard_specs('ASRock B850M Pro RS WiFi', weak)
    assert weak_specs['passed'] is False
    assert '4 DIMM' in weak_specs['missing']


regression()
