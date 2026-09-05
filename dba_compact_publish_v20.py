from __future__ import annotations

import json
from pathlib import Path

SRC = Path('results/wow_strategy_latest.json')
SELF_BUILD_ROUTES = {'PLATFORM_FIRST_AM5', 'HYBRID_USED_NEW', 'USED_BUILD'}
MAX_PUBLISHED_SELF_BUILDS = 250
MAX_BYTES = 90 * 1024 * 1024


def identity(route: dict) -> tuple:
    return (
        route.get('route'), route.get('cpu'), route.get('gpu'),
        int(route.get('tcwp') or 0), int(route.get('v20_decision_cost') or 0),
    )


def main() -> None:
    data=json.loads(SRC.read_text(encoding='utf-8'))
    assert data.get('gate_passed') is True
    assert data.get('model_version')=='DBA-WOW-SELF-BUILD-FIRST-V20'
    assert (data.get('component_market_coverage_v20') or {}).get('passed') is True
    assert (data.get('retail_discovery_v20') or {}).get('model')=='V20_DYNAMIC_RETAIL_SAME_PRODUCT_GATE'

    full=list(data.get('self_build_ranked') or [])
    assert full
    rec_before=data.get('recommended_self_build') or {}
    rec_key=identity(rec_before)
    assert str(rec_before.get('performance_class_v20') or '').startswith('SWEET SPOT')

    # Preserve the recommendation even if it is not first in raw value-sorted routes,
    # then publish a bounded selection of the full post-gate universe.
    published=[]; seen=set()
    for r in [rec_before] + full:
        key=identity(r)
        if key in seen: continue
        seen.add(key); published.append(r)
        if len(published)>=MAX_PUBLISHED_SELF_BUILDS: break

    ranked_other=[r for r in (data.get('ranked') or []) if r.get('route') not in SELF_BUILD_ROUTES]
    data['self_build_evaluated_count']=len(full)
    data['self_build_ranked']=published
    data['ranked']=published+ranked_other
    data['publication_compaction']={
        'mode':'RECOMMENDATION_PLUS_TOP_SELF_BUILDS_AFTER_FULL_V20_GATE',
        'evaluated_self_builds':len(full),
        'published_self_builds':len(published),
        'max_published_self_builds':MAX_PUBLISHED_SELF_BUILDS,
        'decision_scope':'FULL_UNIVERSE_BEFORE_COMPACTION',
    }
    assert identity(data.get('recommended_self_build') or {})==rec_key
    assert published and identity(published[0])==rec_key

    SRC.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    size=SRC.stat().st_size
    assert size<MAX_BYTES,f'Published V20 snapshot still too large: {size/1024/1024:.2f} MiB'
    print(json.dumps({'compacted':True,'evaluated_self_builds':len(full),'published_self_builds':len(published),'size_mib':round(size/1024/1024,2),'recommended_tcwp':rec_before.get('tcwp'),'recommended_gpu':rec_before.get('gpu')},ensure_ascii=False))


if __name__=='__main__':
    main()
