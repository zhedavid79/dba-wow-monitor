from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path

import dba_self_build_v17 as v17

OUT = Path('results/wow_strategy_latest.json')

BAD_DESKTOP_RAM = re.compile(
    r"\b(?:so[- ]?dimm|sodimm|rdimm|lrdimm|registered|server\s*ram|kingston\s+fury\s+impact|kf548s38ibk2(?:-\d+)?)\b",
    re.I,
)

# Fresh Danish retail references verified 2026-09-05. These are comparison anchors,
# not claims that every used part has an exact new-market twin (notably older GPUs).
NEW_REFERENCES = {
    'MOTHERBOARD': {
        'name': 'GIGABYTE B650M GAMING PLUS WIFI', 'price': 1170,
        'url': 'https://www.proshop.dk/Bundkort/GIGABYTE-B650M-GAMING-PLUS-WIFI-Bundkort-AMD-B650-AMD-AM5-DDR5-RAM-Micro-ATX/3335794',
        'comparison': 'EXACT_FOUNDATION_REFERENCE',
    },
    'PSU': {
        'name': 'MSI MAG A850GL PCIE5 II 850W ATX 3.1', 'price': 629,
        'url': 'https://www.proshop.dk/Stroemforsyning/MSI-MAG-A850GL-PCIE5-II-Stroemforsyning-850-Watt-120-mm-ATX-31-80-Plus-Gold-certified/3370565',
        'comparison': 'EXACT_FOUNDATION_REFERENCE', 'watt': 850, 'length_mm': 140,
    },
    'CASE': {
        'name': 'Jonsbo Z20 Mesh White', 'price': 750,
        'url': 'https://www.proshop.dk/Kabinet/Jonsbo-Z20-Mesh-Kabinet-Minitower-Hvid/3407428',
        'comparison': 'EXACT_FINAL_CASE_REFERENCE',
    },
    'COOLER': {
        'name': 'Arctic Freezer 36 Black', 'price': 175,
        'url': 'https://www.proshop.dk/CPU-Koeler/Arctic-Freezer-36-Black-CPU-Luftkoeler/3238363',
        'comparison': 'VALUE_CLASS_REFERENCE',
    },
    'RAM': {
        'name': 'Corsair Vengeance RGB DDR5-6000 32GB (2x16GB) EXPO CL38', 'price': 3699,
        'url': 'https://prisjagt.dk/c/ram-hukommelse?r_95336=32-32',
        'comparison': 'NEW_32GB_DESKTOP_DDR5_6000_EXPO_REFERENCE', 'capacity_gb': 32,
    },
    'GPU': {
        'name': 'XFX Radeon RX 7600 Speedster SWFT 210 8GB', 'price': 2495,
        'url': 'https://www.proshop.dk/Grafikkort/XFX-Radeon-RX-7600-Speedster-SWFT-210-Core-8GB-GDDR6-RAM-Grafikkort/3171558',
        'comparison': 'CURRENT_NEW_TARGET_CLASS_REFERENCE',
    },
    'STORAGE': {
        'name': 'PNY CS1030 M.2 NVMe 500GB', 'price': 703,
        'url': 'https://www.proshop.dk/SSD/PNY-CS1030-M2-NVMe-500GB/3115954',
        'comparison': 'EXACT_VALUE_STORAGE_REFERENCE', 'capacity_gb': 500,
    },
}

CPU_NEW = {
    'Ryzen 5 7500F': {
        'name': 'AMD Ryzen 5 7500F Tray', 'price': 949,
        'url': 'https://pc-lager.dk/da/p/komponenter/processorer/amdprocessorer/amd-cpu-ryzen-5-7500f-3-7ghz-6-kerner-am5-tray-u-koler-1001513790',
        'comparison': 'EXACT_CPU_MODEL_REFERENCE',
    },
    'Ryzen 5 7600': {
        'name': 'AMD Ryzen 5 7600', 'price': 1352,
        'url': 'https://pricetracker.dk/p/0730143314572/amd-ryzen-5-7600-38ghz51ghz-6-kerner-12-traade-32-mb-cache-socket-am5',
        'comparison': 'EXACT_CPU_MODEL_REFERENCE',
    },
    'Ryzen 5 7600X': {
        'name': 'AMD Ryzen 5 7600X', 'price': 1183,
        'url': 'https://prisjagt.dk/product.php?p=6999754',
        'comparison': 'EXACT_CPU_MODEL_REFERENCE',
    },
}

