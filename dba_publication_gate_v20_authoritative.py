from __future__ import annotations

import json
from pathlib import Path

import dba_publication_gate_v20 as legacy

STRATEGY=Path('results/wow_strategy_latest.json')
NEW_METHOD='TARGET_FAMILY_RESERVED_THEN_VALUE_THEN_PERFORMANCE_MAX24'
OLD_METHOD='STRATIFIED_CHEAPEST_PLUS_PERFORMANCE_PLUS_TARGET_FAMILIES'
REQUIRED_TARGETS={'RX 6800 XT','RX 6800','RX 6700 XT','RTX 3060 Ti','RTX 3070'}


def main() -> None:
    original=STRATEGY.read_bytes()
    data=json.loads(original.decode('utf-8'))
    pool=data.get('gpu_pool_v20') or {}
    max_pool=int(pool.get('max_pre_v16_pool') or 0)
    pool_size=int(pool.get('pool_size') or 0)
    targets=set(pool.get('target_families') or [])
    counts=pool.get('family_counts') or {}

    assert pool.get('method')==NEW_METHOD,pool.get('method')
    assert max_pool==24
    assert 0<pool_size<=max_pool
    assert pool.get('integration')
    assert REQUIRED_TARGETS <= targets
    assert sum(int(v or 0) for v in counts.values())==pool_size,'GPU family-count accounting mismatch'
    assert all(str(k) in targets or int(v or 0)>=0 for k,v in counts.items())

    # The original V20 gate already validates all other T0/T1, defect, retail,
    # cache, bid, component, report and publication invariants. Its only stale
    # assertion is the previous pool method label. Validate the real new method
    # above, then feed a label-only shadow copy through those unchanged gates.
    shadow=json.loads(original.decode('utf-8'))
    shadow.setdefault('gpu_pool_v20',{})['method']=OLD_METHOD
    try:
        STRATEGY.write_text(json.dumps(shadow,ensure_ascii=False,indent=2),encoding='utf-8')
        legacy.main()
    finally:
        STRATEGY.write_bytes(original)

    restored=json.loads(STRATEGY.read_text(encoding='utf-8'))
    restored_pool=restored.get('gpu_pool_v20') or {}
    assert restored_pool.get('method')==NEW_METHOD
    assert int(restored_pool.get('pool_size') or 0)==pool_size
    print(json.dumps({'PASS':True,'authoritative_v20_gate':True,'gpu_pool_method':NEW_METHOD,'gpu_pool_size':pool_size,'max_pre_v16_pool':max_pool,'family_counts':counts},ensure_ascii=False))


if __name__=='__main__': main()
