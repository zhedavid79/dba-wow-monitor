from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import dba_strategy_parts as base

parts = base.parts
CACHE = Path('results/t1_cache_v20.json')
MAX_CACHE_AGE_SECONDS = 20 * 60

# Sweet-spot protection: target families get explicit variants instead of relying on
# one broad query or a cheapest-N pool. RAM discovery is widened around the actual
# AM5 long-term target as well as bridge kits.
EXTRA_QUERIES_V20 = [
    'rx 6700 xt 12gb', 'rx 6750 xt 12gb', 'rx 6800 16gb', 'rx 6800 xt 16gb',
    'rtx 3060 ti 8gb', 'rtx 3070 8gb', 'rtx 3080 10gb',
    'ddr5 6000 32gb expo', 'ddr5 6000 cl30 32gb', 'ddr5 6000 cl32 32gb',
    'ddr5 6000 2x16', 'ddr5 5600 32gb', '32gb ddr5 kit', 'am5 ram 32gb',
]
for q in EXTRA_QUERIES_V20:
    if q not in parts.QUERIES:
        parts.QUERIES.append(q)


def _parse_iso(value: str) -> datetime:
    d = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def load_same_run_cache() -> tuple[dict[str, dict], float | None]:
    if not CACHE.exists():
        return {}, None
    try:
        doc = json.loads(CACHE.read_text(encoding='utf-8'))
        if doc.get('model') != 'V20_SAME_RUN_T1_CACHE':
            return {}, None
        age = (datetime.now(timezone.utc) - _parse_iso(doc['generated_at'])).total_seconds()
        if age < 0 or age > MAX_CACHE_AGE_SECONDS:
            return {}, age
        entries = doc.get('entries') or {}
        if not isinstance(entries, dict):
            return {}, age
        return {str(k):v for k,v in entries.items() if isinstance(v,dict)}, age
    except Exception:
        return {}, None


async def shared_fetch_all_t1(context, rows: list[dict]):
    cache, cache_age = load_same_run_cache()
    by_id: dict[str, dict | None] = {}
    errors: list[dict] = []
    expected = {str(r['listing_id']) for r in rows}
    cache_hits = 0

    missing_rows = []
    for row in rows:
        lid = str(row['listing_id'])
        hit = cache.get(lid)
        if hit is not None:
            by_id[lid] = hit
            cache_hits += 1
        else:
            missing_rows.append(row)

    sem = asyncio.Semaphore(parts.T1_CONCURRENCY)

    async def run_row(row: dict):
        async with sem:
            lid = str(row['listing_id'])
            t1, error = await parts.runtime.fetch_t1_one(context, lid)
            return lid, t1, error

    tasks = [asyncio.create_task(run_row(r)) for r in missing_rows]
    timed_out = False
    network_results = []
    if tasks:
        try:
            network_results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=parts.T1_TOTAL_DEADLINE_SECONDS)
        except asyncio.TimeoutError:
            timed_out = True
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    for lid, t1, error in network_results:
        by_id[lid] = t1
        if error:
            errors.append(error)

    completed = set(by_id)
    missing = sorted(expected - completed)
    coverage = {
        'candidate_total':len(rows),
        'candidate_completed':len(completed),
        'candidate_fetch_errors':len(errors),
        'missing_listing_ids':missing,
        'deadline_exceeded':timed_out,
        'complete':not timed_out and not missing,
        'same_run_cache_model':'V20_SAME_RUN_T1_CACHE',
        'same_run_cache_hits':cache_hits,
        'network_fetches':len(network_results),
        'cache_age_seconds':round(cache_age,1) if cache_age is not None else None,
    }
    print(json.dumps({'stage':'V20_T1_CACHE_REUSE',**{k:coverage[k] for k in ('candidate_total','same_run_cache_hits','network_fetches','candidate_fetch_errors','complete')},'cache_age_seconds':coverage['cache_age_seconds']},ensure_ascii=False),flush=True)
    return by_id, errors, coverage


parts.fetch_all_t1 = shared_fetch_all_t1


def regression() -> None:
    base.defect_regression()
    for q in ('rx 6800 xt 16gb','ddr5 6000 cl30 32gb'):
        assert q in parts.QUERIES


if __name__ == '__main__':
    regression()
    asyncio.run(parts.main())
