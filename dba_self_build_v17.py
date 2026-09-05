from __future__ import annotations

import json
from pathlib import Path

import dba_platform_first_v16 as v16

OUT = Path('results/wow_strategy_latest.json')

SELF_BUILD_ROUTES = {'PLATFORM_FIRST_AM5', 'HYBRID_USED_NEW', 'USED_BUILD'}

# Video-inspired durable-part defaults, verified 2026-09-05.
# Principle: spend on parts that should survive several CPU/GPU upgrades, but do not
# pay enthusiast premiums for features the target workload does not need.
DURABLE_DEFAULTS = {
    'PSU': {
        'kind': 'PSU',
        'source': 'NEW RETAIL',
        'name': 'MSI MAG A850GL PCIE5 II 850W ATX 3.1',
        'price': 629,
        'url': 'https://www.proshop.dk/Stroemforsyning/MSI-MAG-A850GL-PCIE5-II-Stroemforsyning-850-Watt-120-mm-ATX-31-80-Plus-Gold-certified/3370565',
        'verified_at': '2026-09-05T15:00:00+02:00',
        'watt': 850,
        'length_mm': 140,
        'fit': 'PROVEN',
        'why': 'Buy-once PSU: 850W, ATX 3.1, modular and 140 mm; strong future GPU headroom without sacrificing Z20 packaging.',
    },
    'STORAGE': {
        'kind': 'STORAGE',
        'source': 'NEW RETAIL',
        'name': 'PNY CS1030 M.2 NVMe 500GB',
        'price': 703,
        'url': 'https://www.proshop.dk/SSD/PNY-CS1030-M2-NVMe-500GB/3115954',
        'verified_at': '2026-09-05T15:00:00+02:00',
        'capacity_gb': 500,
        'fit': 'PROVEN',
        'why': 'Value storage baseline: enough room for Windows + WoW without paying a large FPS-neutral premium for capacity.',
    },
}

PART_POLICY = {
    'MOTHERBOARD': {
        'role': 'PERMANENT FOUNDATION',
        'priority': 100,
        'best': 'B650/B850 mATX, AM5, Wi-Fi, 4 DIMM, at least 2 M.2; buy the cheapest board that genuinely meets the feature set.',
        'spend_rule': 'Pay for socket life, connectivity and slots — not flagship VRMs/branding. X870/X870E only if a concrete required feature justifies it.',
        'used_rule': 'Used only when identity/specs are explicit and price is materially below an equivalent new board.',
    },
    'PSU': {
        'role': 'PERMANENT FOUNDATION',
        'priority': 95,
        'best': 'Quality 750–850W ATX 3.1, modular, native modern GPU power, compact enough for Z20.',
        'spend_rule': 'A modest premium for real headroom is valuable because replacing the PSU later is wasted spend and rebuild work.',
        'used_rule': 'New-first. Reliability, warranty and known cable set matter more than a small used saving.',
    },
    'CASE': {
        'role': 'PERMANENT FOUNDATION',
        'priority': 90,
        'best': 'Jonsbo Z20 as the intended final enclosure.',
        'spend_rule': 'Buy once. A used exact Z20 is attractive if materially cheaper; do not buy a random temporary case unless total economics clearly win.',
        'used_rule': 'Used is fine if complete and undamaged; exact model/fit must be known.',
    },
    'COOLER': {
        'role': 'LONG-LIVED FOUNDATION',
        'priority': 80,
        'best': 'Strong AM5-compatible air cooler that fits <=163 mm; Arctic Freezer 36 class is the value reference.',
        'spend_rule': 'Cooling headroom is useful, but expensive AIOs add little to this WoW-focused build unless noise/aesthetics justify them.',
        'used_rule': 'Used is attractive only with confirmed AM5 mounting hardware and healthy fans.',
    },
    'RAM': {
        'role': 'SEMI-DURABLE',
        'priority': 70,
        'best': '32 GB DDR5 is the long-term target; 16 GB is allowed as a cheap bridge when the saving is substantial.',
        'spend_rule': 'Capacity/compatibility first. Do not pay a huge premium for marginal timings that do not materially improve the target experience.',
        'used_rule': 'Used-first if memory-testable and clearly desktop DDR5.',
    },
    'CPU': {
        'role': 'REPLACEABLE PERFORMANCE',
        'priority': 65,
        'best': 'AM5 value CPU now (7500F/7600/7700 when priced well); X3D is the later WoW raid/crowded-combat upgrade target.',
        'spend_rule': 'Do not overbuy CPU merely to future-proof; preserve the AM5 socket and upgrade when an X3D deal offers a real gain.',
        'used_rule': 'Used-first when genuine CPU identity and function are verified.',
    },
    'GPU': {
        'role': 'REPLACEABLE PERFORMANCE',
        'priority': 60,
        'best': 'Used sweet-spot GPU for 3840x1600/75 Hz; an ACCEPTABLE bridge GPU is valid when the price gap to SWEET SPOT is poor.',
        'spend_rule': 'Highest opportunity-cost part. Buy enough performance, then wait for exceptional used value rather than paying launch/new premiums.',
        'used_rule': 'Strong used-first preference; function/stability must be verified and defective cards are hard-excluded.',
    },
    'STORAGE': {
        'role': 'CONVENIENCE / EASY UPGRADE',
        'priority': 40,
        'best': '500 GB NVMe value baseline; 1 TB when the incremental price is sensible; 250 GB only as an emergency bridge.',
        'spend_rule': 'Storage speed/capacity above adequacy produces little WoW FPS. It is easy to add later.',
        'used_rule': 'New-first because modest saving rarely compensates for wear/SMART uncertainty.',
    },
}

