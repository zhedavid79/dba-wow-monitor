from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import requests

import dba_report_v9 as v9

v6 = v9.v6

LAPTOP_PATTERNS = [
    r"\blaptop\b", r"\bbærbar\b", r"\bnotebook\b", r"\bomen\s+1[456789]\b",
    r"\blegion\s+(?:5|7|pro|slim)\b", r"\bnitro\s+(?:5|16|17|v)\b",
    r"\bpredator\s+helios\b", r"\bkatana\s+(?:15|17)\b", r"\braider\s+ge\b",
    r"\brog\s+(?:strix|zephyrus)\b", r"\btuf\s+gaming\s+(?:a|f)1[567]\b",
]

# Strong positive evidence only. Ambiguous desktops are deliberately not ranked.
MATX_PATTERNS = [
    r"\bmicro[- ]?atx\b", r"\bm[- ]?atx\b", r"\bmatx\b",
    r"\b(?:a|b|h|q|z)[1-9]\d{2}m(?:[-\s]|\b)",
    r"\b(?:a|b|h|q|z)[1-9]\d{2}m[-\w]*\b",
]
ITX_PATTERNS = [r"\bmini[- ]?itx\b", r"\bitx\b"]
ATX_PATTERNS = [r"\be[- ]?atx\b", r"\bextended[- ]?atx\b", r"\batx\b"]

# These brands/models can contain proprietary board/PSU/front-panel designs. They are
# never auto-approved unless the listing itself provides explicit standard mATX/ITX evidence.
OEM_RISK_PATTERNS = [
    r"\bhp\s+(?:omen|pavilion)\b", r"\bdell\s+(?:g5|xps|alienware)\b",
    r"\blenovo\s+(?:legion|ideacentre)\b", r"\bacer\s+(?:nitro|predator)\b",
]

PSU_STANDARD_PATTERNS = [
    r"\b(?:atx|sfx|sfx-l)\s+(?:psu|power supply|strømforsyning)\b",
    r"\b(?:corsair|seasonic|be quiet!?|evga|cooler master|nzxt|asus|msi|fsp|super flower)\b.{0,40}\b\d{3,4}\s*w\b",
]


def _matches(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text, re.I) for p in patterns)


def classify_transfer(title: str, description: str) -> tuple[str, str]:
    text = f"{title}\n{description}"
    if _matches(LAPTOP_PATTERNS, text):
        return "LAPTOP", "Complete portable system; no case transfer required."

    matx = _matches(MATX_PATTERNS, text)
    itx = _matches(ITX_PATTERNS, text)
    # Avoid treating the token 'ATX' inside 'mATX' as full-size ATX evidence.
    normalized = re.sub(r"\b(?:micro[- ]?atx|m[- ]?atx|matx|mini[- ]?itx)\b", " ", text, flags=re.I)
    full_atx = _matches(ATX_PATTERNS, normalized)
    oem_risk = _matches(OEM_RISK_PATTERNS, text)
    standard_psu = _matches(PSU_STANDARD_PATTERNS, text)

    if full_atx and not (matx or itx):
        return "A3_INCOMPATIBLE", "Listing explicitly indicates ATX/E-ATX rather than mATX/ITX."
    if matx or itx:
        if standard_psu:
            return "A3_READY", "Listing explicitly supports mATX/ITX and indicates a standard PSU family/brand."
        return "A3_READY_PSU_CHECK", "mATX/ITX is evidenced; PSU dimensions/standard still require confirmation."
    if oem_risk:
        return "A3_UNCERTAIN", "OEM platform without explicit standard mATX/ITX evidence; proprietary parts cannot be ruled out."
    return "A3_UNCERTAIN", "Desktop form factor is not explicitly evidenced as mATX/ITX in the live listing."


def fetch_live_detail(listing_id: str) -> dict:
    s = requests.Session()
    raw = v6.getj(s, v6.ITEM_URL.format(id=listing_id))
    item = raw.get("itemData") or {}
    price = v6.amount(item.get("price"))
    return {
        "listing_id": str(listing_id),
        "title": str(item.get("title") or ""),
        "description": str(item.get("description") or ""),
        "ask": price,
        "disposed": bool(item.get("disposed")),
        "trade_type": item.get("tradeType") or item.get("adViewTypeLabel"),
    }


