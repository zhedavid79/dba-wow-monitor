from __future__ import annotations

import json
from pathlib import Path

import dba_decision_report

RESULT = Path("results/wow_a3_latest.json")
EXCLUDED_LISTING_IDS = {"7969913": "PURCHASE_ATTEMPTED"}


def main() -> None:
    doc = json.loads(RESULT.read_text(encoding="utf-8"))
    if doc.get("gate_passed") is not True:
        raise SystemExit("PRICE DATA GATE FAILED — active complete-PC report requires a passed source gate")

    excluded = []
    ranked = []
    for row in doc.get("ranked") or []:
        lid = str(row.get("listing_id") or "")
        if lid in EXCLUDED_LISTING_IDS:
            excluded.append({
                "listing_id": lid,
                "reason": EXCLUDED_LISTING_IDS[lid],
                "title": row.get("title"),
                "url": row.get("url"),
                "ask_t1": row.get("ask_t1"),
            })
            continue
        ranked.append(row)

    unresolved = [
        row for row in (doc.get("potential_sweet_spots_unresolved") or [])
        if str(row.get("listing_id") or "") not in EXCLUDED_LISTING_IDS
    ]

    doc["ranked"] = ranked
    doc["potential_sweet_spots_unresolved"] = unresolved
    doc.setdefault("counts", {})["ranked"] = len(ranked)
    doc["counts"]["potential_sweet_spot_unresolved"] = len(unresolved)
    doc["procurement_exclusions"] = excluded
    doc["active_model"] = "PRICE_FIRST_COMPLETE_PC_ONLY"
    doc["scope"] = "Complete ready-to-use desktop gaming PCs, gaming laptops and mini PCs only. No self-build, donor-build or component procurement."
    RESULT.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")

    dba_decision_report.main()

    report = Path("results/wow_a3_report.md")
    text = report.read_text(encoding="utf-8")
    exclusion_line = "Procurement-ekskluderet: `7969913` (PURCHASE_ATTEMPTED).\n"
    if exclusion_line not in text:
        marker = "Scope: komplette brugsklare stationære gaming-PC'er, gaming laptops og mini-PC'er. Ingen byg-selv, donor-builds eller komponentjagt.\n"
        text = text.replace(marker, marker + exclusion_line)
        report.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
