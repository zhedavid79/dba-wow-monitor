from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import dba_browser_v7_intelligence as v7

CACHE = Path('results/t1_cache_v20.json')


def _safe_entries() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for lid, row in v7.T1_CACHE.items():
        if not isinstance(row, dict):
            continue
        if not row.get('identity_ok'):
            continue
        if str(row.get('canonical_url') or '').rstrip('/').split('/')[-1] != str(lid):
            continue
        out[str(lid)] = row
    return out


async def main() -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    if CACHE.exists():
        CACHE.unlink()
    v7.T1_CACHE.clear()
    await v7.main()
    entries = _safe_entries()
    doc = {
        'model':'V20_SAME_RUN_T1_CACHE',
        'generated_at':datetime.now(timezone.utc).isoformat(),
        'source':'dba_browser_v7_intelligence T1 objects from current workflow run',
        'entries':entries,
        'counts':{'raw':len(v7.T1_CACHE),'safe':len(entries)},
    }
    CACHE.write_text(json.dumps(doc,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'t1_cache':True,'safe_entries':len(entries),'path':str(CACHE)},ensure_ascii=False),flush=True)


if __name__ == '__main__':
    asyncio.run(main())
