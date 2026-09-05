from __future__ import annotations

import asyncio
import json

from dba_browser_v3 import discover_cards_by_article
import dba_z20_parts as parts

PART_FALLBACK_QUERY_TIMEOUT_SECONDS = 35
PART_FALLBACK_TOTAL_DEADLINE_SECONDS = 180
PART_FALLBACK_CONCURRENCY = 3
PART_LONG_TAIL_QUERY_TIMEOUT_SECONDS = 45
PART_LONG_TAIL_TOTAL_DEADLINE_SECONDS = 120
PART_LONG_TAIL_CONCURRENCY = 2


def _merge_rows(found: dict[str, dict], rows: list[dict], query: str) -> None:
    for row in rows:
        if not isinstance(row.get("ask_t0"), int) or row["ask_t0"] > parts.MAX_PRICE or not parts.plausible_at_t0(row):
            continue
        listing_id = str(row["listing_id"])
        existing = found.get(listing_id)
        if existing is None:
            row["source_queries"] = [query]
            found[listing_id] = row
        elif query not in existing.setdefault("source_queries", []):
            existing["source_queries"].append(query)


def _normalise_error(query: str, error: dict | None, fallback: str) -> dict | None:
    if not error:
        return None
    return {
        "query": query,
        "error": error.get("error") or fallback,
        "detail": str(error.get("detail") or "")[:260],
        "attempts": error.get("attempts"),
    }


async def _primary_query(context, sem: asyncio.Semaphore, query: str) -> tuple[str, list[dict], dict | None]:
    async with sem:
        try:
            rows, error, attempts = await parts.runtime.discover_one(context, query)
            normalised = _normalise_error(query, error, "PRIMARY_QUERY_FAILED")
            if normalised is not None and normalised.get("attempts") is None:
                normalised["attempts"] = attempts
            print(json.dumps({
                "stage": "PART_DISCOVERY",
                "query": query,
                "rows": len(rows),
                "attempts": attempts,
                "error": normalised["error"] if normalised else None,
            }, ensure_ascii=False), flush=True)
            return query, rows, normalised
        except Exception as exc:
            error = {"query": query, "error": type(exc).__name__, "detail": str(exc)[:260]}
            print(json.dumps({
                "stage": "PART_DISCOVERY",
                "query": query,
                "rows": 0,
                "attempts": None,
                "error": error["error"],
            }, ensure_ascii=False), flush=True)
            return query, [], error


async def _recover_query(context, sem: asyncio.Semaphore, query: str) -> tuple[str, list[dict], dict | None]:
    async with sem:
        try:
            rows, error, attempts = await asyncio.wait_for(
                parts.runtime.discover_one(context, query),
                timeout=PART_FALLBACK_QUERY_TIMEOUT_SECONDS,
            )
            normalised = _normalise_error(query, error, "FALLBACK_QUERY_FAILED")
            if normalised is not None and normalised.get("attempts") is None:
                normalised["attempts"] = attempts
            return query, rows, normalised
        except asyncio.TimeoutError:
            return query, [], {
                "query": query,
                "error": "FALLBACK_QUERY_TIMEOUT",
                "detail": f"isolated fallback exceeded {PART_FALLBACK_QUERY_TIMEOUT_SECONDS}s",
            }
        except Exception as exc:
            return query, [], {
                "query": query,
                "error": type(exc).__name__,
                "detail": f"isolated fallback: {str(exc)[:260]}",
            }


async def _long_tail_query(context, sem: asyncio.Semaphore, query: str) -> tuple[str, list[dict], dict | None]:
    # Important: do not call runtime.discover_one here. That helper hard-caps each
    # attempt at 12 seconds, so wrapping it in a 35-second wait never gives a slow
    # DBA search page more time. This final pass performs one genuinely longer
    # fresh-page fetch and still fails closed if it cannot complete.
    async with sem:
        page = await context.new_page()
        try:
            rows = await asyncio.wait_for(
                discover_cards_by_article(page, query),
                timeout=PART_LONG_TAIL_QUERY_TIMEOUT_SECONDS,
            )
            return query, rows, None
        except asyncio.TimeoutError:
            return query, [], {
                "query": query,
                "error": "LONG_TAIL_QUERY_TIMEOUT",
                "detail": f"direct long-tail fetch exceeded {PART_LONG_TAIL_QUERY_TIMEOUT_SECONDS}s",
            }
        except Exception as exc:
            return query, [], {
                "query": query,
                "error": type(exc).__name__,
                "detail": f"long-tail fetch: {str(exc)[:260]}",
            }
        finally:
            await page.close()


