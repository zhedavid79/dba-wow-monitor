from __future__ import annotations

import asyncio
import json
from collections import Counter
from pathlib import Path

from playwright.async_api import async_playwright

import dba_browser_v2 as v2
from dba_browser_v3 import discover_cards_by_article, fetch_jsonld_item_all_scripts


async def main() -> None:
    Path("results").mkdir(exist_ok=True)
    regression = v2.fixture_regression()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(locale="da-DK", viewport={"width": 1440, "height": 1100})
        search_page = await context.new_page()
        item_page = await context.new_page()

        found: dict[str, dict] = {}
        search_errors: list[dict] = []
        for query in v2.QUERIES:
            try:
                rows = await discover_cards_by_article(search_page, query)
            except Exception as exc:
                search_errors.append({"query": query, "error": type(exc).__name__, "detail": str(exc)[:300]})
                continue
            for row in rows:
                existing = found.get(row["listing_id"])
                if existing is None:
                    row["source_queries"] = [query]
                    found[row["listing_id"]] = row
                else:
                    existing["source_queries"].append(query)

        # Only current search cards with an eligible GPU are candidates for the dynamic source gate.
        # No fixed historical listing is required.
        promising: list[dict] = []
        for row in found.values():
            gpu, gpu_score = v2.match_rule(row["title"] + "\n" + row["card_text"], v2.GPU_RULES)
            if gpu_score >= 50:
                row["t0_gpu"] = gpu
                row["t0_gpu_score"] = gpu_score
                promising.append(row)

        source_gate = None
        gate_attempts: list[dict] = []
        for row in sorted(promising, key=lambda x: (x["ask_t0"], x["listing_id"])):
            try:
                t1 = await fetch_jsonld_item_all_scripts(item_page, row["listing_id"])
            except Exception as exc:
                gate_attempts.append({"listing_id": row["listing_id"], "result": "fetch_error", "detail": type(exc).__name__})
                continue
            if not t1:
                gate_attempts.append({"listing_id": row["listing_id"], "result": "no_product_json"})
                continue
            if not t1.get("identity_ok"):
                gate_attempts.append({"listing_id": row["listing_id"], "result": "identity_failed"})
                continue
            if not t1.get("active_t1"):
                gate_attempts.append({"listing_id": row["listing_id"], "result": "inactive_or_status_failed"})
                continue
            if not isinstance(t1.get("ask_t1"), int) or t1.get("currency_t1") != "DKK" or not t1.get("title"):
                gate_attempts.append({"listing_id": row["listing_id"], "result": "price_currency_title_failed"})
                continue
            source_gate = {
                "ok": True,
                "listing_id": row["listing_id"],
                "canonical_url": t1["canonical_url"],
                "title": t1["title"],
                "t0_price": row["ask_t0"],
                "t1_price": t1["ask_t1"],
                "price_changed": row["ask_t0"] != t1["ask_t1"],
                "currency": t1["currency_t1"],
                "status": t1["availability_t1"],
                "t0_source": row["t0_source"],
                "t1_source": t1["t1_source"],
                "t0_at": row["t0_at"],
                "t1_at": t1["t1_at"],
            }
            break

        if source_gate is None:
            diagnostic = {
                "model_version": "DBA-WOW-BROWSER-PRICE-FIRST-A3-V4",
                "generated_at": v2.utcnow(),
                "gate_passed": False,
                "counts": {"queries": len(v2.QUERIES), "t0_unique": len(found), "t0_gpu_promising": len(promising)},
                "gate_attempts": gate_attempts[:100],
                "search_errors": search_errors,
            }
            Path("results/wow_a3_gate_failure.json").write_text(json.dumps(diagnostic, ensure_ascii=False, indent=2), encoding="utf-8")
            await browser.close()
            raise SystemExit("PRICE DATA GATE FAILED — no live GPU-relevant rendered-card + same-ID Product JSON pair verified")

        ranked: list[dict] = []
        leads: list[dict] = []
        rejected: list[dict] = []

        # T1 is fetched again for every reportable candidate after discovery and source-gate validation.
        for row in promising:
            try:
                t1 = await fetch_jsonld_item_all_scripts(item_page, row["listing_id"])
            except Exception as exc:
                rejected.append({"listing_id": row["listing_id"], "reason": "T1_FETCH_FAILED", "detail": str(exc)[:300]})
                continue
            if not t1 or not t1.get("identity_ok"):
                rejected.append({"listing_id": row["listing_id"], "reason": "T1_IDENTITY_UNVERIFIED"})
                continue
            if not t1.get("active_t1"):
                rejected.append({"listing_id": row["listing_id"], "reason": "INACTIVE_OR_STATUS_UNVERIFIED"})
                continue
            if not isinstance(t1.get("ask_t1"), int) or t1.get("currency_t1") != "DKK":
                rejected.append({"listing_id": row["listing_id"], "reason": "MISSING_OR_INVALID_T1_PRICE"})
                continue
            if not v2.complete_pc_category(t1.get("category", ""), t1.get("title", "")):
                rejected.append({"listing_id": row["listing_id"], "reason": "NOT_VERIFIED_COMPLETE_PC_CATEGORY"})
                continue

            text = f"{t1['title']}\n{t1.get('description', '')}"
            gpu, gpu_score = v2.match_rule(text, v2.GPU_RULES)
            cpu, cpu_score = v2.match_rule(text, v2.CPU_RULES)
            if gpu_score < 50 or cpu_score < 50:
                rejected.append({"listing_id": row["listing_id"], "reason": "SPEC_PARSE_FAILED", "gpu": gpu, "cpu": cpu})
                continue

            pclass = v2.performance_class(gpu_score, cpu_score)
            if pclass == "UNDER MINIMUM":
                rejected.append({"listing_id": row["listing_id"], "reason": "UNDER_MINIMUM"})
                continue

            fgate, frationale = v2.classify_format(text)
            result = {
                "listing_id": row["listing_id"],
                "url": t1["canonical_url"],
                "title": t1["title"],
                "ask_t0": row["ask_t0"],
                "ask_t1": t1["ask_t1"],
                "currency": t1["currency_t1"],
                "price_changed": row["ask_t0"] != t1["ask_t1"],
                "status": t1["availability_t1"],
                "category": t1.get("category"),
                "gpu": gpu,
                "gpu_score": gpu_score,
                "cpu": cpu,
                "cpu_score": cpu_score,
                "performance_class": pclass,
                "format_gate": fgate,
                "format_rationale": frationale,
                "t0_source": row["t0_source"],
                "t1_source": t1["t1_source"],
                "t0_at": row["t0_at"],
                "t1_at": t1["t1_at"],
                "source_queries": sorted(set(row.get("source_queries") or [])),
            }

            if fgate in {"LAPTOP", "A3_READY", "A3_READY_PSU_CHECK"}:
                ranked.append(result)
            elif fgate == "A3_UNCERTAIN":
                leads.append(result)
            else:
                rejected.append({**result, "reason": fgate})

        await browser.close()

    class_order = {"SWEET SPOT": 0, "ACCEPTABLE": 1, "OVERKILL": 2}
    format_order = {"LAPTOP": 0, "A3_READY": 0, "A3_READY_PSU_CHECK": 1}
    ranked.sort(key=lambda r: (r["ask_t1"], format_order.get(r["format_gate"], 9), class_order.get(r["performance_class"], 9), -r["gpu_score"], -r["cpu_score"]))
    leads.sort(key=lambda r: (r["ask_t1"], -r["gpu_score"], -r["cpu_score"]))

    output = {
        "model_version": "DBA-WOW-BROWSER-PRICE-FIRST-A3-V4",
        "generated_at": v2.utcnow(),
        "gate_passed": True,
        "retrieval_method": "Rendered DBA article.sf-search-ad T0 + same-ID DBA Product JSON T1",
        "source_gate": source_gate,
        "price_binding_regression": regression,
        "counts": {
            "queries": len(v2.QUERIES),
            "t0_unique": len(found),
            "t0_gpu_promising": len(promising),
            "t1_ranked_format_verified": len(ranked),
            "t1_a3_uncertain_leads": len(leads),
            "rejected": len(rejected),
        },
        "ranked": ranked,
        "leads": leads,
        "rejected": rejected,
        "rejection_reason_counts": dict(Counter(x.get("reason", "UNKNOWN") for x in rejected)),
        "search_errors": search_errors,
    }
    Path("results/wow_a3_latest.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# FULDT PÅLIDELIG DBA-PRISRAPPORT — WoW Classic/Cataclysm — laptop/A3",
        "",
        f"Generated: {output['generated_at']}",
        f"Retrieval: {output['retrieval_method']}",
        f"Verified ranked records: {len(ranked)}",
        "",
    ]
    if ranked:
        top = ranked[0]
        lines += [
            "## Buy now / billigste tilstrækkelige",
            "",
            f"[{top['title']}]({top['url']}) — **{top['ask_t1']} kr.** — {top['format_gate']} — {top['performance_class']}",
            "",
            "## Ranked shortlist",
            "",
            "| # | T1 ASK | Format | Klasse | GPU | CPU | ID | DBA |",
            "|---:|---:|---|---|---|---|---|---|",
        ]
        for i, r in enumerate(ranked, 1):
            lines.append(f"| {i} | {r['ask_t1']} kr. | {r['format_gate']} | {r['performance_class']} | {r['gpu']} | {r['cpu']} | {r['listing_id']} | [{r['title']}]({r['url']}) |")
    else:
        lines.append("Ingen kandidat bestod T0/T1, performancegate og laptop/A3-formatgate.")

    lines += ["", "## A3-uncertain leads — ikke rangeret", ""]
    for r in leads[:40]:
        lines.append(f"- [{r['title']}]({r['url']}) — {r['ask_t1']} kr. — ID {r['listing_id']} — {r['format_rationale']}")
    lines += ["", "## Objektive diskvalifikationer", "", json.dumps(output["rejection_reason_counts"], ensure_ascii=False)]
    Path("results/wow_a3_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(json.dumps({"gate": True, "t0_unique": len(found), "promising": len(promising), "ranked": len(ranked), "leads": len(leads), "rejected": len(rejected)}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
