from __future__ import annotations

import asyncio
import json
import re
from collections import Counter
from pathlib import Path

from playwright.async_api import async_playwright

import dba_browser_v2 as v2
import dba_browser_v4 as v4
import dba_browser_v5  # noqa: F401  # category-aware JSON-LD patches
from dba_browser_v3 import discover_cards_by_article

RESCUE_PRICE_MAX = 6000
COMPLETE_HINT_RE = re.compile(
    r"\b(?:gaming|gamer)\s*(?:pc|computer|laptop|bærbar)|"
    r"\b(?:pc|computer)\s*(?:gaming|gamer)|"
    r"\b(?:hp\s+)?omen\b|\blegion\b|\bnitro\b|\bpredator\b|"
    r"\bsharkgaming\b|\bdutzo\b|\bmm[- ]?vision\b|\bmsi\s+(?:gamer|katana|raider)\b|"
    r"\bro[gq]\s+(?:strix|zephyrus)\b|\btuf\s+gaming\b|\balienware\b",
    re.I,
)
COMPONENT_ONLY_RE = re.compile(
    r"\b(?:grafikkort|gpu\s+only|videokort|waterblock|vandblok|eGPU|strømforsyning|psu\s+only|"
    r"bundkort|motherboard|cpu\s+only|processor\s+only|ram\s+kit|ssd\s+only|kabinet\s+only)\b",
    re.I,
)


def discovery_priority(row: dict) -> tuple[int, int, str]:
    text = f"{row.get('title','')}\n{row.get('card_text','')}"
    _, gpu_score = v2.match_rule(text, v2.GPU_RULES)
    complete_hint = bool(COMPLETE_HINT_RE.search(text)) and not bool(COMPONENT_ONLY_RE.search(text))
    if gpu_score >= 50 and complete_hint:
        tier = 0
    elif complete_hint and int(row.get("ask_t0") or 10**9) <= RESCUE_PRICE_MAX:
        tier = 1
    elif gpu_score >= 50:
        tier = 2
    else:
        tier = 9
    return tier, int(row.get("ask_t0") or 10**9), str(row.get("listing_id") or "")


def should_t1(row: dict) -> bool:
    return discovery_priority(row)[0] < 9


def unresolved_record(row: dict, t1: dict, gpu: str, gpu_score: int, cpu: str, cpu_score: int) -> dict:
    return {
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
        "resolution_status": "POTENTIAL_SWEET_SPOT_UNRESOLVED",
        "resolution_reason": "GPU_PARSE_FAILED" if gpu_score < 50 else "CPU_PARSE_FAILED",
        "t0_source": row["t0_source"],
        "t1_source": t1["t1_source"],
        "t0_at": row["t0_at"],
        "t1_at": t1["t1_at"],
        "source_queries": sorted(set(row.get("source_queries") or [])),
    }


