from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

INPUT = Path("results/wow_a3_latest.json")
PARTS = Path("results/z20_parts_latest.json")
REPORT = Path("results/wow_a3_report.md")

# Retail fallbacks are only used for low-risk parts where buying new is preferred.
# They are explicit baselines, not scraped silently. If stale, the build remains a planning
# candidate but is never marked READY_TO_BUY until the retail price is refreshed.
RETAIL = {
    "case": {
        "name": "Jonsbo Z20 Mesh White",
        "price": 751,
        "url": "https://www.proshop.dk/Kabinet/Jonsbo-Z20-Mesh-Kabinet-Minitower-Hvid/3407428",
        "verified_at": "2026-09-03T22:55:00+02:00",
        "fit": "PROVEN",
    },
    "psu": {
        "name": "Corsair RM650e (2025) 650W ATX 3.1",
        "price": 642,
        "url": "https://www.proshop.dk/Stroemforsyning/Corsair-RMe-Series-RM650e-2025-Stroemforsyning-650-Watt-120-mm-ATX-31-80-Plus-Gold-certified/3324406",
        "verified_at": "2026-09-03T22:55:00+02:00",
        "length_mm": 140,
        "fit": "PROVEN_AT_RECOMMENDED_MAX",
    },
    "ssd": {
        "name": "Kingston NV3 1TB M.2 2280 PCIe 4.0",
        "price": 1269,
        "url": "https://www.proshop.dk/SSD/Kingston-NV3-SSD-1TB-PCIe-40-M2-2280/3284682",
        "verified_at": "2026-09-03T22:55:00+02:00",
        "fit": "PROVEN_M2_2280",
    },
    "am5_board": {
        "name": "ASRock B650M-HDV/M.2",
        "price": 813,
        "url": "https://www.proshop.dk/Bundkort/ASRock-B650M-HDVM2-Bundkort-AMD-B650-AMD-AM5-DDR5-RAM-Micro-ATX/3183009",
        "verified_at": "2026-09-03T22:55:00+02:00",
        "fit": "PROVEN_MICRO_ATX",
    },
    "am5_cpu": {
        "name": "AMD Ryzen 5 7600 with Wraith Stealth",
        "price": 1373,
        "url": "https://www.proshop.dk/CPU/AMD-Ryzen-5-7600-Wraith-Stealth-CPU-6-kerner-4-GHz-AMD-AM5-AMD-Boxed-med-koeler/3124135",
        "verified_at": "2026-09-03T22:55:00+02:00",
        "cpu": "Ryzen 5 7600",
        "cpu_score": 98,
        "upgradeability": "EXCELLENT",
    },
}

# Exact SKU families with manufacturer-verified dimensions. Generic GPU names are not enough.
GPU_FIT_RULES = [
    {
        "pattern": r"msi.*rtx\s*3060\s*ti.*ventus\s*2x|rtx\s*3060\s*ti.*ventus\s*2x",
        "model": "MSI RTX 3060 Ti Ventus 2X",
        "length_mm": 235,
        "height_mm": 124,
        "thickness_mm": 52,
        "recommended_psu_w": 600,
        "source": "https://www.msi.com/Graphics-Card/GeForce-RTX-3060-Ti-VENTUS-2X-8G-OCV1-LHR/Specification",
    },
    {
        "pattern": r"(?:gigabyte\s+)?(?:geforce\s+)?rtx\s*3070.*a[ou]rus\s+master|a[ou]rus.*rtx\s*3070.*master",
        "model": "Gigabyte AORUS RTX 3070 Master",
        "length_mm": 290,
        "height_mm": 131,
        "thickness_mm": 60,
        "recommended_psu_w": 650,
        "source": "https://www.gigabyte.com/eu/Graphics-Card/GV-N3070AORUS-M-8GD-rev-10-11/sp",
    },
]

UPGRADE_RANK = {"EXCELLENT": 4, "GOOD": 3, "LIMITED": 2, "POOR": 1, "UNVERIFIED": 0}


def retail_fresh() -> bool:
    now = datetime.now(timezone.utc)
    dates = []
    for item in RETAIL.values():
        dates.append(datetime.fromisoformat(item["verified_at"]).astimezone(timezone.utc))
    return all((now - d).days <= 7 for d in dates)


def ram_meta(title: str) -> tuple[str | None, int | None]:
    t = title.lower()
    mem = "DDR5" if "ddr5" in t else "DDR4" if "ddr4" in t else None
    vals = [int(x) for x in re.findall(r"\b(8|16|32|64)\s*gb\b", t)]
    return mem, max(vals) if vals else None


def platform_memory(r: dict) -> str | None:
    text = (r.get("title") or "").lower()
    if any(x in text for x in ("b650", "a620", "x670", "am5")): return "DDR5"
    if any(x in text for x in ("b550", "b450", "x570", "a520", "b560", "h510", "z390", "b365")): return "DDR4"
    if any(x in text for x in ("b660", "b760", "z690", "z790")):
        if "ddr4" in text: return "DDR4"
        if "ddr5" in text: return "DDR5"
    return None


