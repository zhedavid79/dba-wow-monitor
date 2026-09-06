from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import dba_retail_prices_v20 as base

OUT = Path('results/retail_prices_latest.json')

# V20 deliberately sampled only eight products per discovery seed. V22 searches
# deeper and uses chipset category pages for motherboards so the dynamic universe
# is not biased by one free-text search ordering.
MAX_LINKS_PER_SEED_V22 = 20
MOTHERBOARD_SEEDS_V22 = [
    'https://prisjagt.dk/c/bundkort?615=44097',  # AMD B850 category
    'https://prisjagt.dk/c/bundkort?615=39813',  # AMD B650 category
]
ORIGINAL_DISCOVERY_SEEDS = {k: list(v) for k, v in base.DISCOVERY_SEEDS.items()}
ORIGINAL_MAX_LINKS = base.MAX_LINKS_PER_SEED
ORIGINAL_INSPECT_DYNAMIC = base.inspect_dynamic

STATIC_MOTHERBOARD_URLS = {
    str(row.get('url') or '').split('#')[0].rstrip('/')
    for row in (base.market.RETAIL_CANDIDATES.get('MOTHERBOARD') or [])
    if row.get('url')
}


def _norm(s: str) -> str:
    return re.sub(r'\s+', ' ', str(s or '')).strip()


def _field_int(pattern: str, text: str) -> int | None:
    m = re.search(pattern, text, re.I)
    return int(m.group(1)) if m else None


def extract_motherboard_specs_v22(spec_text: str) -> dict:
    """Extract only exact label-bound motherboard hard-gate facts.

    ``Locator.inner_text()`` omits Prisjagt's collapsed detailed specifications.
    ``text_content()`` includes those DOM text nodes, but V22 never feeds that
    whole hidden text into generic inference. Only values immediately bound to
    known specification labels are promoted to evidence.
    """
    text = str(spec_text or '')
    dimm = _field_int(r'\bHukommelsespladser\s*([1-8])\s*stk\b', text)
    m2 = _field_int(r'(?<![A-Za-z0-9])M\.?2\s*([1-6])\s*stk\b', text)

    lan_match = re.search(
        r'\bMaks\.?\s*Ethernet[- ]?hastighed\s*(2[,.]5|5|10)\s*Gbit/s\b',
        text,
        re.I,
    )
    lan = float(lan_match.group(1).replace(',', '.')) if lan_match else None

    wifi_match = re.search(
        r'\bTrådløst netværk\s*\(Wi-?Fi\)\s*(Ja|Nej)\b',
        text,
        re.I,
    )
    wifi_present = bool(wifi_match and wifi_match.group(1).lower() == 'ja')

    return {
        'dimm_slots': dimm,
        'm2_count': m2,
        'lan_gbps': lan,
        'wifi_present': wifi_present,
        'wifi_boolean_proven': bool(wifi_match),
    }


def infer_motherboard_v22(
    name: str,
    visible_body: str,
    spec_text: str,
    url: str,
    price: int,
    availability: str,
    verified_at: str,
) -> tuple[dict | None, list[str]]:
    visible = _norm(str(name or '') + '\n' + str(visible_body or '')[:30000])
    specs = extract_motherboard_specs_v22(spec_text)
    missing: list[str] = []

    model_ok = bool(re.search(r'\b(?:B650M|B850M)\b', str(name or ''), re.I))
    matx = bool(re.search(r'\bMicro[- ]?ATX\b|\bm-?ATX\b', visible, re.I))
    am5 = bool(re.search(r'\bAM5\b|AMD Socket AM5', visible, re.I))
    ddr5 = bool(re.search(r'\bDDR5\b', visible, re.I))
    wifi = specs['wifi_present']
    dimm = int(specs['dimm_slots'] or 0)
    m2 = int(specs['m2_count'] or 0)
    lan = float(specs['lan_gbps'] or 0)

    for ok, label in (
        (model_ok, 'B650M/B850M'),
        (matx, 'mATX'),
        (am5, 'AM5'),
        (ddr5, 'DDR5'),
        (wifi, 'Wi-Fi'),
        (dimm >= 4, '4 DIMM'),
        (m2 >= 2, '>=2 M.2'),
        (lan >= 2.5, '2.5GbE'),
    ):
        if not ok:
            missing.append(label + ' unproven')

    if missing:
        return None, missing

    spec_norm = _norm(spec_text)
    pcie5_m2 = bool(
        re.search(r'\bM\.2 PCIe Gen5\s*Ja\b', spec_norm, re.I)
        or re.search(r'\bPCIe\s*5(?:\.0)?.{0,40}M\.?2\b', spec_norm, re.I)
    )

    return {
        'sku': base._sku(url),
        'name': _norm(name),
        'price': int(price),
        'url': url,
        'identity_aliases': [_norm(name)],
        'source': 'NEW RETAIL',
        'verified_at': verified_at,
        'availability': availability,
        'price_evidence': 'LIVE_RETAIL_DISCOVERY',
        'dynamic_discovery_v20': True,
        'dynamic_discovery_v22': True,
        'kind': 'MOTHERBOARD',
        'socket': 'AM5',
        'form_factor': 'mATX',
        'ddr': 'DDR5',
        'dimm_slots': dimm,
        'wifi': '6',
        'lan_gbps': lan,
        'm2_count': m2,
        'pcie5_m2': pcie5_m2,
        'pcie5_x16': False,
        'power_tier': 1,
        'drmos': False,
        'bios_flashback': False,
        'front_usb_c': False,
        'spec_evidence_v22': {
            'source': 'CURRENT_PRODUCT_PAGE_LABEL_BOUND_DOM_TEXT',
            'dimm_slots': dimm,
            'm2_count': m2,
            'lan_gbps': lan,
            'wifi_boolean_proven': specs['wifi_boolean_proven'],
            'wifi_present': wifi,
        },
    }, []