def _failed_in_query_order(completed: set[str], errors: list[dict]) -> list[str]:
    failed = {str(e.get("query")) for e in errors if e.get("query")}
    failed.update(q for q in parts.QUERIES if q not in completed)
    return [q for q in parts.QUERIES if q in failed]


def recovery_regression() -> None:
    original = list(parts.QUERIES)
    try:
        parts.QUERIES[:] = ["a", "b", "c", "d"]
        got = _failed_in_query_order({"a", "b", "d"}, [{"query": "b", "error": "QUERY_TIMEOUT"}])
        assert got == ["b", "c"], got
    finally:
        parts.QUERIES[:] = original


async def robust_discover_all(context) -> tuple[dict[str, dict], list[dict], dict]:
    # The old implementation wrapped gather() in wait_for(). When the global deadline
    # expired, gather was cancelled and every already-completed query result was then
    # discarded by assigning results=[]. Keep completed tasks and recover only genuine
    # failures/misses.
    primary_sem = asyncio.Semaphore(parts.DISCOVERY_CONCURRENCY)
    task_to_query = {
        asyncio.create_task(_primary_query(context, primary_sem, query)): query
        for query in parts.QUERIES
    }
    done, pending = await asyncio.wait(
        set(task_to_query),
        timeout=parts.DISCOVERY_TOTAL_DEADLINE_SECONDS,
    )
    primary_deadline_exceeded = bool(pending)
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)

    found: dict[str, dict] = {}
    primary_errors: list[dict] = []
    completed: set[str] = set()

    for task in done:
        query = task_to_query[task]
        try:
            q, rows, error = task.result()
        except Exception as exc:
            q, rows, error = query, [], {
                "query": query,
                "error": type(exc).__name__,
                "detail": str(exc)[:260],
            }
        completed.add(q)
        if error:
            primary_errors.append(error)
        _merge_rows(found, rows, q)

    ordered_failed = _failed_in_query_order(completed, primary_errors)
    if not ordered_failed:
        coverage = {
            "query_total": len(parts.QUERIES),
            "query_completed": len(parts.QUERIES),
            "query_failed": 0,
            "missing_queries": [],
            "deadline_exceeded": False,
            "complete": True,
            "recovery_used": False,
            "recovered_queries": [],
            "long_tail_recovered_queries": [],
            "primary_failed_queries": [],
            "primary_deadline_exceeded": primary_deadline_exceeded,
        }
        return found, [], coverage

    recovery_sem = asyncio.Semaphore(PART_FALLBACK_CONCURRENCY)
    recovery_task_to_query = {
        asyncio.create_task(_recover_query(context, recovery_sem, query)): query
        for query in ordered_failed
    }
    recovery_done, recovery_pending = await asyncio.wait(
        set(recovery_task_to_query),
        timeout=PART_FALLBACK_TOTAL_DEADLINE_SECONDS,
    )
    for task in recovery_pending:
        task.cancel()
    if recovery_pending:
        await asyncio.gather(*recovery_pending, return_exceptions=True)

    recovered: list[str] = []
    first_pass_errors: list[dict] = []
    result_by_query: dict[str, tuple[list[dict], dict | None]] = {}

    for task in recovery_done:
        query = recovery_task_to_query[task]
        try:
            q, rows, error = task.result()
        except Exception as exc:
            q, rows, error = query, [], {
                "query": query,
                "error": type(exc).__name__,
                "detail": str(exc)[:260],
            }
        result_by_query[q] = (rows, error)

    for index, query in enumerate(ordered_failed, 1):
        if query in result_by_query:
            rows, error = result_by_query[query]
        else:
            rows, error = [], {
                "query": query,
                "error": "FALLBACK_TOTAL_DEADLINE",
                "detail": f"parts recovery budget {PART_FALLBACK_TOTAL_DEADLINE_SECONDS}s exhausted",
            }

        if error is None:
            _merge_rows(found, rows, query)
            recovered.append(query)
        else:
            first_pass_errors.append(error)

        print(json.dumps({
            "stage": "PART_DISCOVERY_RECOVERY",
            "index": index,
            "total": len(ordered_failed),
            "query": query,
            "rows": len(rows),
            "recovered": error is None,
            "error": error.get("error") if error else None,
            "unique_total": len(found),
        }, ensure_ascii=False), flush=True)

    # A small subset of queries can consistently need more than runtime.discover_one's
    # 12-second per-attempt cap. Give only those unresolved queries one longer direct
    # fetch. A zero-result response is a valid completed query; a timeout/error remains
    # a hard coverage failure.
    long_tail_queries = [q for q in ordered_failed if any(str(e.get("query")) == q for e in first_pass_errors)]
    long_tail_recovered: list[str] = []
    remaining_errors: list[dict] = []
    long_tail_pending: set[asyncio.Task] = set()

    if long_tail_queries:
        long_tail_sem = asyncio.Semaphore(PART_LONG_TAIL_CONCURRENCY)
        long_task_to_query = {
            asyncio.create_task(_long_tail_query(context, long_tail_sem, query)): query
            for query in long_tail_queries
        }
        long_done, long_tail_pending = await asyncio.wait(
            set(long_task_to_query),
            timeout=PART_LONG_TAIL_TOTAL_DEADLINE_SECONDS,
        )
        for task in long_tail_pending:
            task.cancel()
        if long_tail_pending:
            await asyncio.gather(*long_tail_pending, return_exceptions=True)

        long_results: dict[str, tuple[list[dict], dict | None]] = {}
        for task in long_done:
            query = long_task_to_query[task]
            try:
                q, rows, error = task.result()
            except Exception as exc:
                q, rows, error = query, [], {
                    "query": query,
                    "error": type(exc).__name__,
                    "detail": str(exc)[:260],
                }
            long_results[q] = (rows, error)

        for index, query in enumerate(long_tail_queries, 1):
            if query in long_results:
                rows, error = long_results[query]
            else:
                rows, error = [], {
                    "query": query,
                    "error": "LONG_TAIL_TOTAL_DEADLINE",
                    "detail": f"long-tail budget {PART_LONG_TAIL_TOTAL_DEADLINE_SECONDS}s exhausted",
                }
            if error is None:
                _merge_rows(found, rows, query)
                long_tail_recovered.append(query)
            else:
                remaining_errors.append(error)

            print(json.dumps({
                "stage": "PART_DISCOVERY_LONG_TAIL",
                "index": index,
                "total": len(long_tail_queries),
                "query": query,
                "rows": len(rows),
                "recovered": error is None,
                "error": error.get("error") if error else None,
                "unique_total": len(found),
            }, ensure_ascii=False), flush=True)
    else:
        remaining_errors = []

    unresolved = {str(e.get("query")) for e in remaining_errors if e.get("query")}
    coverage = {
        "query_total": len(parts.QUERIES),
        "query_completed": len(parts.QUERIES) - len(unresolved),
        "query_failed": len(remaining_errors),
        "missing_queries": sorted(unresolved),
        "deadline_exceeded": bool(long_tail_pending) or any(
            e.get("error") in {"FALLBACK_TOTAL_DEADLINE", "LONG_TAIL_TOTAL_DEADLINE"}
            for e in remaining_errors
        ),
        "complete": not remaining_errors,
        "recovery_used": True,
        "recovered_queries": recovered,
        "long_tail_recovered_queries": long_tail_recovered,
        "primary_failed_queries": ordered_failed,
        "primary_completed_queries": len(completed),
        "primary_deadline_exceeded": primary_deadline_exceeded,
        "fallback_query_timeout_seconds": PART_FALLBACK_QUERY_TIMEOUT_SECONDS,
        "fallback_total_deadline_seconds": PART_FALLBACK_TOTAL_DEADLINE_SECONDS,
        "fallback_concurrency": PART_FALLBACK_CONCURRENCY,
        "long_tail_query_timeout_seconds": PART_LONG_TAIL_QUERY_TIMEOUT_SECONDS,
        "long_tail_total_deadline_seconds": PART_LONG_TAIL_TOTAL_DEADLINE_SECONDS,
        "long_tail_concurrency": PART_LONG_TAIL_CONCURRENCY,
    }
    return found, remaining_errors, coverage


recovery_regression()
parts.discover_all = robust_discover_all


if __name__ == "__main__":
    asyncio.run(parts.main())