def bundle_ram_included(r: dict, required: str | None) -> bool:
    mem, gb = ram_meta(r.get("title") or "")
    return bool(gb and gb >= 16 and (required is None or mem is None or mem == required))


def gpu_fit(r: dict) -> dict:
    title = r.get("title") or ""
    for rule in GPU_FIT_RULES:
        if re.search(rule["pattern"], title, re.I):
            return {
                "status": "PROVEN_FIT",
                "model": rule["model"],
                "length_mm": rule["length_mm"],
                "height_mm": rule["height_mm"],
                "thickness_mm": rule["thickness_mm"],
                "manufacturer_source": rule["source"],
                "reason": "Exact SKU family has manufacturer dimensions below Z20 limits; 650W/140mm retail PSU baseline covers power requirement.",
            }
    return {"status": "UNVERIFIED_SKU", "reason": "GPU family is known but exact board-partner SKU dimensions are not proven."}


def pick_ram(parts: list[dict], memory_type: str) -> dict | None:
    candidates = []
    for r in parts:
        if r.get("kind") != "RAM" or r.get("condition") == "DEFECT_DISCLOSED": continue
        mem, gb = ram_meta(r.get("title") or "")
        if mem == memory_type and gb and gb >= 16:
            candidates.append((r["ask_t1"], -gb, r))
    return sorted(candidates, key=lambda x: (x[0], x[1]))[0][2] if candidates else None


def source_component(kind: str, r: dict) -> dict:
    return {"kind": kind, "source": "DBA_USED", "name": r.get("title"), "price": r.get("ask_t1"), "url": r.get("url"), "listing_id": r.get("listing_id")}


def retail_component(kind: str, key: str) -> dict:
    r = RETAIL[key]
    return {"kind": kind, "source": "NEW_RETAIL_BASELINE", "name": r["name"], "price": r["price"], "url": r["url"], "verified_at": r["verified_at"]}


def make_build(platform: dict, gpu: dict, parts: list[dict], platform_source: str = "DBA_USED") -> dict | None:
    if platform_source == "DBA_USED":
        if platform.get("kind") != "PLATFORM_BUNDLE" or platform.get("z20_fit") != "COMPATIBLE": return None
        if platform.get("condition") == "DEFECT_DISCLOSED": return None
        if UPGRADE_RANK.get(platform.get("upgradeability"), 0) < UPGRADE_RANK["GOOD"]: return None
        memory = platform_memory(platform)
        cpu = platform.get("cpu")
        cpu_score = int(platform.get("cpu_score") or 0)
        components = [source_component("PLATFORM", platform)]
        upgrade = platform.get("upgradeability")
        if not bundle_ram_included(platform, memory):
            if not memory: return None
            ram = pick_ram(parts, memory)
            if not ram: return None
            components.append(source_component("RAM", ram))
    else:
        memory = "DDR5"; cpu = RETAIL["am5_cpu"]["cpu"]; cpu_score = RETAIL["am5_cpu"]["cpu_score"]
        upgrade = "EXCELLENT"
        ram = pick_ram(parts, "DDR5")
        if not ram: return None
        components = [retail_component("MOTHERBOARD", "am5_board"), retail_component("CPU", "am5_cpu"), source_component("RAM", ram)]

    gf = gpu_fit(gpu)
    components.append(source_component("GPU", gpu))
    components += [retail_component("CASE", "case"), retail_component("PSU", "psu"), retail_component("SSD", "ssd")]
    total = sum(int(x["price"]) for x in components)
    missing = []
    if gf["status"] != "PROVEN_FIT": missing.append("exact GPU SKU dimensions")
    if not retail_fresh(): missing.append("refresh new-part prices")
    status = "READY_TO_BUY" if not missing else "NEEDS_VERIFICATION"
    gpu_score = int(gpu.get("gpu_score") or 0)
    # WoW procurement utility: enough GPU for 3840x1600, CPU/upgrade path matter strongly thereafter.
    capped_gpu = min(gpu_score, 75); capped_cpu = min(cpu_score, 110)
    utility = round(0.45 * capped_gpu + 0.45 * capped_cpu + 2.5 * UPGRADE_RANK.get(upgrade, 0), 2)
    return {
        "status": status,
        "total_price": total,
        "cpu": cpu,
        "cpu_score": cpu_score,
        "gpu": gpu.get("gpu"),
        "gpu_score": gpu_score,
        "z20_fit": "PROVEN" if not missing else "PARTIAL",
        "gpu_fit": gf,
        "upgradeability": upgrade,
        "memory_type": memory,
        "utility": utility,
        "missing_evidence": missing,
        "components": components,
    }