THRESHOLDS = {
    'CPU': 0.85, 'GPU': 0.80, 'RAM': 0.75, 'COOLER': 0.60,
    'MOTHERBOARD': 0.70, 'CASE': 0.70, 'PSU': 0.60, 'STORAGE': 0.60,
}


def money(n: int | None) -> int | None:
    return int(n) if n is not None else None


def ram_capacity(name: str) -> int:
    m = re.search(r'\b(2|4)\s*x\s*(8|16|32)\s*gb\b', name or '', re.I)
    if m:
        return int(m.group(1)) * int(m.group(2))
    vals = [int(x) for x in re.findall(r'\b(8|16|32|64)\s*gb\b', name or '', re.I)]
    return max(vals) if vals else 0


def new_reference(route: dict, kind: str) -> dict | None:
    if kind == 'CPU':
        return deepcopy(CPU_NEW.get(str(route.get('cpu') or '')))
    ref = NEW_REFERENCES.get(kind)
    return deepcopy(ref) if ref else None


def used_candidates(route: dict, kind: str) -> list[dict]:
    out = []
    current = next((c for c in route.get('components', []) if c.get('kind') == kind), None)
    if current and current.get('source') == 'USED ASK':
        out.append(current)
    for a in ((route.get('component_alternatives') or {}).get(kind) or []):
        if a.get('source') == 'USED ASK':
            out.append(a)
    dedup, seen = [], set()
    for a in out:
        name = str(a.get('name') or '')
        if kind == 'RAM' and BAD_DESKTOP_RAM.search(name):
            continue
        price = int(a.get('price') or 0)
        if price <= 0:
            continue
        key = (name, price, a.get('url'))
        if key in seen:
            continue
        seen.add(key)
        b = dict(a)
        if kind == 'RAM':
            b['capacity_gb'] = int(b.get('capacity_gb') or ram_capacity(name))
        dedup.append(b)
    return sorted(dedup, key=lambda x: int(x.get('price') or 10**9))


def route_has_desktop_ram(route: dict) -> bool:
    ram = next((c for c in route.get('components', []) if c.get('kind') == 'RAM'), None)
    if not ram:
        return False
    return not BAD_DESKTOP_RAM.search(str(ram.get('name') or ''))


def apply_current_new_ram(route: dict) -> None:
    comps = route.get('components') or []
    for i, c in enumerate(comps):
        if c.get('kind') == 'RAM' and c.get('source') == 'NEW RETAIL':
            ref = deepcopy(NEW_REFERENCES['RAM'])
            ref.update({'kind': 'RAM', 'source': 'NEW RETAIL', 'verified_at': '2026-09-05T18:00:00+02:00'})
            comps[i] = ref
            break
    route['components'] = comps
    route['tcwp'] = sum(int(c.get('price') or 0) for c in comps)


def component_decision(route: dict, kind: str) -> dict:
    current = next((c for c in route.get('components', []) if c.get('kind') == kind), None)
    new = new_reference(route, kind)
    used = used_candidates(route, kind)
    equivalent_used = used
    if kind == 'RAM':
        equivalent_used = [u for u in used if int(u.get('capacity_gb') or 0) >= 32]
    if kind == 'CPU':
        target = str(route.get('cpu') or '').lower()
        exact = [u for u in used if target and target in str(u.get('name') or '').lower()]
        equivalent_used = exact or ([current] if current and current.get('source') == 'USED ASK' else [])
    if kind == 'GPU':
        equivalent_used = [current] if current and current.get('source') == 'USED ASK' else []

    best_used = equivalent_used[0] if equivalent_used else None
    new_price = int(new.get('price') or 0) if new else 0
    used_price = int(best_used.get('price') or 0) if best_used else 0
    threshold = THRESHOLDS[kind]

    decision = 'WAIT'
    reason = 'No sufficiently strong verified buy signal.'
    if new and best_used and used_price <= int(new_price * threshold):
        decision = 'BUY_USED'
        reason = f"Verified used price is at least {round((1-threshold)*100)}% below the new reference."
    elif kind == 'RAM' and new:
        bridge = next((u for u in used if 16 <= int(u.get('capacity_gb') or 0) < 32 and int(u.get('price') or 0) <= int(new_price * 0.40)), None)
        if bridge:
            best_used = bridge
            used_price = int(bridge['price'])
            decision = 'BUY_USED_BRIDGE'
            reason = '32GB new pricing is unusually expensive; a cheap verified 16GB desktop bridge preserves upgrade budget.'
        else:
            decision = 'BUY_NEW_OR_WAIT'
            reason = 'No verified desktop used RAM clears the required discount versus the new 32GB reference.'
    elif new and kind in {'PSU', 'STORAGE'}:
        decision = 'BUY_NEW'
        reason = 'New-first category; used must be exceptionally cheap to justify wear/warranty uncertainty.'
    elif new and current and current.get('source') == 'NEW RETAIL':
        decision = 'BUY_NEW'
        reason = 'Selected new foundation part is the current retail reference or already competitive with it.'
    elif new:
        decision = 'BUY_NEW_OR_WAIT'
        reason = 'Used saving is too small versus the current new reference.'

    saving = (new_price - used_price) if new_price and used_price else None
    saving_pct = round((saving / new_price) * 100, 1) if saving is not None and new_price else None
    return {
        'kind': kind,
        'selected': current,
        'best_used': best_used,
        'new_reference': new,
        'used_price': used_price or None,
        'new_price': new_price or None,
        'saving_dkk': saving,
        'saving_pct': saving_pct,
        'decision': decision,
        'reason': reason,
        'threshold_pct': round((1-threshold)*100),
    }