async def inspect_dynamic_v22(context, kind: str, url: str, sem: asyncio.Semaphore) -> dict:
    if kind != 'MOTHERBOARD':
        return await ORIGINAL_INSPECT_DYNAMIC(context, kind, url, sem)

    async with sem:
        page = await context.new_page()
        now = datetime.now(timezone.utc).isoformat()
        result = {
            'kind': kind,
            'url': url,
            'verified': False,
            'admitted': False,
            'verified_at': now,
            'evidence_model_v22': 'VISIBLE_PRODUCT_TEXT_PLUS_LABEL_BOUND_DOM_SPECS',
        }
        try:
            response = await page.goto(url, wait_until='domcontentloaded', timeout=45000)
            result['http_status'] = int(response.status) if response else None

            scripts = await page.locator('script[type="application/ld+json"]').all_text_contents()
            products = []
            for text in scripts:
                try:
                    blob = json.loads(text)
                except Exception:
                    continue
                for d in base.base.walk(blob):
                    typ = d.get('@type')
                    types = typ if isinstance(typ, list) else [typ]
                    if any(str(x).lower() == 'product' for x in types if x):
                        products.append(d)
            if not products:
                result['error'] = 'NO_JSON_LD_PRODUCT'
                return result

            chosen = None
            for prod in products:
                offers = prod.get('offers')
                objs = offers if isinstance(offers, list) else [offers] if isinstance(offers, dict) else []
                prices = []
                for offer in objs:
                    p = base.base.numeric_price(offer.get('price')) or base.base.numeric_price(offer.get('lowPrice'))
                    if p:
                        prices.append((p, offer))
                if prices:
                    prices.sort(key=lambda x: x[0])
                    chosen = (prod, prices[0][0], prices[0][1])
                    break
            if not chosen:
                result['error'] = 'NO_LIVE_OFFER'
                return result

            prod, price, offer = chosen
            name = str(prod.get('name') or await page.title())
            visible_body = (await page.locator('body').inner_text(timeout=7000))[:40000]
            dom_text = (await page.locator('body').text_content(timeout=7000) or '')[:160000]
            availability = str(offer.get('availability') or 'AVAILABLE_COMPARISON')
            candidate, missing = infer_motherboard_v22(
                name,
                visible_body,
                dom_text,
                url,
                price,
                availability,
                now,
            )
            result.update({
                'verified': True,
                'name': name,
                'price': price,
                'availability': availability,
                'missing_evidence': missing,
                'spec_probe_v22': extract_motherboard_specs_v22(dom_text),
            })

            normalized_url = str(url or '').split('#')[0].rstrip('/')
            if candidate and normalized_url in STATIC_MOTHERBOARD_URLS:
                result['duplicate_static_product'] = True
                result['missing_evidence'] = ['DUPLICATE_STATIC_PRODUCT']
                candidate = None

            if candidate:
                result['admitted'] = True
                result['candidate'] = candidate
            return result
        except Exception as exc:
            result['error'] = f'{type(exc).__name__}: {str(exc)[:200]}'
            return result
        finally:
            await page.close()