VIDEO_REFERENCE = {
    'url': 'https://youtu.be/4v1hVfghtlw?is=tr7l8PXG1Aw_DG1V',
    'principles': [
        'Allocate budget according to the job each component must do, not prestige tier.',
        'Avoid enthusiast motherboard premiums when the required features are available on a sensible mainstream board.',
        'It can be cheaper to buy sufficient PSU headroom once than to replace an undersized PSU during a later GPU upgrade.',
        'Keep current performance balanced; do not force maximum-tier CPU/GPU into a value-focused build.',
    ],
}


def is_self_build(route: dict) -> bool:
    return route.get('route') in SELF_BUILD_ROUTES


def _replace_component(route: dict, kind: str, replacement: dict) -> None:
    comps = route.get('components') or []
    for i, comp in enumerate(comps):
        if comp.get('kind') == kind and comp.get('source') == 'NEW RETAIL':
            comps[i] = dict(replacement)
            break
    route['components'] = comps
    route['tcwp'] = sum(int(c.get('price') or 0) for c in comps)


def apply_durable_defaults(routes: list[dict]) -> None:
    for route in routes:
        if route.get('route') != 'PLATFORM_FIRST_AM5':
            continue
        _replace_component(route, 'PSU', DURABLE_DEFAULTS['PSU'])
        _replace_component(route, 'STORAGE', DURABLE_DEFAULTS['STORAGE'])
        route['durable_defaults_applied'] = True


def self_build_effective_cost(route: dict) -> int:
    tcwp = int(route.get('tcwp') or 10**9)
    perf_penalty = {'ACCEPTABLE': 800, 'SWEET SPOT': 0, 'OVERKILL': 250}.get(route.get('performance_class'), 1200)
    foundation_penalty = 0 if route.get('foundation') == 'AM5_B650_B850_MATX_WIFI_4DIMM' else 1800
    z20_penalty = {'VERIFIED': 0, 'LIKELY': 50, 'UNKNOWN': 500, 'NO': 5000}.get(route.get('z20_fit'), 800)
    upgrade_penalty = {'A': 0, 'B': 600, 'C': 1400, 'D': 2200}.get(route.get('upgradeability'), 1800)
    # Small reward for a strong current CPU, but not enough to make CPU overbuy dominate value.
    cpu_reward = max(0, min(350, (int(route.get('cpu_score') or 0) - 80) * 12))
    score = tcwp + perf_penalty + foundation_penalty + z20_penalty + upgrade_penalty - cpu_reward
    route['self_build_effective_cost'] = int(score)
    return int(score)


