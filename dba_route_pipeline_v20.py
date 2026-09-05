from __future__ import annotations

import json
from pathlib import Path

# Importing this module patches dba_platform_first_v16.foundation_routes in-process.
# V17 calls v16.main() internally, so the patch must remain alive in the SAME Python
# process or V17 would silently rebuild the old cheapest-24 GPU universe.
import dba_platform_first_v20 as platform20
import dba_self_build_v17 as v17
import dba_build_alternatives as alternatives
import dba_self_build_v18 as v18

OUT = Path('results/wow_strategy_latest.json')


def annotate_pool() -> None:
    d=json.loads(OUT.read_text(encoding='utf-8'))
    counts={}
    for r in platform20.LAST_POOL:
        model=str(r.get('gpu') or 'UNKNOWN')
        counts[model]=counts.get(model,0)+1
    d['gpu_pool_v20']={
        'method':'STRATIFIED_CHEAPEST_PLUS_PERFORMANCE_PLUS_TARGET_FAMILIES',
        'pool_size':len(platform20.LAST_POOL),
        'target_families':list(platform20.TARGET_GPU_FAMILIES),
        'family_counts':counts,
        'rule':'A target GPU family cannot be dropped solely because it is not in the cheapest-N listings.',
        'integration':'V20 patch remained active inside V17 -> alternatives -> V18 route construction process.',
    }
    OUT.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8')


def main() -> None:
    # v17.main -> patched v16.main -> V17 finalize
    v17.main()
    # alternatives operates on the already-built V17 routes; it does not rerun V16.
    alternatives.main()
    # V18 is an internal used-vs-new route baseline only; V20 later replaces its
    # permanent retail choices with live multi-candidate decisions.
    v18.main()
    annotate_pool()
    d=json.loads(OUT.read_text(encoding='utf-8'))
    pool=d.get('gpu_pool_v20') or {}
    assert d.get('model_version')=='DBA-WOW-SELF-BUILD-FIRST-V18'
    assert int(pool.get('pool_size') or 0)>0
    print(json.dumps({'V20_ROUTE_PIPELINE':True,'baseline_model':d.get('model_version'),'self_builds':len(d.get('self_build_ranked') or []),'gpu_pool_size':pool.get('pool_size'),'gpu_family_counts':pool.get('family_counts')},ensure_ascii=False))


if __name__=='__main__':
    main()
