from __future__ import annotations

import json
import re
from pathlib import Path

import dba_self_build_v17 as v17
import dba_strategy_report_v17 as strategy_report

STRATEGY = Path('results/wow_strategy_latest.json')
PARTS = Path('results/z20_parts_latest.json')

# Storage is convenience, not the place to burn budget. For a "good PC" the normal
# baseline is now 500 GB; 1 TB remains a comfort alternative rather than a requirement.
RETAIL_ALTS = {
    'STORAGE': [
        {
            'name': 'PNY CS1030 M.2 NVMe 500GB', 'price': 703,
            'url': 'https://www.proshop.dk/SSD/PNY-CS1030-M2-NVMe-500GB/3115954',
            'source': 'NEW RETAIL', 'capacity_gb': 500, 'tier': 'VALUE',
            'pros': 'Recommended baseline: enough for Windows + WoW while preserving budget for platform/GPU.',
            'cons': 'Less spare capacity than 1 TB; another SSD may be useful later.',
        },
        {
            'name': 'Kingston NV3 1TB M.2 NVMe', 'price': 1212,
            'url': 'https://www.proshop.dk/SSD/Kingston-NV3-SSD-1TB-PCIe-40-M2-2280/3284682',
            'source': 'NEW RETAIL', 'capacity_gb': 1000, 'tier': 'COMFORT',
            'pros': 'Comfortable capacity and no near-term storage upgrade.',
            'cons': 'Large premium with essentially no WoW FPS benefit.',
        },
    ],
    'PSU': [
        {
            'name': 'MSI MAG A850GL PCIE5 II 850W ATX 3.1', 'price': 629,
            'url': 'https://www.proshop.dk/Stroemforsyning/MSI-MAG-A850GL-PCIE5-II-Stroemforsyning-850-Watt-120-mm-ATX-31-80-Plus-Gold-certified/3370565',
            'source': 'NEW RETAIL', 'tier': 'RECOMMENDED',
            'pros': '850W headroom, ATX 3.1, fully modular, 140 mm length; excellent Z20/future-GPU value at current price.',
            'cons': 'Promotion-dependent price; must be re-verified when retail baseline expires.',
        },
        {
            'name': 'Corsair RM750e (2025) 750W ATX 3.1', 'price': 799,
            'url': 'https://www.proshop.dk/Stroemforsyning/Corsair-RMe-Series-RM750e-2025-Stroemforsyning-750-Watt-120-mm-ATX-31-80-Plus-Gold-certified/3324407',
            'source': 'NEW RETAIL', 'tier': 'ALTERNATIVE',
            'pros': 'Compact 140 mm, ATX 3.1, modular, native modern GPU connector and strong warranty/brand support.',
            'cons': 'Currently costs more while offering less wattage than the MSI 850W deal.',
        },
    ],
}

KNOWN_ACCESSORY_FALSE_POSITIVES = {'11596289'}
CPU_ACCESSORY = re.compile(
    r'\b(?:k(?:ø|oe)ler|cooler|heatsink|vandblok|waterblock|aio|radiator|'
    r'mount(?:ing)?\s*(?:kit|bracket)|beslag|backplate|tom\s*(?:kasse|emballage)|empty\s*box)\b',
    re.I,
)


def cap(title):
    t = title or ''
    m = re.search(r'\b(2|4)\s*x\s*(8|16|32)\s*gb\b', t, re.I)
    if m:
        return int(m.group(1)) * int(m.group(2))
    vals = [int(x) for x in re.findall(r'\b(8|16|32|64)\s*gb\b', t, re.I)]
    return max(vals) if vals else 0


def live_ram_alternatives(parts):
    out = []
    for r in parts:
        if r.get('kind') != 'RAM' or r.get('ram_compatibility') != 'DESKTOP_COMPATIBLE':
            continue
        title = str(r.get('title') or '')
        if 'ddr5' not in title.lower():
            continue
        capacity = cap(title)
        if capacity < 16:
            continue
        price = int(r.get('ask_t1') or 0)
        if price <= 0 or not r.get('url'):
            continue
        out.append({
            'name': title, 'price': price, 'url': r['url'], 'source': 'USED ASK',
            'listing_id': str(r.get('listing_id') or ''), 'capacity_gb': capacity,
            'tier': 'BRIDGE' if capacity < 32 else 'VALUE',
            'pros': 'Lowest-cost bridge; preserves upgrade budget.' if capacity < 32 else '32 GB is the preferred long-term capacity.',
            'cons': '16 GB is adequate, but 32 GB may be desirable later.' if capacity < 32 else 'Used RAM must be memory-tested; speed/timings may not be optimal.',
        })
    return sorted(out, key=lambda x: (x['price'], -x['capacity_gb']))[:10]