def finalize(data: dict) -> dict:
    routes = list(data.get('ranked') or [])
    apply_durable_defaults(routes)

    self_build = [r for r in routes if is_self_build(r)]
    for r in self_build:
        self_build_effective_cost(r)
    self_build.sort(key=lambda r: (int(r.get('self_build_effective_cost') or 10**9), int(r.get('tcwp') or 10**9)))

    foundation = [r for r in self_build if r.get('foundation') == 'AM5_B650_B850_MATX_WIFI_4DIMM']
    foundation_by_price = sorted(foundation, key=lambda r: int(r.get('tcwp') or 10**9))
    sweet = sorted([r for r in foundation if r.get('performance_class') == 'SWEET SPOT'], key=lambda r: int(r.get('tcwp') or 10**9))

    complete = sorted(
        [r for r in routes if r.get('route') == 'COMPLETE_USED_PC'],
        key=lambda r: (int(r.get('tcwp') or 10**9), -int(r.get('cpu_score') or 0), -int(r.get('gpu_score') or 0)),
    )
    secondary = [r for r in routes if r not in self_build and r.get('route') != 'COMPLETE_USED_PC']

    recommended = self_build[0] if self_build else None
    value_foundation = foundation_by_price[0] if foundation_by_price else recommended
    performance_step_up = sweet[0] if sweet else None

    # Ranking order now reflects the user's decision problem: self-builds first;
    # complete PCs remain fully retained as a market-reference section.
    data['ranked'] = self_build + secondary + complete
    data['self_build_ranked'] = self_build
    data['complete_pc_reference'] = complete
    data['recommended_self_build'] = recommended
    data['value_foundation_build'] = value_foundation
    data['performance_step_up_build'] = performance_step_up
    data['buy_now'] = recommended
    data['best_foundation'] = value_foundation
    data['best_complete_pc'] = complete[0] if complete else None
    data['wait_buy'] = 'BUILD_FOUNDATION_GPU_OPPORTUNISTIC' if recommended else 'WAIT_FOR_VALID_SELF_BUILD'
    data['model_version'] = 'DBA-WOW-SELF-BUILD-FIRST-V17'
    data['strategy_mode'] = 'SELF_BUILD_FIRST_UPGRADEABLE'
    data['primary_decision'] = 'BUILD_AN_UPGRADEABLE_PC; COMPLETE_PCS_ARE_SECONDARY_MARKET_REFERENCES'
    data['video_reference'] = VIDEO_REFERENCE
    data['part_policy'] = PART_POLICY
    data['durable_defaults'] = DURABLE_DEFAULTS
    data['self_build_performance_policy'] = {
        'target': 'SWEET SPOT when premium is reasonable',
        'acceptable_bridge_penalty_dkk': 800,
        'overkill_penalty_dkk': 250,
        'reason': '3840x1600/75 Hz should feel good now, but short-lived performance must not crowd out the permanent platform.',
    }
    return data


def main() -> None:
    v16.main()
    data = json.loads(OUT.read_text(encoding='utf-8'))
    data = finalize(data)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({
        'model': data['model_version'],
        'self_builds': len(data.get('self_build_ranked') or []),
        'complete_pc_reference': len(data.get('complete_pc_reference') or []),
        'recommended_route': (data.get('recommended_self_build') or {}).get('route'),
        'recommended_tcwp': (data.get('recommended_self_build') or {}).get('tcwp'),
        'value_foundation_tcwp': (data.get('value_foundation_build') or {}).get('tcwp'),
        'performance_step_up_tcwp': (data.get('performance_step_up_build') or {}).get('tcwp'),
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
