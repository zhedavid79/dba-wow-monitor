from __future__ import annotations

import asyncio
import json
from pathlib import Path

import dba_browser_v6_recovery as recovery
from dba_listing_intelligence import enrich_result_file
from dba_t1_hydration_ancestor import fetch_hydration_ancestor

T1_CACHE: dict[str, dict] = {}
_original_fetch_t1_one = recovery.v6.fetch_t1_one


async def cached_fetch_t1_one(context, listing_id: str):
    t1, error = await _original_fetch_t1_one(context, listing_id)
    if t1 is None and error is None:
        t1 = await fetch_hydration_ancestor(context, str(listing_id))
    if t1 is not None:
        T1_CACHE[str(listing_id)] = t1
    return t1, error


def reconcile_description_aware_ranking(path: str = "results/wow_a3_latest.json") -> None:
    p = Path(path)
    doc = json.loads(p.read_text(encoding="utf-8"))

    combined = []
    seen = set()
    for section in ("ranked", "potential_sweet_spots_unresolved"):
        for row in doc.get(section) or []:
            lid = str(row.get("listing_id"))
            if not lid or lid in seen:
                continue
            seen.add(lid)
            combined.append(row)

    ranked = []
    unresolved = []
    under_minimum = []
    for row in combined:
        intel = row.get("listing_intelligence") or {}
        cpu = intel.get("cpu") or {}
        gpu = intel.get("gpu") or {}
        cpu_score = int(intel.get("cpu_score") or 0)
        gpu_score = int(intel.get("gpu_score") or 0)
        cpu_ok = cpu.get("confidence") == "VERIFIED" and bool(cpu.get("value")) and cpu_score >= 50
        gpu_ok = gpu.get("confidence") == "VERIFIED" and bool(gpu.get("value")) and gpu_score >= 50

        if cpu_ok and gpu_ok:
            pclass = recovery.v6.v2.performance_class(gpu_score, cpu_score)
            row["cpu"] = cpu["value"]
            row["cpu_score"] = cpu_score
            row["gpu"] = gpu["value"]
            row["gpu_score"] = gpu_score
            row["performance_class"] = pclass
            if pclass == "UNDER MINIMUM":
                row["description_aware_resolution"] = "UNDER_MINIMUM"
                under_minimum.append(row)
            else:
                row.pop("resolution_status", None)
                row.pop("resolution_reason", None)
                row["description_aware_resolution"] = "RANKED"
                ranked.append(row)
        else:
            row["resolution_status"] = "POTENTIAL_SWEET_SPOT_UNRESOLVED"
            missing = []
            if not cpu_ok:
                missing.append("CPU_NOT_DESCRIPTION_VERIFIED")
            if not gpu_ok:
                missing.append("GPU_NOT_DESCRIPTION_VERIFIED")
            row["resolution_reason"] = "+".join(missing)
            row["description_aware_resolution"] = "UNRESOLVED"
            unresolved.append(row)

    class_order = {"SWEET SPOT": 0, "ACCEPTABLE": 1, "OVERKILL": 2}
    ranked.sort(key=lambda r: (int(r.get("ask_t1") or 10**9), class_order.get(r.get("performance_class"), 9), -int(r.get("gpu_score") or 0), -int(r.get("cpu_score") or 0)))
    unresolved.sort(key=lambda r: (int(r.get("ask_t1") or 10**9), str(r.get("listing_id") or "")))

    doc["model_version"] = "DBA-WOW-PRICE-FIRST-COMPLETE-PC-V14"
    doc["target"] = "WoW Classic/Cataclysm at 3840x1600 up to 75 Hz"
    doc["scope"] = "Complete ready-to-use desktop gaming PCs, gaming laptops and mini PCs only. No self-build, donor-build or component procurement."
    doc["ranked"] = ranked
    doc["potential_sweet_spots_unresolved"] = unresolved
    doc.setdefault("counts", {})["ranked"] = len(ranked)
    doc["counts"]["potential_sweet_spot_unresolved"] = len(unresolved)
    doc["listing_intelligence"]["ranking_reconciled"] = True
    doc["listing_intelligence"]["under_minimum_after_context_parse"] = len(under_minimum)
    doc["listing_intelligence"]["ranking_rule"] = "Only context-verified CPU+GPU from title/description may enter ranked output. Bare GPU numbers cannot satisfy CPU evidence."
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


async def main() -> None:
    recovery.v6.fetch_t1_one = cached_fetch_t1_one
    await recovery.v6.main()
    enrich_result_file("results/wow_a3_latest.json", T1_CACHE)
    reconcile_description_aware_ranking()


if __name__ == "__main__":
    asyncio.run(main())