def main() -> None:
    doc = json.loads(INPUT.read_text(encoding="utf-8"))
    pdoc = json.loads(PARTS.read_text(encoding="utf-8"))
    parts = pdoc.get("opportunities") or []
    gpus = [r for r in parts if r.get("kind") == "GPU" and r.get("condition") != "DEFECT_DISCLOSED" and int(r.get("gpu_score") or 0) >= 60]
    platforms = [r for r in parts if r.get("kind") == "PLATFORM_BUNDLE" and r.get("z20_fit") == "COMPATIBLE" and UPGRADE_RANK.get(r.get("upgradeability"), 0) >= 3]

    builds = []
    for platform in platforms[:12]:
        for gpu in gpus[:20]:
            b = make_build(platform, gpu, parts)
            if b: builds.append(b)
    # Always test a modern new AM5 foundation + live used RAM/GPU route. This prevents an old cheap
    # used platform from becoming the default merely because no suitable AM5 bundle is listed today.
    for gpu in gpus[:20]:
        b = make_build({}, gpu, parts, platform_source="NEW_AM5")
        if b: builds.append(b)

    # Deduplicate equivalent component sets.
    seen = set(); unique = []
    for b in builds:
        key = tuple((x["kind"], x.get("listing_id") or x["name"]) for x in b["components"])
        if key in seen: continue
        seen.add(key); unique.append(b)
    builds = unique
    builds.sort(key=lambda b: (b["status"] != "READY_TO_BUY", -b["utility"] / max(b["total_price"], 1), b["total_price"]))

    donors = []
    for r in (doc.get("ranked") or [])[:20]:
        if str(r.get("form_factor") or "").upper() != "DESKTOP": continue
        donors.append({
            "status": "DONOR_SPECS_REQUIRED",
            "price": r.get("ask_t1"), "cpu": r.get("cpu"), "gpu": r.get("gpu"), "url": r.get("url"), "listing_id": r.get("listing_id"),
            "reason": "Excellent price may make this the cheapest source of several parts, but exact motherboard/GPU/PSU/cooler SKUs must be proven before a Z20 transfer recommendation.",
        })

    doc["model_version"] = "DBA-WOW-Z20-WHOLE-BUILD-V12"
    doc["whole_build_optimizer"] = {
        "policy": "Rank complete end-to-end Z20 systems, not isolated deals. READY_TO_BUY requires a compatible upgradeable platform, non-defective parts, exact GPU SKU fit and fresh new-part baseline. Unknown fit is retained as a lead, never promoted as compatible.",
        "retail_baselines": RETAIL,
        "retail_baselines_fresh": retail_fresh(),
        "ready_build_count": sum(b["status"] == "READY_TO_BUY" for b in builds),
        "builds": builds[:30],
        "donor_candidates": donors,
    }
    INPUT.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# DBA WoW / Jonsbo Z20 — WHOLE-BUILD OPTIMIZER V12", "",
        f"Generated: {doc.get('generated_at')}",
        "Target: cheapest strong WoW Classic/progression system for 3840×1600 / 75 Hz that physically fits Jonsbo Z20 and preserves a sensible upgrade path.", "",
        "## Complete Z20 configurations", "",
        "| # | Status | Total | CPU | GPU | Upgrade | Fit | Components |", "|---:|---|---:|---|---|---|---|---|",
    ]
    for i, b in enumerate(builds[:10], 1):
        comps = "; ".join(f"[{x['name']}]({x['url']}) {x['price']} kr." for x in b["components"])
        lines.append(f"| {i} | {b['status']} | {b['total_price']} kr. | {b['cpu']} | {b['gpu']} | {b['upgradeability']} | {b['z20_fit']} | {comps} |")
    if not builds:
        lines.append("| - | NO COMPLETE BUILD YET | - | - | - | - | - | No combination currently satisfies all required evidence and component coverage. |")

    lines += ["", "## Complete-PC donor candidates — not approved for Z20 transfer until exact parts are proven", "", "| # | ASK | CPU | GPU | DBA |", "|---:|---:|---|---|---|"]
    for i, r in enumerate(donors[:10], 1):
        lines.append(f"| {i} | {r['price']} kr. | {r['cpu']} | {r['gpu']} | [DBA {r['listing_id']}]({r['url']}) |")
    lines += ["", "## Safety rules", "", "- ATX motherboard: hard reject for Z20.", "- Unknown motherboard form factor: never treated as compatible.", "- Exact GPU partner model/dimensions required before READY_TO_BUY.", "- New PSU and boot SSD are preferred baselines unless used condition/health is documented strongly enough to justify the risk.", "- GOOD/EXCELLENT upgrade path is required for recommended platform builds; legacy dead-end platforms remain price references only."]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"model": doc["model_version"], "ready_builds": doc["whole_build_optimizer"]["ready_build_count"], "builds": len(builds), "donors": len(donors)}))


if __name__ == "__main__":
    main()
