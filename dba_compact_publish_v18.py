from __future__ import annotations

import json
from pathlib import Path

SRC = Path('results/wow_strategy_latest.json')
SELF_BUILD_ROUTES = {'PLATFORM_FIRST_AM5', 'HYBRID_USED_NEW', 'USED_BUILD'}
MAX_PUBLISHED_SELF_BUILDS = 250
MAX_BYTES = 90 * 1024 * 1024


def main() -> None:
    data = json.loads(SRC.read_text(encoding='utf-8'))
    assert data.get('gate_passed') is True
    assert data.get('model_version') == 'DBA-WOW-SELF-BUILD-FIRST-V18'

    full_self_build = list(data.get('self_build_ranked') or [])
    assert full_self_build
    recommended_before = data.get('recommended_self_build') or {}
    recommended_key = (
        recommended_before.get('route'),
        recommended_before.get('cpu'),
        recommended_before.get('gpu'),
        int(recommended_before.get('tcwp') or 0),
    )

    published_self_build = full_self_build[:MAX_PUBLISHED_SELF_BUILDS]
    ranked_other = [
        r for r in (data.get('ranked') or [])
        if r.get('route') not in SELF_BUILD_ROUTES
    ]

    data['self_build_evaluated_count'] = len(full_self_build)
    data['self_build_ranked'] = published_self_build
    data['ranked'] = published_self_build + ranked_other
    data['publication_compaction'] = {
        'mode': 'TOP_SELF_BUILDS_AFTER_FULL_V18_GATE',
        'evaluated_self_builds': len(full_self_build),
        'published_self_builds': len(published_self_build),
        'max_published_self_builds': MAX_PUBLISHED_SELF_BUILDS,
        'decision_scope': 'FULL_UNIVERSE_BEFORE_COMPACTION',
    }

    recommended_after = data.get('recommended_self_build') or {}
    after_key = (
        recommended_after.get('route'),
        recommended_after.get('cpu'),
        recommended_after.get('gpu'),
        int(recommended_after.get('tcwp') or 0),
    )
    assert after_key == recommended_key
    assert published_self_build and published_self_build[0].get('tcwp') == recommended_after.get('tcwp')

    SRC.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    size = SRC.stat().st_size
    assert size < MAX_BYTES, f'Published V18 snapshot still too large: {size / 1024 / 1024:.2f} MiB'
    print(json.dumps({
        'compacted': True,
        'evaluated_self_builds': len(full_self_build),
        'published_self_builds': len(published_self_build),
        'size_mib': round(size / 1024 / 1024, 2),
        'recommended_tcwp': recommended_after.get('tcwp'),
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
