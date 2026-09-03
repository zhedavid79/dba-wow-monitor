from __future__ import annotations

import json
from pathlib import Path

INPUT = Path("results/wow_a3_latest.json")
REPORT = Path("results/wow_a3_report.md")

# Procurement target: WoW Classic/progression at 3840x1600, display capped at 75 Hz.
# Inspired by value-first compact PC building: buy enough gaming performance cheaply,
# then prefer reusable/upgradeable standard components when that evidence is available.
# Unknown platform details must never hide an otherwise strong bargain.
VALUE_PREMIUM_DKK = 1000
VALUE_PREMIUM_RATIO = 1.25
TOP_N = 10


def utility(r: dict) -> float:
    """Conservative use-case utility, not an FPS estimate."""
    gpu = min(float(r.get("gpu_score") or 0), 75.0)
    cpu = min(float(r.get("cpu_score") or 0), 80.0)
    return round(0.55 * gpu + 0.45 * cpu, 2)


def platform_value(r: dict) -> tuple[str, int]:
    """Secondary procurement signal only; never infer missing hardware.

    The browser scanner currently proves form factor only coarsely. Preserve high recall:
    DESKTOP is potentially reusable, LAPTOP is not an A3 donor, and anything unknown stays
    UNKNOWN rather than being penalised or guessed.
    """
    form = str(r.get("form_factor") or "").upper()
    if form == "DESKTOP":
        return "POTENTIAL_DONOR_CHECK_REQUIRED", 1
    if form == "LAPTOP":
        return "NOT_A3_DONOR", 0
    return "UNKNOWN", 0


def annotate(rows: list[dict]) -> None:
    if not rows:
        return
    for r in rows:
        old = r.pop("performance_class", None)
        if old is None:
            old = r.get("hardware_band_legacy")
        r["hardware_band_legacy"] = old
        r["use_case_utility"] = utility(r)
        r["performance_status"] = "SUFFICIENT" if old != "UNDER MINIMUM" else "INSUFFICIENT"
        label, score = platform_value(r)
        r["platform_value"] = label
        r["platform_tiebreak"] = score

    sufficient = [r for r in rows if r["performance_status"] == "SUFFICIENT"]
    if not sufficient:
        return
    cheapest = min(r["ask_t1"] for r in sufficient)
    sweet_ceiling = min(cheapest + VALUE_PREMIUM_DKK, round(cheapest * VALUE_PREMIUM_RATIO))

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

    # Price and WoW utility remain primary. Platform reuse is only a tie-breaker so an
    # unknown motherboard/PSU can never make a cheap bargain disappear.
    rows.sort(key=lambda r: (r["ask_t1"], -r["use_case_utility"], -r["platform_tiebreak"]))

    d["model_version"] = "DBA-WOW-VALUE-AWARE-V9"
    d["ranking_policy"] = (
        "Price-first procurement for WoW at 3840x1600/75 Hz. Performance sufficiency and economic value are separate. "
        "Standard/reusable platform evidence is a secondary tie-breaker only; unknown A3 compatibility never excludes a bargain."
    )
    d["value_model"] = {
        "target": "WoW Classic/progression, 3840x1600, up to 75 Hz",
        "utility": "55% capped GPU score + 45% capped CPU score; deliberately not an FPS estimate",
        "sweet_spot_rule": "non-dominated sufficient candidate within min(cheapest+1000 DKK, cheapest*1.25)",
        "platform_rule": "prefer reusable/upgradeable desktop platform only as a secondary tie-breaker; never infer exact compatibility",
        "cheapest_verified_sufficient": min((r["ask_t1"] for r in rows), default=None),
        "sweet_spot_price_ceiling": rows[0].get("sweet_spot_price_ceiling") if rows else None,
    }
    INPUT.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# DBA WoW-PC — TOP 10 VALUE RANKING",
        "",
        f"Generated: {d.get('generated_at')}",
        f"Retrieval: {d.get('retrieval_method')}",
        "Target: WoW Classic/progression at 3840×1600 / up to 75 Hz.",
        "Platform/A3 suitability is secondary and never guessed; unknown compatibility does not remove bargains.",
        "",
        "## Top 10 — price first",
        "",
        "| # | T1 ASK | Value | GPU | CPU | Platform | ID | DBA |",
        "|---:|---:|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(rows[:TOP_N], 1):
        lines.append(
            f"| {i} | {r['ask_t1']} kr. | {r['value_class']} | {r['gpu']} | {r['cpu']} | "
            f"{r['platform_value']} | {r['listing_id']} | [{r['title']}]({r['url']}) |"
        )
    lines += ["", "## POTENTIAL BARGAINS — NEEDS SPEC RESOLUTION", ""]
    for r in d.get("potential_sweet_spots_unresolved") or []:
        lines.append(f"- [{r['title']}]({r['url']}) — {r['ask_t1']} kr. — {r['resolution_reason']} — ID {r['listing_id']}")
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
