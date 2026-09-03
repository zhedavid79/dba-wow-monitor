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
    gpu = min(float(r.get("gpu_score") or 0), 75.0); cpu = min(float(r.get("cpu_score") or 0), 80.0)
    return round(0.55 * gpu + 0.45 * cpu, 2)


def platform_value(r: dict) -> tuple[str, int]:
    form = str(r.get("form_factor") or "").upper()
    if form == "DESKTOP": return "Z20_DONOR_CHECK_REQUIRED", 1
    if form == "LAPTOP": return "NOT_Z20_DONOR", 0
    return "UNKNOWN", 0


def annotate(rows: list[dict]) -> None:
    for r in rows:
        old = r.pop("performance_class", None) or r.get("hardware_band_legacy")
        r["hardware_band_legacy"] = old; r["use_case_utility"] = utility(r)
        r["performance_status"] = "SUFFICIENT" if old != "UNDER MINIMUM" else "INSUFFICIENT"
        r["platform_value"], r["platform_tiebreak"] = platform_value(r)
    sufficient = [r for r in rows if r["performance_status"] == "SUFFICIENT"]
    if not sufficient: return
    cheapest = min(r["ask_t1"] for r in sufficient); ceiling = min(cheapest + VALUE_PREMIUM_DKK, round(cheapest * VALUE_PREMIUM_RATIO))
    best = -1.0
    for r in sorted(sufficient, key=lambda x: (x["ask_t1"], -x["use_case_utility"])):
        dominated = r["use_case_utility"] <= best; r["value_dominated"] = dominated; best = max(best, r["use_case_utility"])
        r["value_class"] = "SWEET SPOT" if r["ask_t1"] <= ceiling and not dominated else ("GOOD VALUE" if r["ask_t1"] <= ceiling else "EXCESS SPEND FOR THIS USE CASE")
        r["sweet_spot_price_ceiling"] = ceiling


def part_efficiency(r: dict) -> float:
    price = max(int(r.get("ask_t1") or 1), 1); kind = r.get("kind")
    raw = 1000 * float(r.get("gpu_score") if kind == "GPU" else r.get("cpu_score") if kind in {"CPU", "PLATFORM_BUNDLE"} else 0) / price
    if r.get("condition") == "DEFECT_DISCLOSED": return 0.0
    if kind == "PLATFORM_BUNDLE":
        if r.get("z20_fit") != "COMPATIBLE": return 0.0
        raw *= {"EXCELLENT": 1.25, "GOOD": 1.15, "LIMITED": .75, "POOR": .45, "UNVERIFIED": .6}.get(r.get("upgradeability"), .6)
    return round(raw, 3)


def main() -> None:
    d = json.loads(INPUT.read_text(encoding="utf-8")); rows = d.get("ranked") or []
    annotate(rows); rows.sort(key=lambda r: (r["ask_t1"], -r["use_case_utility"], -r["platform_tiebreak"]))
    parts_doc = json.loads(PARTS.read_text(encoding="utf-8")) if PARTS.exists() else {"opportunities": []}; parts = parts_doc.get("opportunities") or []
    for r in parts:
        r["value_efficiency"] = part_efficiency(r)
        r["build_eligible"] = r.get("condition") != "DEFECT_DISCLOSED" and (r.get("kind") != "PLATFORM_BUNDLE" or r.get("z20_fit") == "COMPATIBLE")
    parts.sort(key=lambda r: (not r["build_eligible"], -r["value_efficiency"], r["ask_t1"]))

    d["model_version"] = "DBA-WOW-Z20-UPGRADEABLE-V11"
    d["target_case"] = {"model": "Jonsbo Z20", "motherboard": ["Micro-ATX", "Mini-ITX"], "gpu_max_mm": 363, "cpu_cooler_max_mm_intel": 164, "cpu_cooler_max_mm_amd": 163, "psu": ["ATX", "SFX", "SFX-L"], "atx_psu_recommended_max_mm": 140, "rule": "No platform bundle is build-eligible without explicit Micro-ATX/Mini-ITX evidence. Exact GPU/PSU/cooler dimensions remain required before final assembly."}
    d["ranking_policy"] = "V11 prioritizes a physically Z20-compatible and continuously upgradeable platform. Complete PCs remain a price safety net, but donor status is not equivalent to verified fit. Platform bundles with ATX or unknown motherboard form factor cannot become build recommendations."
    d["parts_scan"] = {"model_version": parts_doc.get("model_version"), "counts": parts_doc.get("counts"), "opportunities": parts}
    d["value_model"] = {"target": "WoW Classic/progression, 3840x1600, up to 75 Hz in Jonsbo Z20 with future upgrades", "platform_priority": "AM5 preferred; AM4/B550 and LGA1700 viable value paths; legacy LGA1151 is penalized; unknown motherboard fit is never accepted", "cheapest_verified_sufficient": min((r["ask_t1"] for r in rows), default=None)}
    INPUT.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

    eligible = [r for r in parts if r["build_eligible"]]
    lines = ["# DBA WoW / Jonsbo Z20 — UPGRADEABLE VALUE REPORT V11", "", f"Generated: {d.get('generated_at')}", "Target: WoW Classic/progression at 3840×1600 / 75 Hz, physically compatible with Jonsbo Z20 and suitable for ongoing upgrades.", "", "## Z20 build-eligible parts / bundles", "", "| Type | ASK | GPU | CPU | Z20 fit | Upgrade path | Efficiency | DBA |", "|---|---:|---|---|---|---|---:|---|"]
    for r in eligible[:20]: lines.append(f"| {r['kind']} | {r['ask_t1']} kr. | {r['gpu']} | {r['cpu']} | {r.get('z20_fit')} | {r.get('upgradeability')} | {r['value_efficiency']} | [{r['title']}]({r['url']}) |")
    lines += ["", "## Top 10 complete-PC safety net — fit still requires verification", "", "| # | T1 ASK | Value | GPU | CPU | Z20 | ID | DBA |", "|---:|---:|---|---|---|---|---|---|"]
    for i, r in enumerate(rows[:TOP_N], 1): lines.append(f"| {i} | {r['ask_t1']} kr. | {r['value_class']} | {r['gpu']} | {r['cpu']} | {r['platform_value']} | {r['listing_id']} | [{r['title']}]({r['url']}) |")
    lines += ["", "## Rejected / not build-eligible examples", ""]
    for r in [x for x in parts if not x["build_eligible"]][:20]: lines.append(f"- [{r['title']}]({r['url']}) — {r['ask_t1']} kr. — Z20={r.get('z20_fit')} / upgrade={r.get('upgradeability')} / condition={r.get('condition')}")
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")

if __name__ == "__main__": main()
