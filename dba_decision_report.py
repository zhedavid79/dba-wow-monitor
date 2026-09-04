from __future__ import annotations

import json
from pathlib import Path

MAIN = Path("results/wow_a3_latest.json")
REPORT = Path("results/wow_a3_report.md")


def has_route(row: dict, name: str) -> bool:
    return any(x.get("route") == name for x in ((row.get("listing_intelligence") or {}).get("routes") or []))


def route_status(row: dict, name: str) -> str | None:
    x = next((x for x in ((row.get("listing_intelligence") or {}).get("routes") or []) if x.get("route") == name), None)
    return x.get("status") if x else None


def evidence_value(row: dict, key: str, fallback: str = "Ukendt") -> str:
    x = (row.get("listing_intelligence") or {}).get(key) or {}
    return str(x.get("value") or fallback)


def confidence(row: dict, key: str) -> str:
    x = (row.get("listing_intelligence") or {}).get(key) or {}
    return str(x.get("confidence") or "UNKNOWN")


def scenario(row: dict) -> str:
    intel = row.get("listing_intelligence") or {}
    cpu = int(intel.get("cpu_score") or row.get("cpu_score") or 0)
    gpu = int(intel.get("gpu_score") or row.get("gpu_score") or 0)
    if cpu >= 90 and gpu >= 60:
        return "Open world/dungeons: 75 Hz-målet stærkt; raids: stærkt; crowded combat: CPU bør stadig have god margin."
    if cpu >= 65 and gpu >= 65:
        return "Open world/dungeons: typisk 75 Hz-målet; raids: god; crowded combat: CPU kan være den primære begrænsning."
    if cpu >= 59 and gpu >= 55:
        return "Open world/dungeons: god; raids: acceptabel-god; crowded combat: forvent tydeligere CPU-dyk under 75 Hz."
    return "Ydelsen er tilstrækkelig efter hovedgaten, men annonceevidensen giver ikke grundlag for et skarpere scenarie."


def short_specs(row: dict) -> str:
    intel = row.get("listing_intelligence") or {}
    cpu = evidence_value(row, "cpu", row.get("cpu") or "Ukendt")
    gpu = evidence_value(row, "gpu", row.get("gpu") or "Ukendt")
    ram = evidence_value(row, "ram")
    board = evidence_value(row, "motherboard")
    psu = evidence_value(row, "psu")
    return f"CPU {cpu}; GPU {gpu}; RAM {ram}; board {board}; PSU {psu}"


def option_line(row: dict, label: str) -> str:
    return f"[{label}]({row['url']}) — **{row['ask_t1']} kr.** — {short_specs(row)}"