def component_alts(route, ram_alts):
    result = {}
    for kind in ('CPU', 'GPU', 'MOTHERBOARD', 'RAM', 'PSU', 'STORAGE', 'CASE', 'COOLER'):
        cur = next((c for c in route.get('components', []) if c.get('kind') == kind), None)
        opts = []
        if cur:
            opts.append({
                'name': cur.get('name', kind), 'price': int(cur.get('price') or 0),
                'url': cur.get('url'), 'source': cur.get('source'), 'tier': 'CURRENT',
                'pros': 'Current selected component in this complete working build.',
                'cons': 'Compare against the alternatives before buying.',
            })
        if kind == 'STORAGE':
            opts.extend(RETAIL_ALTS['STORAGE'])
        if kind == 'PSU':
            opts.extend(RETAIL_ALTS['PSU'])
        if kind == 'RAM':
            opts.extend(ram_alts)
        result[kind] = opts
    return result


def enrich_cross_route_alts(routes):
    pools = {k: [] for k in ('CPU', 'GPU', 'MOTHERBOARD', 'PSU', 'CASE', 'COOLER')}
    for r in routes:
        if not v17.is_self_build(r):
            continue
        for c in r.get('components') or []:
            k = c.get('kind')
            if k not in pools:
                continue
            key = (c.get('name'), int(c.get('price') or 0), c.get('url'))
            if not any((x['name'], x['price'], x['url']) == key for x in pools[k]):
                pools[k].append({
                    'name': c.get('name', k), 'price': int(c.get('price') or 0),
                    'url': c.get('url'), 'source': c.get('source'), 'tier': 'ALTERNATIVE',
                    'pros': 'Alternative already used in another complete verified self-build route.',
                    'cons': 'Compatibility/value must be checked against the exact selected build.',
                })
    for k in pools:
        pools[k] = sorted(pools[k], key=lambda x: x['price'])[:8]
    for r in routes:
        if not v17.is_self_build(r):
            continue
        for k, opts in pools.items():
            r.setdefault('component_alternatives', {}).setdefault(k, []).extend(opts)


def main():
    d = json.loads(STRATEGY.read_text(encoding='utf-8'))
    p = json.loads(PARTS.read_text(encoding='utf-8'))

    routes = []
    for r in d.get('ranked') or []:
        bad = False
        for c in r.get('components') or []:
            if c.get('kind') == 'CPU' and (
                str(c.get('listing_id')) in KNOWN_ACCESSORY_FALSE_POSITIVES
                or CPU_ACCESSORY.search(str(c.get('name') or ''))
            ):
                bad = True
        if not bad:
            routes.append(r)

    ram_alts = live_ram_alternatives(p.get('opportunities') or [])
    for r in routes:
        if r.get('route') != 'PLATFORM_FIRST_AM5':
            continue
        comps = r.get('components') or []
        storage = next((c for c in comps if c.get('kind') == 'STORAGE'), None)
        if storage:
            value = RETAIL_ALTS['STORAGE'][0]
            storage.update({
                'name': value['name'], 'price': value['price'], 'url': value['url'],
                'source': 'NEW RETAIL', 'capacity_gb': value['capacity_gb'], 'storage_tier': 'VALUE',
            })
            r['tcwp'] = sum(int(c.get('price') or 0) for c in comps)
        r['component_alternatives'] = component_alts(r, ram_alts)

    enrich_cross_route_alts(routes)
    d['ranked'] = routes
    d['storage_policy'] = 'VALUE_FIRST_500_BASE_1000_COMFORT'
    d['component_alternatives_policy'] = 'PART_BY_PART_BEST_CHOICE_WITH_LIVE_ALTERNATIVES'
    d = v17.finalize(d)
    STRATEGY.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding='utf-8')

    # Generate report only after all filters, durable defaults and alternatives are final.
    strategy_report.main()
    report = Path('results/wow_self_build_report.md').read_text(encoding='utf-8')
    assert '/item/11596289' not in report, 'Accessory false-positive leaked into published report'
    assert '## Del-for-del købsplan' in report
    assert '## Færdige computere — markedsreference' in report
    print(json.dumps({
        'ok': True,
        'model': d.get('model_version'),
        'self_builds': len(d.get('self_build_ranked') or []),
        'complete_pc_reference': len(d.get('complete_pc_reference') or []),
        'ram_alternatives': len(ram_alts),
        'storage_default_gb': 500,
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
