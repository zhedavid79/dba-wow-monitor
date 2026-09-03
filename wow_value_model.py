from __future__ import annotations

import json
from pathlib import Path

INPUT = Path("results/wow_a3_latest.json")
PARTS = Path("results/z20_parts_latest.json")
REPORT = Path("results/wow_a3_report.md")
VALUE_PREMIUM_DKK = 1000
VALUE_PREMIUM_RATIO = 1.25
TOP_N = 10


def utility(r: dict) -> float:
    gpu = min(float(r.get("gpu_score") or 0), 75.0)
    cpu = min(float(r.get("cpu_score") or 0), 80.0)
    return round(0.55 * gpu + 0.45 * cpu, 2)


def platform_value(r: dict) -> tuple[str, int]:
    form = str(r.get("form_factor") or "").upper()
    if form == "DESKTOP": return "Z20_DONOR_CHECK_REQUIRED", 1
    if form == "LAPTOP": return "NOT_Z20_DONOR", 0
    return "UNKNOWN", 0


def annotate(rows: list[dict]) -> None:
    for r in rows:
        old = r.pop("performance_class", None) or r.get("hardware_band_legacy")
        r["hardware_band_legacy"] = old
        r["use_case_utility"] = utility(r)
        r["performance_status"] = "SUFFICIENT" if old != "UNDER MINIMUM" else "INSUFFICIENT"
        r["platform_value"], r["platform_tiebreak"] = platform_value(r)
    sufficient = [r for r in rows if r["performance_status"] == "SUFFICIENT"]
    if not sufficient: return
    cheapest = min(r["ask_t1"] for r in sufficient)
    ceiling = min(cheapest + VALUE_PREMIUM_DKK, round(cheapest * VALUE_PREMIUM_RATIO))
    best = -1.0
    for r in sorted(sufficient, key=lambda x: (x["ask_t1"], -x["use_case_utility"])):
        dominated = r["use_case_utility"] <= best
        r["value_dominated"] = dominated
        best = max(best, r["use_case_utility"])
        r["value_class"] = "SWEET SPOT" if r["ask_t1"] <= ceiling and not dominated else ("GOOD VALUE" if r["ask_t1"] <= ceiling else "EXCESS SPEND FOR THIS USE CASE")
        r["sweet_spot_price_ceiling"] = ceiling


def part_efficiency(r: dict) -> float:
    price = max(int(r.get("ask_t1") or 1), 1)
    kind = r.get("kind")
    if kind == "GPU": return round(1000 * float(r.get("gpu_score") or 0) / price, 3)
    if kind in {"CPU", "PLATFORM_BUNDLE"}: return round(1000 * float(r.get("cpu_score") or 0) / price, 3)
    return 0.0


def main() -> None:
    d = json.loads(INPUT.read_text(encoding="utf-8"))
    rows = d.get("ranked") or []
    annotate(rows)
    rows.sort(key=lambda r: (r["ask_t1"], -r["use_case_utility"], -r["platform_tiebreak"]))

    parts_doc = json.loads(PARTS.read_text(encoding="utf-8")) if PARTS.exists() else {"opportunities": []}
    parts = parts_doc.get("opportunities") or []
    for r in parts: r["value_efficiency"] = part_efficiency(r)
    parts.sort(key=lambda r: (-r["value_efficiency"], r["ask_t1"]))

    d["model_version"] = "DBA-WOW-Z20-HYBRID-V10"
    d["target_case"] = {
        "model": "Jonsbo Z20", "motherboard": ["Micro-ATX", "Mini-ITX"], "gpu_max_mm": 363,
        "cpu_cooler_max_mm_intel": 164, "cpu_cooler_max_mm_amd": 163,
        "psu": ["ATX", "SFX", "SFX-L"], "atx_psu_recommended_max_mm": 140,
        "rule": "Exact fit requires concrete component dimensions; unknown fit never silently becomes compatible."
    }
    d["ranking_policy"] = "Hybrid Z20 procurement: retain price-first complete-PC safety net while scanning live DBA GPU, CPU, platform-bundle, RAM and PSU opportunities. Prefer donor/bundle/part route only when evidence supports it; never invent compatibility."
    d["parts_scan"] = {"model_version": parts_doc.get("model_version"), "counts": parts_doc.get("counts"), "opportunities": parts}
    d["value_model"] = {
        "target": "WoW Classic/progression, 3840x1600, up to 75 Hz in Jonsbo Z20",
        "utility": "55% capped GPU score + 45% capped CPU score; not an FPS estimate",
        "sweet_spot_rule": "non-dominated sufficient complete PC within min(cheapest+1000 DKK, cheapest*1.25)",
        "component_rule": "compare live verified component/bundle opportunities by score per DKK; compatibility must be evidenced before a combined build is declared valid",
        "cheapest_verified_sufficient": min((r["ask_t1"] for r in rows), default=None),
        "sweet_spot_price_ceiling": rows[0].get("sweet_spot_price_ceiling") if rows else None,
    }
    INPUT.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = ["# DBA WoW / Jonsbo Z20 — HYBRID VALUE REPORT V10", "", f"Generated: {d.get('generated_at')}",
             "Target: WoW Classic/progression at 3840×1600 / up to 75 Hz in Jonsbo Z20.",
             "Strategy: compare complete donor PCs with live DBA components/bundles; never infer missing compatibility.", "",
             "## Top 10 complete-PC safety net", "", "| # | T1 ASK | Value | GPU | CPU | Z20 | ID | DBA |", "|---:|---:|---|---|---|---|---|---|"]
    for i, r in enumerate(rows[:TOP_N], 1):
        lines.append(f"| {i} | {r['ask_t1']} kr. | {r['value_class']} | {r['gpu']} | {r['cpu']} | {r['platform_value']} | {r['listing_id']} | [{r['title']}]({r['url']}) |")
    lines += ["", "## Z20 parts / bundle opportunities", "", "| Type | ASK | GPU | CPU | Efficiency | DBA |", "|---|---:|---|---|---:|---|"]
    for r in parts[:20]:
        lines.append(f"| {r['kind']} | {r['ask_t1']} kr. | {r['gpu']} | {r['cpu']} | {r['value_efficiency']} | [{r['title']}]({r['url']}) |")
    lines += ["", "## Potential bargains needing spec resolution", ""]
    for r in d.get("potential_sweet_spots_unresolved") or []:
        lines.append(f"- [{r['title']}]({r['url']}) — {r['ask_t1']} kr. — {r['resolution_reason']} — ID {r['listing_id']}")
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__": main()