async def main() -> None:
    Path("results").mkdir(exist_ok=True)
    regression = v2.fixture_regression()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(locale="da-DK", viewport={"width": 1440, "height": 1100})
        search_page = await context.new_page()
        item_page = await context.new_page()
        try:
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

            candidates = sorted((r for r in found.values() if should_t1(r)), key=discovery_priority)

            source_gate = None
            gate_attempts: list[dict] = []
            for row in candidates:
                try:
                    t1 = await v4.fetch_jsonld_item_all_scripts(item_page, row["listing_id"])
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
                    "model_version": "DBA-WOW-BROWSER-HIGH-RECALL-V7",
                    "generated_at": v2.utcnow(),
                    "gate_passed": False,
                    "counts": {"queries": len(v2.QUERIES), "t0_unique": len(found), "t0_to_t1": len(candidates)},
                    "gate_attempts": gate_attempts[:100],
                    "search_errors": search_errors,
                }
                Path("results/wow_a3_gate_failure.json").write_text(json.dumps(diagnostic, ensure_ascii=False, indent=2), encoding="utf-8")
                raise SystemExit("PRICE DATA GATE FAILED — no live rendered-card + same-ID Product JSON pair verified")

            ranked: list[dict] = []
            unresolved: list[dict] = []
            rejected: list[dict] = []

            for row in candidates:
                try:
                    t1 = await v4.fetch_jsonld_item_all_scripts(item_page, row["listing_id"])
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

                text = f"{t1['title']}\n{t1.get('description', '')}\n{t1.get('brand','')}\n{t1.get('category','')}"
                gpu, gpu_score = v2.match_rule(text, v2.GPU_RULES)
                cpu, cpu_score = v2.match_rule(text, v2.CPU_RULES)
                if gpu_score < 50 or cpu_score < 50:
                    if int(t1["ask_t1"]) <= RESCUE_PRICE_MAX:
                        unresolved.append(unresolved_record(row, t1, gpu, gpu_score, cpu, cpu_score))
                    else:
                        rejected.append({"listing_id": row["listing_id"], "reason": "SPEC_PARSE_FAILED", "gpu": gpu, "cpu": cpu})
                    continue

                pclass = v2.performance_class(gpu_score, cpu_score)
                if pclass == "UNDER MINIMUM":
                    rejected.append({"listing_id": row["listing_id"], "reason": "UNDER_MINIMUM"})
                    continue

                a3_assessment, a3_rationale = v2.classify_format(text)
                is_laptop = a3_assessment == "LAPTOP"
                ranked.append({
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
                    "form_factor": "LAPTOP" if is_laptop else "DESKTOP",
                    "case_check": "NOT_NEEDED" if is_laptop else "MANUAL_A3_CHECK",
                    "a3_assessment": a3_assessment,
                    "a3_rationale": a3_rationale,
                    "t0_source": row["t0_source"],
                    "t1_source": t1["t1_source"],
                    "t0_at": row["t0_at"],
                    "t1_at": t1["t1_at"],
                    "source_queries": sorted(set(row.get("source_queries") or [])),
                })
        finally:
            await search_page.close()
            await item_page.close()
            await context.close()
            await browser.close()

    class_order = {"SWEET SPOT": 0, "ACCEPTABLE": 1, "OVERKILL": 2}
    ranked.sort(key=lambda r: (r["ask_t1"], class_order.get(r["performance_class"], 9), -r["gpu_score"], -r["cpu_score"]))
    unresolved.sort(key=lambda r: (r["ask_t1"], r["listing_id"]))

    output = {
        "model_version": "DBA-WOW-BROWSER-HIGH-RECALL-V7",
        "generated_at": v2.utcnow(),
        "gate_passed": True,
        "retrieval_method": "Rendered DBA article.sf-search-ad T0 + same-ID DBA Product JSON T1",
        "ranking_policy": "Verified complete PCs clearing the WoW performance gate are ranked strictly price-first. Cheap unresolved complete systems remain visible but unranked.",
        "source_gate": source_gate,
        "price_binding_regression": regression,
        "counts": {
            "queries": len(v2.QUERIES),
            "t0_unique": len(found),
            "t0_to_t1": len(candidates),
            "ranked": len(ranked),
            "potential_sweet_spot_unresolved": len(unresolved),
            "rejected": len(rejected),
        },
        "ranked": ranked,
        "potential_sweet_spots_unresolved": unresolved,
        "rejected": rejected,
        "rejection_reason_counts": dict(Counter(x.get("reason", "UNKNOWN") for x in rejected)),
        "search_errors": search_errors,
    }
    Path("results/wow_a3_latest.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# FULDT PÅLIDELIG DBA-PRISRAPPORT — WoW Classic/Cataclysm",
        "",
        f"Generated: {output['generated_at']}",
        f"Retrieval: {output['retrieval_method']}",
        f"Verified ranked records: {len(ranked)}",
        f"Potential sweet spots needing spec resolution: {len(unresolved)}",
        "",
    ]
    if ranked:
        top = ranked[0]
        lines += [
            "## Buy now / billigste tilstrækkelige", "",
            f"[{top['title']}]({top['url']}) — **{top['ask_t1']} kr.** — {top['performance_class']}", "",
            "## Ranked shortlist", "",
            "| # | T1 ASK | Type | Klasse | GPU | CPU | ID | DBA |",
            "|---:|---:|---|---|---|---|---|---|",
        ]
        for i, r in enumerate(ranked, 1):
            lines.append(f"| {i} | {r['ask_t1']} kr. | {r['form_factor']} | {r['performance_class']} | {r['gpu']} | {r['cpu']} | {r['listing_id']} | [{r['title']}]({r['url']}) |")
    else:
        lines.append("Ingen kandidat bestod T0/T1 og performancegaten.")

    lines += ["", "## POTENTIAL SWEET SPOTS — NEEDS SPEC RESOLUTION", ""]
    for r in unresolved:
        lines.append(f"- [{r['title']}]({r['url']}) — {r['ask_t1']} kr. — {r['resolution_reason']} — ID {r['listing_id']}")
    lines += ["", "## Objektive diskvalifikationer", "", json.dumps(output["rejection_reason_counts"], ensure_ascii=False)]
    Path("results/wow_a3_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(json.dumps({"gate": True, "t0_unique": len(found), "t0_to_t1": len(candidates), "ranked": len(ranked), "unresolved": len(unresolved), "rejected": len(rejected)}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
