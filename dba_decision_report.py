from __future__ import annotations

import json
import statistics
from pathlib import Path

MAIN = Path("results/wow_a3_latest.json")
REPORT = Path("results/wow_a3_report.md")
TOP_N = 15


def evidence_value(row: dict, key: str, fallback: str = "Ukendt") -> str:
    x = (row.get("listing_intelligence") or {}).get(key) or {}
    return str(x.get("value") or fallback)


def evidence_confidence(row: dict, key: str) -> str:
    x = (row.get("listing_intelligence") or {}).get(key) or {}
    return str(x.get("confidence") or "UNKNOWN")


def scenario(row: dict) -> str:
    cpu = int(row.get("cpu_score") or 0)
    gpu = int(row.get("gpu_score") or 0)
    if cpu >= 90 and gpu >= 60:
        return "Quest/open world og dungeons: stærk margin mod 75 Hz; raids: stærk; worst-case crowded combat: primært CPU-begrænset, men med god margin."
    if cpu >= 65 and gpu >= 65:
        return "Quest/open world og dungeons: typisk omkring 75 Hz-målet; raids: god; worst-case crowded combat: CPU kan give mærkbare dyk."
    if cpu >= 59 and gpu >= 55:
        return "Quest/open world: god; dungeons: god; raids: acceptabel-god; worst-case crowded combat: tydelige CPU-dyk under 75 Hz må forventes."
    return "Består minimumsgaten, men evidensen understøtter ikke en skarpere konservativ scenarieklassifikation."


def short_specs(row: dict) -> str:
    cpu = evidence_value(row, "cpu", row.get("cpu") or "Ukendt")
    gpu = evidence_value(row, "gpu", row.get("gpu") or "Ukendt")
    ram = evidence_value(row, "ram")
    storage = (row.get("listing_intelligence") or {}).get("storage") or []
    storage_text = ", ".join(str(x.get("value")) for x in storage if x.get("value")) or "Ukendt"
    return f"CPU {cpu}; GPU {gpu}; RAM {ram}; lager {storage_text}"


def fair_value_proxy(row: dict, ranked: list[dict]) -> int | None:
    """Current-live cohort proxy, never a replacement for ASK.

    Requires at least three other verified complete PCs with approximately the same
    CPU/GPU performance band. This intentionally avoids pretending that a single ASK
    is independent market-value evidence.
    """
    gpu = int(row.get("gpu_score") or 0)
    cpu = int(row.get("cpu_score") or 0)
    comps = [
        int(x["ask_t1"])
        for x in ranked
        if x.get("listing_id") != row.get("listing_id")
        and isinstance(x.get("ask_t1"), int)
        and abs(int(x.get("gpu_score") or 0) - gpu) <= 6
        and abs(int(x.get("cpu_score") or 0) - cpu) <= 12
    ]
    if len(comps) < 3:
        return None
    return int(round(statistics.median(comps) / 50.0) * 50)


def bid_model(row: dict, ranked: list[dict]) -> dict:
    ask = int(row["ask_t1"])
    fair = fair_value_proxy(row, ranked)
    anchor = min(ask, fair) if fair else ask
    start = max(100, int(round(anchor * 0.82 / 50.0) * 50))
    target = max(start, int(round(anchor * 0.90 / 50.0) * 50))
    hard_max = min(ask, fair) if fair else ask
    good_deal = int(round(fair * 0.90 / 50.0) * 50) if fair else None
    return {
        "fair_value_proxy": fair,
        "good_deal": good_deal,
        "start_bid": start,
        "target": target,
        "hard_max": hard_max,
        "method": "Live verified same-run cohort median" if fair else "ASK-relative negotiation only; insufficient same-band live comps for fair-value proxy",
    }


def choose_best_bidcase(ranked: list[dict]) -> dict | None:
    if not ranked:
        return None
    with_models = [(r, bid_model(r, ranked)) for r in ranked]
    with_fair = [(r, b) for r, b in with_models if b["fair_value_proxy"] is not None]
    if with_fair:
        return max(with_fair, key=lambda rb: (rb[1]["fair_value_proxy"] - int(rb[0]["ask_t1"]), -int(rb[0]["ask_t1"])))[0]
    return ranked[0]


