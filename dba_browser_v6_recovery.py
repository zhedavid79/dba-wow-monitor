from __future__ import annotations

import asyncio
import json

import dba_browser_v6 as v6
from dba_browser_v3 import discover_cards_by_article

FALLBACK_QUERY_TIMEOUT_SECONDS = 35
FALLBACK_TOTAL_DEADLINE_SECONDS = 180

_original_discover_all = v6.discover_all


async def _recover_query(context, query: str) -> tuple[list[dict], dict | None]:
    """Retry one failed discovery query in isolation on a fresh page.

    This is deliberately sequential at the caller. The primary discovery pass remains parallel;
    only queries that exhausted the normal 2x12s attempts are retried without concurrent DBA
    navigation pressure. Failure remains fail-closed.
    """
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

    # A global deadline keeps the fallback bounded even if DBA is broadly unhealthy.
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
        "deadline_exceeded": bool(remaining_errors and any(e.get("error") == "FALLBACK_TOTAL_DEADLINE" for e in remaining_errors)),
        "complete": not remaining_errors,
        "recovery_used": True,
        "recovered_queries": recovered,
        "primary_failed_queries": ordered_failed,
        "fallback_query_timeout_seconds": FALLBACK_QUERY_TIMEOUT_SECONDS,
        "fallback_total_deadline_seconds": FALLBACK_TOTAL_DEADLINE_SECONDS,
    }
    return found, remaining_errors, coverage


# Keep the production ranking/gates untouched; replace only its discovery implementation.
v6.discover_all = robust_discover_all


if __name__ == "__main__":
    asyncio.run(v6.main())
