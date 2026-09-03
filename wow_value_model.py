from __future__ import annotations

import json
from pathlib import Path

INPUT = Path("results/wow_a3_latest.json")
REPORT = Path("results/wow_a3_report.md")

# Procurement target: WoW Classic/progression at 3840x1600, display capped at 75 Hz.
# Hardware performance and purchase value are deliberately separate concepts.
# A faster PC is not a better buy once the use-case performance floor is cleared.
VALUE_PREMIUM_DKK = 1000
VALUE_PREMIUM_RATIO = 1.25


def utility(r: dict) -> float:
    """Conservative use-case utility, not an FPS estimate.

    CPU gets extra weight because WoW's crowded/raid workloads are commonly CPU-sensitive;
    GPU remains material at 3840x1600. Scores are capped so excess hardware above the
    75-Hz use case has sharply diminishing procurement value.
    """
    gpu = min(float(r.get("gpu_score") or 0), 75.0)
    cpu = min(float(r.get("cpu_score") or 0), 80.0)
    return round(0.55 * gpu + 0.45 * cpu, 2)


def annotate(rows: list[dict]) -> None:
    if not rows:
        return
    for r in rows:
        # Preserve the old hardware-only label for diagnostics, but never call it sweet spot.
        old = r.pop("performance_class", None)
        r["hardware_band_legacy"] = old
        r["use_case_utility"] = utility(r)
        r["performance_status"] = "SUFFICIENT" if old != "UNDER MINIMUM" else "INSUFFICIENT"

    sufficient = [r for r in rows if r["performance_status"] == "SUFFICIENT"]
    if not sufficient:
        return
    cheapest = min(r["ask_t1"] for r in sufficient)
    sweet_ceiling = min(cheapest + VALUE_PREMIUM_DKK, round(cheapest * VALUE_PREMIUM_RATIO))

    # Value frontier: a row is dominated when a cheaper/equal candidate has equal/higher
    # capped use-case utility. This prevents expensive overkill being labelled a sweet spot.
    best_utility = -1.0
    for r in sorted(sufficient, key=lambda x: (x["ask_t1"], -x["use_case_utility"])):
        dominated = r["use_case_utility"] <= best_utility
        r["value_dominated"] = dominated
        if not dominated:
            best_utility = r["use_case_utility"]
        if r["ask_t1"] <= sweet_ceiling and not dominated:
            r["value_class"] = "SWEET SPOT"
        elif r["ask_t1"] <= sweet_ceiling:
            r["value_class"] = "GOOD VALUE"
        else:
            r["value_class"] = "EXCESS SPEND FOR THIS USE CASE"
        r["sweet_spot_price_ceiling"] = sweet_ceiling


def main() -> None:
    d = json.loads(INPUT.read_text(encoding="utf-8"))
    rows = d.get("ranked") or []
    annotate(rows)
    rows.sort(key=lambda r: (r["ask_t1"], -r["use_case_utility"]))

    d["model_version"] = "DBA-WOW-VALUE-AWARE-V8"
    d["ranking_policy"] = (
        "Price-first procurement for WoW at 3840x1600/75 Hz. Performance sufficiency and economic value are separate. "
        "SWEET SPOT is reserved for non-dominated sufficient systems close to the cheapest verified sufficient price; "
        "expensive excess performance is explicitly marked as excess spend."
    )
    d["value_model"] = {
        "target": "WoW Classic/progression, 3840x1600, up to 75 Hz",
        "utility": "55% capped GPU score + 45% capped CPU score; deliberately not an FPS estimate",
        "sweet_spot_rule": "non-dominated sufficient candidate within min(cheapest+1000 DKK, cheapest*1.25)",
        "cheapest_verified_sufficient": min((r["ask_t1"] for r in rows), default=None),
        "sweet_spot_price_ceiling": rows[0].get("sweet_spot_price_ceiling") if rows else None,
    }
    INPUT.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# FULDT PÅLIDELIG DBA-PRISRAPPORT — WoW 3840×1600 / 75 Hz",
        "",
        f"Generated: {d.get('generated_at')}",
        f"Retrieval: {d.get('retrieval_method')}",
        "Value model: performance sufficiency and purchase value are separate; SWEET SPOT is price-relative, not a hardware tier.",
        "",
        "## Ranked shortlist — price first",
        "",
        "| # | T1 ASK | Value | Performance | GPU | CPU | ID | DBA |",
        "|---:|---:|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(rows, 1):
        lines.append(
            f"| {i} | {r['ask_t1']} kr. | {r['value_class']} | {r['performance_status']} | "
            f"{r['gpu']} | {r['cpu']} | {r['listing_id']} | [{r['title']}]({r['url']}) |"
        )
    lines += ["", "## POTENTIAL BARGAINS — NEEDS SPEC RESOLUTION", ""]
    for r in d.get("potential_sweet_spots_unresolved") or []:
        lines.append(f"- [{r['title']}]({r['url']}) — {r['ask_t1']} kr. — {r['resolution_reason']} — ID {r['listing_id']}")
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
