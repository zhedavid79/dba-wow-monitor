from __future__ import annotations

import json
from pathlib import Path

import dba_platform_first_v16 as v16

OUT = Path('results/wow_strategy_latest.json')
_original_foundation_routes = v16.foundation_routes
LAST_POOL: list[dict] = []

TARGET_GPU_FAMILIES = (
    'RX 6800 XT','RX 6800','RX 6750 XT','RX 6700 XT',
    'RTX 3080','RTX 3070 Ti','RTX 3070','RTX 3060 Ti',
    'RTX 2080 Super','RTX 2070 Super','RX 5700 XT',
)


def _lid(r: dict) -> str:
    return str(r.get('listing_id') or r.get('url') or r.get('title') or '')


def stratified_gpu_pool(parts: list[dict]) -> list[dict]:
    eligible = [r for r in parts if v16.genuine_gpu(r) and v16.used_ok(r) and int(r.get('gpu_score') or 0) >= 45]
    selected: list[dict] = []
    seen: set[str] = set()

    def add(rows):
        for r in rows:
            key = _lid(r)
            if not key or key in seen:
                continue
            seen.add(key)
            selected.append(r)

    # Preserve cheap bridge/value cards.
    add(sorted(eligible, key=lambda r:(int(r.get('ask_t1') or 10**9), -int(r.get('gpu_score') or 0)))[:12])

    # Preserve top performance even when not among the cheapest cards.
    add(sorted(eligible, key=lambda r:(-int(r.get('gpu_score') or 0), int(r.get('ask_t1') or 10**9)))[:10])

    # Explicit target-family strata: up to two cheapest live examples per family.
    for family in TARGET_GPU_FAMILIES:
        rows = [r for r in eligible if str(r.get('gpu') or '') == family]
        add(sorted(rows, key=lambda r:int(r.get('ask_t1') or 10**9))[:2])

    # Keep a broad but bounded pool. The downstream route optimizer evaluates all of it.
    return selected[:40]


def foundation_routes_v20(parts: list[dict]):
    global LAST_POOL
    pool = stratified_gpu_pool(parts)
    LAST_POOL = pool
    non_gpu = [r for r in parts if r.get('kind') != 'GPU']
    return _original_foundation_routes(non_gpu + pool)


v16.foundation_routes = foundation_routes_v20


def main() -> None:
    v16.main()
    d = json.loads(OUT.read_text(encoding='utf-8'))
    by_family: dict[str,int] = {}
    for r in LAST_POOL:
        m = str(r.get('gpu') or 'UNKNOWN')
        by_family[m] = by_family.get(m,0) + 1
    d['gpu_pool_v20'] = {
        'method':'STRATIFIED_CHEAPEST_PLUS_PERFORMANCE_PLUS_TARGET_FAMILIES',
        'pool_size':len(LAST_POOL),
        'target_families':list(TARGET_GPU_FAMILIES),
        'family_counts':by_family,
        'rule':'A target GPU family cannot be dropped solely because it is not in the cheapest-N listings.',
    }
    OUT.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'v20_gpu_pool':len(LAST_POOL),'families':by_family},ensure_ascii=False))


if __name__ == '__main__':
    main()