def finalize(data: dict) -> dict:
    self_build = []
    for original in data.get('self_build_ranked') or []:
        route = deepcopy(original)
        if not route_has_desktop_ram(route):
            continue
        apply_current_new_ram(route)
        v17.self_build_effective_cost(route)
        self_build.append(route)

    self_build.sort(key=lambda r: (int(r.get('self_build_effective_cost') or 10**9), int(r.get('tcwp') or 10**9)))
    foundation = [r for r in self_build if r.get('foundation') == 'AM5_B650_B850_MATX_WIFI_4DIMM']
    sweet = [r for r in foundation if r.get('performance_class') == 'SWEET SPOT']
    foundation_price = sorted(foundation, key=lambda r: int(r.get('tcwp') or 10**9))
    sweet_price = sorted(sweet, key=lambda r: int(r.get('tcwp') or 10**9))

    recommended = self_build[0] if self_build else None
    if recommended:
        recommended['component_market_decisions'] = {
            kind: component_decision(recommended, kind)
            for kind in ('MOTHERBOARD','PSU','CASE','COOLER','RAM','CPU','GPU','STORAGE')
        }

    complete = list(data.get('complete_pc_reference') or [])
    secondary = [r for r in data.get('ranked') or [] if r.get('route') not in v17.SELF_BUILD_ROUTES and r.get('route') != 'COMPLETE_USED_PC']
    data['ranked'] = self_build + secondary + complete
    data['self_build_ranked'] = self_build
    data['recommended_self_build'] = recommended
    data['value_foundation_build'] = foundation_price[0] if foundation_price else recommended
    data['performance_step_up_build'] = sweet_price[0] if sweet_price else None
    data['buy_now'] = recommended
    data['new_price_references'] = {'common': NEW_REFERENCES, 'cpu': CPU_NEW}
    data['market_decision_policy'] = {
        'mode': 'USED_VS_NEW_WITH_BUY_WAIT',
        'thresholds': THRESHOLDS,
        'ram_form_factor': 'DESKTOP_DIMM_ONLY; SO_DIMM_RDIMM_LRDIMM_HARD_EXCLUDE',
        'rule': 'Used must beat a current new reference by a category-specific margin; otherwise buy new or wait.',
    }
    data['model_version'] = 'DBA-WOW-SELF-BUILD-FIRST-V18'
    data['strategy_mode'] = 'SELF_BUILD_FIRST_USED_VS_NEW'
    return data


def main() -> None:
    data = json.loads(OUT.read_text(encoding='utf-8'))
    data = finalize(data)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    rec = data.get('recommended_self_build') or {}
    print(json.dumps({
        'model': data.get('model_version'),
        'self_builds': len(data.get('self_build_ranked') or []),
        'recommended_tcwp': rec.get('tcwp'),
        'recommended_cpu': rec.get('cpu'),
        'recommended_gpu': rec.get('gpu'),
        'ram_decision': ((rec.get('component_market_decisions') or {}).get('RAM') or {}).get('decision'),
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