def main() -> None:
    d = json.loads(MAIN.read_text(encoding="utf-8"))
    ranked = d.get("ranked") or []
    enriched = [r for r in ranked if r.get("listing_intelligence")]
    if ranked and not enriched:
        raise SystemExit("DECISION REPORT GATE FAILED — ranked records lack listing intelligence")

    buy_now = next((r for r in ranked if has_route(r, "BUY_AND_USE_AS_IS")), None)
    direct_z20 = next((r for r in ranked if has_route(r, "DIRECT_Z20_TRANSFER")), None)
    z20_donor = next((r for r in ranked if has_route(r, "Z20_DONOR_WITH_NEW_PLATFORM")), None)
    one_question = next((r for r in ranked if has_route(r, "Z20_TRANSFER_NEEDS_BOARD_INFO") and (r.get("listing_intelligence") or {}).get("seller_question")), None)

    opt = d.get("complete_system_optimizer") or {}
    ready_builds = [b for b in (opt.get("builds") or []) if b.get("status") == "READY_TO_BUY"]
    ready_builds.sort(key=lambda b: b.get("total_price", 10**9))
    cheapest_build = ready_builds[0] if ready_builds else None
    long_term = next((b for b in ready_builds if b.get("upgradeability") == "EXCELLENT"), None)

    d["decision_summary"] = {
        "policy": "Present mutually understandable purchase routes. Listing description evidence informs hardware/fit only; T1 ASK remains the sole ranked price.",
        "buy_and_use_listing_id": buy_now.get("listing_id") if buy_now else None,
        "direct_z20_listing_id": direct_z20.get("listing_id") if direct_z20 else None,
        "z20_donor_listing_id": z20_donor.get("listing_id") if z20_donor else None,
        "one_question_listing_id": one_question.get("listing_id") if one_question else None,
        "cheapest_ready_build_total": cheapest_build.get("total_price") if cheapest_build else None,
        "long_term_ready_build_total": long_term.get("total_price") if long_term else None,
    }
    MAIN.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# FULDT PÅLIDELIG DBA-PRISRAPPORT — BESLUTNINGSUDGAVE",
        "",
        f"Generated: {d.get('generated_at')}",
        f"Live verification: {d.get('coverage',{}).get('discovery',{}).get('query_completed')}/{d.get('coverage',{}).get('discovery',{}).get('query_total')} searches; {d.get('coverage',{}).get('t1',{}).get('candidate_completed')}/{d.get('coverage',{}).get('t1',{}).get('candidate_total')} T1 candidates.",
        "Annoncebeskrivelser bruges nu til hardware-/fit-forståelse med evidens og confidence. De bruges aldrig som prisbevis.",
        "",
        "## Dine muligheder — først",
        "",
    ]

    if buy_now:
        lines += ["### 1. Billigste køb-og-spil-nu", "", option_line(buy_now, buy_now["title"]), "", scenario(buy_now), ""]
    else:
        lines += ["### 1. Billigste køb-og-spil-nu", "", "Ingen verificeret kandidat.", ""]

    lines += ["### 2. Direkte flytning til Jonsbo Z20", ""]
    if direct_z20:
        intel = direct_z20["listing_intelligence"]
        lines += [option_line(direct_z20, direct_z20["title"]), "", f"Board fit: **{intel['motherboard_z20_fit']['value']}** ({intel['motherboard_z20_fit']['confidence']}). Route status: **{route_status(direct_z20,'DIRECT_Z20_TRANSFER')}**.", ""]
    else:
        lines += ["Ingen komplet PC har endnu annoncebevist mATX/ITX + tilstrækkelig evidens til at være en direkte transfer-route.", ""]

    lines += ["### 3. Bedste donor / køb og genbrug", ""]
    donor_pick = z20_donor or one_question
    if donor_pick:
        intel = donor_pick["listing_intelligence"]
        lines += [option_line(donor_pick, donor_pick["title"]), "", "Mulige genbrugsdele vurderes fra den konkrete beskrivelse. Modellen gør ikke ukendt hardware til bevist kompatibilitet.", ""]
        if intel.get("seller_question"):
            lines += [f"**Ét spørgsmål kan afklare ruten:** {intel['seller_question']}", ""]
    else:
        lines += ["Ingen stærk donor-route blandt de aktuelt rangerede kandidater.", ""]

    lines += ["### 4. Sikker komplet Z20-løsning", ""]
    if cheapest_build:
        lines += [f"**{cheapest_build['total_price']} kr. — {cheapest_build['route']} — {cheapest_build['cpu']} + {cheapest_build['gpu']} — upgrade {cheapest_build['upgradeability']}**", ""]
    else:
        lines += ["Ingen komplet READY_TO_BUY build i optimizerens aktuelle evidens.", ""]
    if long_term:
        lines += [f"Langsigtet platformvalg: **{long_term['total_price']} kr. — {long_term['route']} — {long_term['cpu']} + {long_term['gpu']}**.", ""]

    lines += [
        "## Top 10 komplette PC'er — hvad kan du faktisk gøre?",
        "",
        "| # | ASK | PC | CPU | GPU | Board | Z20 | Upgrade | Mulighed | Mangler / næste handling |",
        "|---:|---:|---|---|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(ranked[:10], 1):
        intel = r.get("listing_intelligence") or {}
        routes = intel.get("routes") or []
        route_names = ", ".join(x.get("route", "") for x in routes[:3]) or "Ingen"
        board_fit = (intel.get("motherboard_z20_fit") or {}).get("value", "UNVERIFIED")
        upg = (intel.get("upgradeability") or {}).get("class", "UNVERIFIED")
        missing = intel.get("seller_question") or ", ".join(intel.get("missing_facts") or []) or "Ingen kritisk annonceoplysning"
        lines.append(
            f"| {i} | {r['ask_t1']} kr. | [{r['title']}]({r['url']}) | {evidence_value(r,'cpu',r.get('cpu','Ukendt'))} | {evidence_value(r,'gpu',r.get('gpu','Ukendt'))} | {evidence_value(r,'motherboard')} | {board_fit} | {upg} | {route_names} | {missing} |"
        )

    lines += ["", "## Evidens pr. Top 10", ""]
    for i, r in enumerate(ranked[:10], 1):
        intel = r.get("listing_intelligence") or {}
        lines += [f"### {i}. [{r['title']}]({r['url']}) — {r['ask_t1']} kr.", ""]
        for key, label in (("cpu","CPU"),("gpu","GPU"),("motherboard","Bundkort"),("ram","RAM"),("psu","PSU"),("case","Kabinet")):
            obj = intel.get(key) or {}
            lines.append(f"- **{label}:** {obj.get('value') or 'Ukendt'} — {obj.get('confidence','UNKNOWN')} — evidens: {obj.get('evidence') or 'ikke angivet'}")
        storage = intel.get("storage") or []
        if storage:
            lines.append("- **Lager:** " + "; ".join(f"{x.get('value')} ({x.get('confidence')})" for x in storage))
        lines.append(f"- **WoW-scenarie:** {scenario(r)}")
        if intel.get("seller_question"):
            lines.append(f"- **Spørg sælger:** {intel['seller_question']}")
        lines.append("")

    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"decision_report": True, "ranked_with_intelligence": len(enriched), "buy_now": buy_now.get("listing_id") if buy_now else None, "direct_z20": direct_z20.get("listing_id") if direct_z20 else None}, ensure_ascii=False))


if __name__ == "__main__":
    main()