def regression() -> None:
    visible = 'Asus Example B850M WiFi Formfaktor Micro ATX Stikkontakt AMD Socket AM5 Hukommelsestype DDR5'
    hidden = (
        'Trådløst netværk (Wi-Fi)Ja '
        'Hukommelsespladser4 stk '
        'M.23 stk '
        'Maks. Ethernet-hastighed2.5 Gbit/s '
        'M.2 PCIe Gen5Ja'
    )
    specs = extract_motherboard_specs_v22(hidden)
    assert specs == {
        'dimm_slots': 4,
        'm2_count': 3,
        'lan_gbps': 2.5,
        'wifi_present': True,
        'wifi_boolean_proven': True,
    }, specs

    candidate, missing = infer_motherboard_v22(
        'Asus Example B850M WiFi',
        visible,
        hidden,
        'https://prisjagt.dk/product.php?p=1',
        1200,
        'InStock',
        '2026-09-06T00:00:00+00:00',
    )
    assert candidate is not None, missing
    assert candidate['dimm_slots'] == 4
    assert candidate['m2_count'] == 3
    assert candidate['lan_gbps'] == 2.5
    assert candidate['wifi'] == '6'

    no_wifi = hidden.replace('Trådløst netværk (Wi-Fi)Ja', 'Trådløst netværk (Wi-Fi)Nej')
    rejected, missing = infer_motherboard_v22(
        'Asus Example B850M',
        visible,
        no_wifi,
        'https://prisjagt.dk/product.php?p=2',
        1000,
        'InStock',
        '2026-09-06T00:00:00+00:00',
    )
    assert rejected is None and 'Wi-Fi unproven' in missing, missing

    weak = hidden.replace('Hukommelsespladser4 stk', 'Hukommelsespladser2 stk')
    rejected, missing = infer_motherboard_v22(
        'Asus Example B850M WiFi',
        visible,
        weak,
        'https://prisjagt.dk/product.php?p=3',
        800,
        'InStock',
        '2026-09-06T00:00:00+00:00',
    )
    assert rejected is None and '4 DIMM unproven' in missing, missing


async def main() -> None:
    regression()

    used_seeds = {k: list(v) for k, v in ORIGINAL_DISCOVERY_SEEDS.items()}
    used_seeds['MOTHERBOARD'] = list(MOTHERBOARD_SEEDS_V22)
    seed_count = sum(len(v) for v in used_seeds.values())

    base.MAX_LINKS_PER_SEED = MAX_LINKS_PER_SEED_V22
    base.DISCOVERY_SEEDS = used_seeds
    base.inspect_dynamic = inspect_dynamic_v22
    try:
        await base.main()
    finally:
        base.inspect_dynamic = ORIGINAL_INSPECT_DYNAMIC
        base.DISCOVERY_SEEDS = ORIGINAL_DISCOVERY_SEEDS
        base.MAX_LINKS_PER_SEED = ORIGINAL_MAX_LINKS

    doc = json.loads(OUT.read_text(encoding='utf-8'))
    admitted = doc.get('dynamic_admitted_products') or []
    by_kind = {}
    for row in admitted:
        kind = str(row.get('kind') or '')
        by_kind[kind] = by_kind.get(kind, 0) + 1

    doc['deal_discovery_v22'] = {
        'active': True,
        'max_product_links_per_seed': MAX_LINKS_PER_SEED_V22,
        'seed_count': seed_count,
        'motherboard_seeds': MOTHERBOARD_SEEDS_V22,
        'motherboard_spec_evidence': 'VISIBLE_PRODUCT_TEXT_PLUS_LABEL_BOUND_DOM_SPECS',
        'dynamic_duplicate_policy': 'SAME_PRISJAGT_PRODUCT_URL_NEVER_COUNTS_TWICE',
        'policy': 'Actively inspect a deeper live retail universe before store-level offer comparison. Compatibility evidence remains fail-closed; a cheap product cannot win without the category hard gates.',
    }
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding='utf-8')

    print(json.dumps({
        'V22_RETAIL_DISCOVERY': True,
        'dynamic_inspected': (doc.get('counts') or {}).get('dynamic_inspected'),
        'dynamic_admitted': (doc.get('counts') or {}).get('dynamic_admitted'),
        'dynamic_admitted_by_kind': by_kind,
        'max_links_per_seed': MAX_LINKS_PER_SEED_V22,
        'motherboard_spec_evidence': 'VISIBLE_PRODUCT_TEXT_PLUS_LABEL_BOUND_DOM_SPECS',
    }, ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(main())
