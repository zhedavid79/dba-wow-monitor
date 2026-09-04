from __future__ import annotations

import asyncio
import json

import dba_z20_parts as parts

PART_FALLBACK_QUERY_TIMEOUT_SECONDS = 35
PART_FALLBACK_TOTAL_DEADLINE_SECONDS = 180

_original_discover_all = parts.discover_all


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


async def _recover_query(context, query: str) -> tuple[list[dict], dict | None]:
    try:
        rows, error, attempts = await asyncio.wait_for(
            parts.runtime.discover_one(context, query),
            timeout=PART_FALLBACK_QUERY_TIMEOUT_SECONDS,
        )
        if error:
            return rows, {
                "query": query,
                "error": error.get("error") or "FALLBACK_QUERY_FAILED",
                "detail": error.get("detail", "")[:260],
                "attempts": attempts,
            }
        return rows, None
    except asyncio.TimeoutError:
        return [], {
            "query": query,
            "error": "FALLBACK_QUERY_TIMEOUT",
            "detail": f"isolated fallback exceeded {PART_FALLBACK_QUERY_TIMEOUT_SECONDS}s",
        }
    except Exception as exc:
        return [], {
            "query": query,
            "error": type(exc).__name__,
            "detail": f"isolated fallback: {str(exc)[:260]}",
        }


async def robust_discover_all(context) -> tuple[dict[str, dict], list[dict], dict]:
    found, errors, coverage = await _original_discover_all(context)
    if coverage.get("complete"):
        coverage["recovery_used"] = False
        coverage["recovered_queries"] = []
        return found, errors, coverage

    failed_queries = {str(e.get("query")) for e in errors if e.get("query")}
    failed_queries.update(str(q) for q in coverage.get("missing_queries") or [])
    ordered_failed = [q for q in parts.QUERIES if q in failed_queries]

    loop = asyncio.get_running_loop()
    deadline = loop.time() + PART_FALLBACK_TOTAL_DEADLINE_SECONDS
    recovered: list[str] = []
    remaining_errors: list[dict] = []

    for index, query in enumerate(ordered_failed, 1):
        remaining = deadline - loop.time()
        if remaining <= 0:
            remaining_errors.append({
                "query": query,
                "error": "FALLBACK_TOTAL_DEADLINE",
                "detail": f"parts recovery budget {PART_FALLBACK_TOTAL_DEADLINE_SECONDS}s exhausted",
            })
            continue
        try:
            rows, error = await asyncio.wait_for(
                _recover_query(context, query),
                timeout=min(PART_FALLBACK_QUERY_TIMEOUT_SECONDS + 2, remaining),
            )
        except asyncio.TimeoutError:
            rows, error = [], {
                "query": query,
                "error": "FALLBACK_TOTAL_DEADLINE",
                "detail": "query exceeded remaining parts recovery budget",
            }

        if error is None:
            _merge_rows(found, rows, query)
            recovered.append(query)
        else:
            remaining_errors.append(error)

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

    unresolved = {str(e.get("query")) for e in remaining_errors if e.get("query")}
    coverage = {
        **coverage,
        "query_completed": len(parts.QUERIES) - len(unresolved),
        "query_failed": len(remaining_errors),
        "missing_queries": sorted(unresolved),
        "deadline_exceeded": any(e.get("error") == "FALLBACK_TOTAL_DEADLINE" for e in remaining_errors),
        "complete": not remaining_errors,
        "recovery_used": True,
        "recovered_queries": recovered,
        "primary_failed_queries": ordered_failed,
        "fallback_query_timeout_seconds": PART_FALLBACK_QUERY_TIMEOUT_SECONDS,
        "fallback_total_deadline_seconds": PART_FALLBACK_TOTAL_DEADLINE_SECONDS,
    }
    return found, remaining_errors, coverage


parts.discover_all = robust_discover_all


if __name__ == "__main__":
    asyncio.run(parts.main())