def main() -> None:
    # Reuse the proven structured DBA T0/T1 pipeline and its schema + regression gates.
    v6.main()

    src = Path("results/latest_v6.json")
    data = json.loads(src.read_text(encoding="utf-8"))
    base_ranked = data.get("ranked") or []

    eligible = []
    leads = []
    rejected = []

    for r in base_ranked:
        if r.get("performance_class") == "UNDER MINIMUM":
            rejected.append({**r, "objective_reason": "UNDER_MINIMUM"})
            continue

        try:
            live = fetch_live_detail(str(r["listing_id"]))
        except Exception as exc:
            rejected.append({**r, "objective_reason": "FORMAT_GATE_REFETCH_FAILED", "detail": str(exc)})
            continue

        # This is a second live same-ID refetch after v6 T1. Never rank if identity/status/price is uncertain.
        if live["listing_id"] != str(r["listing_id"]):
            rejected.append({**r, "objective_reason": "IDENTITY_MISMATCH"})
            continue
        if live["disposed"]:
            rejected.append({**r, "objective_reason": "INACTIVE_OR_DISPOSED"})
            continue
        if live["ask"] is None:
            rejected.append({**r, "objective_reason": "MISSING_LIVE_PRICE"})
            continue

        status, rationale = classify_transfer(live["title"] or r.get("title", ""), live["description"])
        row = {
            **r,
            "ask_t1": int(live["ask"]),
            "title": live["title"] or r.get("title", ""),
            "trade_type": live["trade_type"],
            "format_gate": status,
            "format_rationale": rationale,
            "format_gate_refetched_at": datetime.now(timezone.utc).isoformat(),
        }

        if status in {"LAPTOP", "A3_READY", "A3_READY_PSU_CHECK"}:
            eligible.append(row)
        elif status == "A3_UNCERTAIN":
            leads.append(row)
        else:
            rejected.append({**row, "objective_reason": status})

    class_order = {"SWEET SPOT": 0, "ACCEPTABLE": 1, "OVERKILL": 2}
    format_order = {"A3_READY": 0, "LAPTOP": 0, "A3_READY_PSU_CHECK": 1}
    eligible.sort(key=lambda r: (
        int(r.get("ask_t1", 10**9)),
        format_order.get(r.get("format_gate"), 9),
        class_order.get(r.get("performance_class"), 9),
        -int(r.get("gpu_score", 0)),
        -int(r.get("cpu_score", 0)),
    ))

    out = {
        "model_version": "DBA-WOW-PRICE-FIRST-A3-V10",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "gate_passed": bool(data.get("schema_gate", {}).get("ok")) and bool(data.get("price_binding_regression", {}).get("ok")),
        "source": "DBA native structured search API + DBA item JSON; same-ID live refetch for format gate",
        "schema_gate": data.get("schema_gate"),
        "price_binding_regression": data.get("price_binding_regression"),
        "counts": {
            **(data.get("counts") or {}),
            "base_ranked_after_t1": len(base_ranked),
            "format_verified_ranked": len(eligible),
            "a3_uncertain_leads": len(leads),
            "format_or_status_rejected": len(rejected),
        },
        "ranked": eligible,
        "leads": leads,
        "rejected": rejected,
        "rejection_reason_counts": dict(Counter(x.get("objective_reason", "UNKNOWN") for x in rejected)),
    }

    Path("results/wow_a3_latest.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# FULDT PÅLIDELIG DBA-PRISRAPPORT — WoW Classic/Cataclysm — laptop/A3",
        "",
        f"Generated: {out['generated_at']}",
        f"Source: {out['source']}",
        f"Structured verified ranked records: {len(eligible)}",
        "",
    ]
    if not out["gate_passed"]:
        lines[0] = "# PRICE DATA GATE FAILED — INGEN VERIFICERET PRISRANGERING"
    if eligible:
        lines += [
            f"## Buy now / billigste tilstrækkelige\n\n[{eligible[0]['title']}]({eligible[0]['url']}) — **{eligible[0]['ask_t1']} kr.** — {eligible[0]['format_gate']} — {eligible[0]['performance_class']}",
            "",
            "## Ranked shortlist",
            "",
            "| # | T1 ASK | Format | Klasse | GPU | CPU | Listing ID | DBA-link |",
            "|---:|---:|---|---|---|---|---|---|",
        ]
        for i, r in enumerate(eligible, 1):
            lines.append(f"| {i} | {r['ask_t1']} kr. | {r['format_gate']} | {r['performance_class']} | {r['gpu']} | {r['cpu']} | {r['listing_id']} | [{r['title']}]({r['url']}) |")
    else:
        lines += ["Ingen kandidat bestod både pris-/identitetsgate, performancegate og laptop/A3-formatgate."]

    lines += ["", "## A3-uncertain leads (ikke rangeret)", ""]
    for r in leads[:30]:
        lines.append(f"- [{r['title']}]({r['url']}) — listing {r['listing_id']} — {r['format_rationale']}")
    lines += ["", "## Objektive diskvalifikationer", "", json.dumps(out["rejection_reason_counts"], ensure_ascii=False)]

    Path("results/wow_a3_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
