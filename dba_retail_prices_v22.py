from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import dba_retail_prices_v20 as base

OUT = Path('results/retail_prices_latest.json')
MAX_LINKS_PER_SEED_V22 = 20
MOTHERBOARD_SEEDS_V22 = [
    'https://prisjagt.dk/c/bundkort?615=44097',
    'https://prisjagt.dk/c/bundkort?615=39813',
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
    """Read exact label-bound hard-gate facts from the current product page."""
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
    return {
        'dimm_slots': dimm,
        'm2_count': m2,
        'lan_gbps': lan,
        'wifi_present': bool(wifi_match and wifi_match.group(1).lower() == 'ja'),
        'wifi_boolean_proven': bool(wifi_match),
    }


def _complete_spec_set(specs: dict) -> bool:
    return (
        specs.get('dimm_slots') is not None
        and specs.get('m2_count') is not None
        and specs.get('lan_gbps') is not None
        and specs.get('wifi_boolean_proven') is True
    )


async def reveal_spec_text_v22(page) -> tuple[str, dict]:
    """Expose Prisjagt's complete product specification block without guessing.

    Current product pages render a shortened Info block first and use the
    generic ``Se mere information`` control for the remaining properties.
    Clicking a control grants no evidence by itself; all required facts must
    subsequently be found as exact label/value pairs in the page DOM.
    """
    before = await page.locator('body').text_content(timeout=7000) or ''
    before_specs = extract_motherboard_specs_v22(before)
    if _complete_spec_set(before_specs):
        return before[:200000], {'revealed': False, 'method': 'COMPLETE_SPECS_ALREADY_IN_DOM'}

    expand_re = re.compile(
        r'^(?:Se mere information|Vis mere information|Se alle specifikationer|Vis alle specifikationer)$',
        re.I,
    )
    info_re = re.compile(r'^(?:Info|Specifikationer|Specifikation|Produktinformation|Detaljer)$', re.I)
    candidates = [
        ('expand_button', page.get_by_role('button', name=expand_re)),
        ('expand_text', page.get_by_text(expand_re, exact=True)),
        ('info_link', page.get_by_role('link', name=info_re)),
        ('info_button', page.get_by_role('button', name=info_re)),
        ('info_text', page.get_by_text(info_re, exact=True)),
    ]
    attempts: list[str] = []
    for kind, locator in candidates:
        try:
            count = min(await locator.count(), 5)
        except Exception as exc:
            attempts.append(f'{kind}:count:{type(exc).__name__}')
            continue
        for idx in range(count):
            item = locator.nth(idx)
            try:
                if not await item.is_visible():
                    continue
                label = _norm(await item.inner_text(timeout=1000))[:80]
                await item.click(timeout=4000)
                attempts.append(f'{kind}:{idx}:{label}:clicked')
                try:
                    await page.get_by_text(re.compile(r'Maks\.?\s*Ethernet[- ]?hastighed', re.I)).first.wait_for(
                        state='attached', timeout=4000
                    )
                except Exception:
                    pass
                current = await page.locator('body').text_content(timeout=7000) or ''
                specs = extract_motherboard_specs_v22(current)
                if _complete_spec_set(specs):
                    return current[:200000], {
                        'revealed': True,
                        'method': f'CLICK_{kind.upper()}',
                        'label': label,
                        'attempts': attempts,
                    }
            except Exception as exc:
                attempts.append(f'{kind}:{idx}:{type(exc).__name__}')

    after = await page.locator('body').text_content(timeout=7000) or ''
    return after[:200000], {
        'revealed': False,
        'method': 'COMPLETE_SPEC_SET_NOT_REVEALED',
        'attempts': attempts,
        'partial_specs': extract_motherboard_specs_v22(after),
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
            'source': 'CURRENT_PRODUCT_PAGE_LABEL_BOUND_EXPANDED_INFO',
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
            'evidence_model_v22': 'VISIBLE_PRODUCT_TEXT_PLUS_LABEL_BOUND_EXPANDED_INFO',
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
            spec_text, reveal = await reveal_spec_text_v22(page)
            availability = str(offer.get('availability') or 'AVAILABLE_COMPARISON')
            candidate, missing = infer_motherboard_v22(
                name, visible_body, spec_text, url, price, availability, now
            )
            result.update({
                'verified': True,
                'name': name,
                'price': price,
                'availability': availability,
                'missing_evidence': missing,
                'spec_probe_v22': extract_motherboard_specs_v22(spec_text),
                'spec_reveal_v22': reveal,
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
    assert _complete_spec_set(specs), specs
    candidate, missing = infer_motherboard_v22(
        'Asus Example B850M WiFi', visible, hidden,
        'https://prisjagt.dk/product.php?p=1', 1200, 'InStock',
        '2026-09-06T00:00:00+00:00',
    )
    assert candidate is not None, missing
    assert candidate['dimm_slots'] == 4 and candidate['m2_count'] == 3 and candidate['lan_gbps'] == 2.5

    no_wifi = hidden.replace('Trådløst netværk (Wi-Fi)Ja', 'Trådløst netværk (Wi-Fi)Nej')
    rejected, missing = infer_motherboard_v22(
        'Asus Example B850M', visible, no_wifi,
        'https://prisjagt.dk/product.php?p=2', 1000, 'InStock',
        '2026-09-06T00:00:00+00:00',
    )
    assert rejected is None and 'Wi-Fi unproven' in missing, missing

    weak = hidden.replace('Hukommelsespladser4 stk', 'Hukommelsespladser2 stk')
    rejected, missing = infer_motherboard_v22(
        'Asus Example B850M WiFi', visible, weak,
        'https://prisjagt.dk/product.php?p=3', 800, 'InStock',
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
        'motherboard_spec_evidence': 'CURRENT_PRODUCT_PAGE_LABEL_BOUND_EXPANDED_INFO',
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
        'motherboard_spec_evidence': 'CURRENT_PRODUCT_PAGE_LABEL_BOUND_EXPANDED_INFO',
    }, ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(main())
