from __future__ import annotations

import asyncio
import json
from collections import Counter

import dba_browser_v6 as v6
from dba_browser_v3 import discover_cards_by_article

FALLBACK_QUERY_TIMEOUT_SECONDS = 35
FALLBACK_TOTAL_DEADLINE_SECONDS = 180

# Live evidence:
# - concurrency=8 completed T1 fetches with 0 individual fetch errors, but the old 300s
#   global deadline was too short for the full high-recall candidate set.
# - concurrency=16 produced 376 fetch errors in run #43.
# Keep the proven-stable load level and solve runtime with a larger bounded budget plus
# a narrow recovery pass rather than increasing parallel pressure.
T1_PRIMARY_CONCURRENCY = 8
T1_PRIMARY_TOTAL_DEADLINE_SECONDS = 600
T1_RECOVERY_CONCURRENCY = 2
T1_RECOVERY_TOTAL_DEADLINE_SECONDS = 180

v6.T1_CONCURRENCY = T1_PRIMARY_CONCURRENCY
v6.T1_TOTAL_DEADLINE_SECONDS = T1_PRIMARY_TOTAL_DEADLINE_SECONDS

_original_discover_all = v6.discover_all
_original_fetch_all_t1 = v6.fetch_all_t1


async def _recover_query(context, query: str) -> tuple[list[dict], dict | None]:
    """Retry one failed discovery query in isolation on a fresh page."""
    page = await context.new_page()
    try:
        rows = await asyncio.wait_for(
            discover_cards_by_article(page, query),
            timeout=FALLBACK_QUERY_TIMEOUT_SECONDS,
        )
        return rows, None
    except asyncio.TimeoutError:
        return [], {
            "query": query,
            "error": "FALLBACK_QUERY_TIMEOUT",
            "detail": f"isolated fallback exceeded {FALLBACK_QUERY_TIMEOUT_SECONDS}s",
        }
    except Exception as exc:
        return [], {
            "query": query,
            "error": type(exc).__name__,
            "detail": f"isolated fallback: {str(exc)[:260]}",
        }
    finally:
        await page.close()


def _merge_rows(found: dict[str, dict], rows: list[dict], query: str) -> None:
    for row in rows:
        listing_id = row["listing_id"]
        existing = found.get(listing_id)
        if existing is None:
            row["source_queries"] = [query]
            found[listing_id] = row
        elif query not in existing.setdefault("source_queries", []):
            existing["source_queries"].append(query)


async def robust_discover_all(context) -> tuple[dict[str, dict], list[dict], dict]:
    found, errors, coverage = await _original_discover_all(context)
    if coverage.get("complete"):
        coverage["recovery_used"] = False
        coverage["recovered_queries"] = []
        return found, errors, coverage

    failed_queries = {str(e.get("query")) for e in errors if e.get("query")}
    failed_queries.update(str(q) for q in coverage.get("missing_queries") or [])
    ordered_failed = [q for q in v6.v2.QUERIES if q in failed_queries]

    loop = asyncio.get_running_loop()
    deadline = loop.time() + FALLBACK_TOTAL_DEADLINE_SECONDS
    recovered: list[str] = []
    remaining_errors: list[dict] = []

    for index, query in enumerate(ordered_failed, 1):
        remaining = deadline - loop.time()
        if remaining <= 0:
            remaining_errors.append({
                "query": query,
                "error": "FALLBACK_TOTAL_DEADLINE",
                "detail": f"recovery budget {FALLBACK_TOTAL_DEADLINE_SECONDS}s exhausted",
            })
            continue
        try:
            rows, error = await asyncio.wait_for(
                _recover_query(context, query),
                timeout=min(FALLBACK_QUERY_TIMEOUT_SECONDS + 2, remaining),
            )
        except asyncio.TimeoutError:
            rows, error = [], {
                "query": query,
                "error": "FALLBACK_TOTAL_DEADLINE",
                "detail": "query exceeded remaining recovery budget",
            }

        if error is None:
            _merge_rows(found, rows, query)
            recovered.append(query)
        else:
            remaining_errors.append(error)

        print(json.dumps({
            "stage": "DISCOVERY_RECOVERY",
            "index": index,
            "total": len(ordered_failed),
            "query": query,
            "rows": len(rows),
            "recovered": error is None,
            "error": error.get("error") if error else None,
            "unique_total": len(found),
        }, ensure_ascii=False), flush=True)

    unresolved = {str(e.get("query")) for e in remaining_errors if e.get("query")}
    coverage = {
        **coverage,
        "query_completed": len(v6.v2.QUERIES) - len(unresolved),
        "query_failed": len(remaining_errors),
        "missing_queries": sorted(unresolved),
        "deadline_exceeded": bool(
            remaining_errors
            and any(e.get("error") == "FALLBACK_TOTAL_DEADLINE" for e in remaining_errors)
        ),
        "complete": not remaining_errors,
        "recovery_used": True,
        "recovered_queries": recovered,
        "primary_failed_queries": ordered_failed,
        "fallback_query_timeout_seconds": FALLBACK_QUERY_TIMEOUT_SECONDS,
        "fallback_total_deadline_seconds": FALLBACK_TOTAL_DEADLINE_SECONDS,
    }
    return found, remaining_errors, coverage


def _diagnostic_kind(diagnostic: dict) -> str:
    return str(diagnostic.get("result") or diagnostic.get("error") or "UNKNOWN")


async def _recover_t1_one(context, listing_id: str) -> tuple[str, dict | None, dict | None]:
    t1, error = await v6.fetch_t1_one(context, listing_id)
    return listing_id, t1, error