def main() -> None:
    d = json.loads(MAIN.read_text(encoding="utf-8"))
    if d.get("gate_passed") is not True:
        raise SystemExit("PRICE DATA GATE FAILED — report generation requires a passed source gate")

    ranked = d.get("ranked") or []
    unresolved = d.get("potential_sweet_spots_unresolved") or []
    rejected = d.get("rejected") or []

    if any(not r.get("listing_intelligence") for r in ranked):
        raise SystemExit("PUBLICATION GATE FAILED — ranked record lacks listing intelligence")

    buy_now = ranked[0] if ranked else None
    cheapest_sufficient = ranked[0] if ranked else None
    best_bid = choose_best_bidcase(ranked)

    for r in ranked:
        r["bid_model"] = bid_model(r, ranked)

    d["decision_summary"] = {
        "policy": "Complete ready-to-use PCs only. Price-first among candidates that pass live T0/T1 identity, status, price and WoW performance gates.",
        "buy_now_listing_id": buy_now.get("listing_id") if buy_now else None,
        "cheapest_sufficient_listing_id": cheapest_sufficient.get("listing_id") if cheapest_sufficient else None,
        "best_bidcase_listing_id": best_bid.get("listing_id") if best_bid else None,
        "self_build": False,
        "donor_builds": False,
        "component_procurement": False,
    }
    MAIN.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

    cov = d.get("coverage") or {}
    dcov = cov.get("discovery") or {}
    tcov = cov.get("t1") or {}
    source_gate = d.get("source_gate") or {}

    lines = [
        "# FULDT PÅLIDELIG DBA-PRISRAPPORT — WoW Classic/Cataclysm",
        "",
        f"Dato/tid: {d.get('generated_at')}",
        f"Data source / retrieval: {d.get('retrieval_method')}",
        f"Struktureret discovery: {dcov.get('query_completed')}/{dcov.get('query_total')} søgninger; T1: {tcov.get('candidate_completed')}/{tcov.get('candidate_total')} kandidater.",
        f"Same-object source gate: listing {source_gate.get('listing_id')} — T0 {source_gate.get('t0_source')} / T1 {source_gate.get('t1_source')}.",
        f"Antal struktureret verificerede og rangerede annoncer: {len(ranked)}.",
        "Scope: komplette brugsklare stationære gaming-PC'er, gaming laptops og mini-PC'er. Ingen byg-selv, donor-builds eller komponentjagt.",
        "",
    ]

    if buy_now:
        lines += [
            "## Buy now",
            "",
            f"[{buy_now['title']}]({buy_now['url']}) — **T1 ASK {buy_now['ask_t1']} kr.** — {buy_now['performance_class']} — ID `{buy_now['listing_id']}`",
            f"{short_specs(buy_now)}. {scenario(buy_now)}",
            "",
            "## Billigste tilstrækkelige",
            "",
            f"[{cheapest_sufficient['title']}]({cheapest_sufficient['url']}) — **{cheapest_sufficient['ask_t1']} kr.** — {cheapest_sufficient['performance_class']} — ID `{cheapest_sufficient['listing_id']}`",
            "",
        ]
    else:
        lines += ["## Buy now", "", "Ingen kandidat bestod performance- og datagates.", ""]

    if best_bid:
        b = best_bid["bid_model"]
        fair = f"{b['fair_value_proxy']} kr." if b["fair_value_proxy"] is not None else "ikke estimeret (for få live same-band comps)"
        good = f"{b['good_deal']} kr." if b["good_deal"] is not None else "ikke estimeret"
        lines += [
            "## Bedste budcase",
            "",
            f"[{best_bid['title']}]({best_bid['url']}) — **ASK {best_bid['ask_t1']} kr.** — ID `{best_bid['listing_id']}`",
            f"Fair-value proxy: {fair}; good-deal niveau: {good}; startbud: **{b['start_bid']} kr.**; target: **{b['target']} kr.**; hard max: **{b['hard_max']} kr.**.",
            f"Metode: {b['method']}.",
            "",
        ]

    lines += [
        "## Ranked shortlist — pris først",
        "",
        "| # | T1 ASK | PC / direkte DBA-link | Listing ID | Specs | Klasse | Rationale |",
        "|---:|---:|---|---|---|---|---|",
    ]
    for i, r in enumerate(ranked[:TOP_N], 1):
        lines.append(
            f"| {i} | {r['ask_t1']} kr. | [{r['title']}]({r['url']}) | {r['listing_id']} | {short_specs(r)} | {r['performance_class']} | {scenario(r)} |"
        )

    lines += ["", "## Evidensmatrix", "", "| PC | CPU-evidens | GPU-evidens | RAM | T0→T1 pris | Status |", "|---|---|---|---|---|---|"]
    for r in ranked[:TOP_N]:
        intel = r.get("listing_intelligence") or {}
        cpu = intel.get("cpu") or {}
        gpu = intel.get("gpu") or {}
        ram = intel.get("ram") or {}
        price = f"{r.get('ask_t0')}→{r.get('ask_t1')} kr." + (" (ændret)" if r.get("price_changed") else "")
        lines.append(
            f"| [{r['title']}]({r['url']}) | {cpu.get('value') or 'Ukendt'} / {cpu.get('confidence','UNKNOWN')} | {gpu.get('value') or 'Ukendt'} / {gpu.get('confidence','UNKNOWN')} | {ram.get('value') or 'Ukendt'} | {price} | {r.get('status')} |"
        )

    lines += ["", "## WoW-scenarier", ""]
    for r in ranked[:min(8, TOP_N)]:
        lines.append(f"- [{r['title']}]({r['url']}) — **{r['performance_class']}**: {scenario(r)}")

    lines += ["", "## Budmodel", "", "ASK er altid den live T1-verificerede DBA-pris. Estimaterne nedenfor er separate og ændrer aldrig ASK.", "", "| PC | ASK | Fair-value proxy | Good deal | Startbud | Target | Hard max |", "|---|---:|---:|---:|---:|---:|---:|"]
    for r in ranked[:min(8, TOP_N)]:
        b = r["bid_model"]
        fair = f"{b['fair_value_proxy']} kr." if b["fair_value_proxy"] is not None else "—"
        good = f"{b['good_deal']} kr." if b["good_deal"] is not None else "—"
        lines.append(f"| [{r['title']}]({r['url']}) | {r['ask_t1']} kr. | {fair} | {good} | {b['start_bid']} kr. | {b['target']} kr. | {b['hard_max']} kr. |")

    lines += ["", "## Leads — ikke rangeret", ""]
    if unresolved:
        for r in unresolved[:20]:
            lines.append(f"- [{r['title']}]({r['url']}) — ID `{r['listing_id']}` — {r.get('resolution_reason','SPEC_EVIDENCE_UNRESOLVED')}. Ikke med i prisrankingen.")
    else:
        lines.append("Ingen uafklarede complete-PC leads i denne kørsel.")

    lines += ["", "## Objektive diskvalifikationer", ""]
    reason_counts = d.get("rejection_reason_counts") or {}
    if reason_counts:
        for reason, count in sorted(reason_counts.items(), key=lambda x: (-x[1], x[0])):
            lines.append(f"- {reason}: {count}")
    else:
        lines.append("Ingen objektive diskvalifikationer registreret.")

    lines += ["", "## Konklusion", ""]
    if buy_now:
        lines.append(f"Pris-først-valget er [{buy_now['title']}]({buy_now['url']}) til **{buy_now['ask_t1']} kr.**, fordi den er den billigste live T1-verificerede komplette PC, der består WoW-performancegaten.")
    else:
        lines.append("Ingen verificeret komplet PC bestod alle gates i denne kørsel; derfor gives ingen købskandidat.")

    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"decision_report": True, "ranked": len(ranked), "buy_now": buy_now.get("listing_id") if buy_now else None, "best_bidcase": best_bid.get("listing_id") if best_bid else None}, ensure_ascii=False))


if __name__ == "__main__":
    main()
