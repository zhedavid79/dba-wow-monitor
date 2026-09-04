from __future__ import annotations

import asyncio

import dba_browser_v6_recovery as recovery
from dba_listing_intelligence import enrich_result_file

T1_CACHE: dict[str, dict] = {}
_original_fetch_t1_one = recovery.v6.fetch_t1_one


async def cached_fetch_t1_one(context, listing_id: str):
    t1, error = await _original_fetch_t1_one(context, listing_id)
    if t1 is not None:
        T1_CACHE[str(listing_id)] = t1
    return t1, error


async def main() -> None:
    # Price/status/identity gates remain in V6/V6 recovery. This wrapper only retains
    # the already-fetched T1 listing payload so description intelligence can reuse it
    # without another DBA request.
    recovery.v6.fetch_t1_one = cached_fetch_t1_one
    await recovery.v6.main()
    enrich_result_file("results/wow_a3_latest.json", T1_CACHE)


if __name__ == "__main__":
    asyncio.run(main())