async def robust_fetch_all_t1(context, candidates: list[dict]) -> tuple[dict[str, dict | None], list[dict], dict]:
    """Run the proven-stable T1 load first, then retry only unresolved IDs.

    A candidate is considered fully covered only if it ends with a successful T1 object.
    This is intentionally stricter than the base scanner: a transient fetch error cannot hide a
    potential sweet spot and still allow publication.
    """
    results, diagnostics, primary_coverage = await _original_fetch_all_t1(context, candidates)

    expected_ids = {str(row["listing_id"]) for row in candidates}
    failed_ids = {str(d.get("listing_id")) for d in diagnostics if d.get("listing_id")}
    missing_ids = set(str(x) for x in primary_coverage.get("missing_listing_ids") or [])
    retry_ids = sorted((failed_ids | missing_ids) & expected_ids)

    error_counts = Counter(_diagnostic_kind(d) for d in diagnostics)
    print(json.dumps({
        "stage": "T1_PRIMARY_COMPLETE",
        "candidate_total": len(expected_ids),
        "successful_objects": sum(1 for lid in expected_ids if results.get(lid)),
        "retry_ids": len(retry_ids),
        "error_types": dict(error_counts),
        "deadline_exceeded": bool(primary_coverage.get("deadline_exceeded")),
        "concurrency": T1_PRIMARY_CONCURRENCY,
        "deadline_seconds": T1_PRIMARY_TOTAL_DEADLINE_SECONDS,
    }, ensure_ascii=False), flush=True)

    if not retry_ids:
        coverage = {
            **primary_coverage,
            "candidate_completed": len(expected_ids),
            "candidate_fetch_errors": 0,
            "missing_listing_ids": [],
            "deadline_exceeded": False,
            "complete": True,
            "recovery_used": False,
            "primary_concurrency": T1_PRIMARY_CONCURRENCY,
            "primary_deadline_seconds": T1_PRIMARY_TOTAL_DEADLINE_SECONDS,
        }
        return results, [], coverage

    queue: asyncio.Queue[str | None] = asyncio.Queue()
    for lid in retry_ids:
        queue.put_nowait(lid)
    for _ in range(T1_RECOVERY_CONCURRENCY):
        queue.put_nowait(None)

    recovery_errors: list[dict] = []
    recovered_ids: set[str] = set()
    attempted_ids: set[str] = set()
    lock = asyncio.Lock()

    async def worker(worker_no: int) -> None:
        while True:
            lid = await queue.get()
            try:
                if lid is None:
                    return
                _, t1, error = await _recover_t1_one(context, lid)
                async with lock:
                    attempted_ids.add(lid)
                    if t1 is not None:
                        results[lid] = t1
                        recovered_ids.add(lid)
                    else:
                        recovery_errors.append(error or {
                            "listing_id": lid,
                            "result": "T1_RECOVERY_NO_OBJECT",
                            "detail": "recovery returned no T1 object",
                        })
                    completed = len(attempted_ids)
                    if completed == 1 or completed % 20 == 0 or completed == len(retry_ids):
                        print(json.dumps({
                            "stage": "T1_RECOVERY_PROGRESS",
                            "worker": worker_no,
                            "completed": completed,
                            "total": len(retry_ids),
                            "recovered": len(recovered_ids),
                            "errors": len(recovery_errors),
                        }, ensure_ascii=False), flush=True)
            finally:
                queue.task_done()

    workers = [asyncio.create_task(worker(i + 1)) for i in range(T1_RECOVERY_CONCURRENCY)]
    recovery_timed_out = False
    try:
        await asyncio.wait_for(queue.join(), timeout=T1_RECOVERY_TOTAL_DEADLINE_SECONDS)
    except asyncio.TimeoutError:
        recovery_timed_out = True
    finally:
        if recovery_timed_out:
            for task in workers:
                task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)

    unresolved_ids = sorted(lid for lid in expected_ids if not results.get(lid))
    recovery_error_counts = Counter(_diagnostic_kind(d) for d in recovery_errors)
    print(json.dumps({
        "stage": "T1_RECOVERY_COMPLETE",
        "requested": len(retry_ids),
        "attempted": len(attempted_ids),
        "recovered": len(recovered_ids),
        "unresolved": len(unresolved_ids),
        "error_types": dict(recovery_error_counts),
        "deadline_exceeded": recovery_timed_out,
        "concurrency": T1_RECOVERY_CONCURRENCY,
        "deadline_seconds": T1_RECOVERY_TOTAL_DEADLINE_SECONDS,
    }, ensure_ascii=False), flush=True)

    coverage = {
        "candidate_total": len(expected_ids),
        "candidate_completed": len(expected_ids) - len(unresolved_ids),
        "candidate_fetch_errors": len(recovery_errors),
        "missing_listing_ids": unresolved_ids,
        "deadline_exceeded": recovery_timed_out,
        "complete": (not recovery_timed_out and not unresolved_ids),
        "recovery_used": True,
        "primary_concurrency": T1_PRIMARY_CONCURRENCY,
        "primary_deadline_seconds": T1_PRIMARY_TOTAL_DEADLINE_SECONDS,
        "recovery_concurrency": T1_RECOVERY_CONCURRENCY,
        "recovery_deadline_seconds": T1_RECOVERY_TOTAL_DEADLINE_SECONDS,
        "primary_error_types": dict(error_counts),
        "recovery_error_types": dict(recovery_error_counts),
        "recovered_listing_ids": sorted(recovered_ids),
    }
    return results, recovery_errors, coverage


# Keep production discovery/ranking/price/status/identity gates untouched.
v6.discover_all = robust_discover_all
v6.fetch_all_t1 = robust_fetch_all_t1


if __name__ == "__main__":
    asyncio.run(v6.main())
