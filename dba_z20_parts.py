from __future__ import annotations

import asyncio
import json
import re
from collections import Counter
from pathlib import Path

from playwright.async_api import async_playwright

import dba_browser_v2 as v2
import dba_browser_v4 as v4
from dba_browser_v3 import discover_cards_by_article

QUERIES = [
    "rtx 3060 ti", "rtx 3070", "rtx 3070 ti", "rtx 3080", "rtx 4060", "rtx 4060 ti",
    "rx 6700 xt", "rx 6750 xt", "rx 6800", "rx 6800 xt", "rx 7600",
    "ryzen 5600 bundkort", "ryzen 5700x3d bundkort", "ryzen 5800x3d bundkort",
    "i5 10400 bundkort", "i5 11400 bundkort", "i5 12400 bundkort", "i5 12600 bundkort",
    "cpu bundkort ram", "bundkort ram cpu", "matx bundkort cpu", "micro atx bundkort cpu",
    "ddr4 16gb", "ddr4 32gb", "sfx strømforsyning", "atx strømforsyning 650w",
]
MAX_PRICE = 6000

GPU_NOUN = re.compile(r"\b(grafikkort|gpu|videokort|geforce|radeon)\b", re.I)
CPU_NOUN = re.compile(r"\b(cpu|processor|core\s+i[3579]|ryzen\s+[3579])\b", re.I)
BOARD = re.compile(r"\b(bundkort|motherboard|mainboard|(?:b|h|z|a)[345678]\d{2}[a-z0-9-]*)\b", re.I)
RAM_NOUN = re.compile(r"\b(ram|memory|hukommelse|ddr[345])\b", re.I)
RAM_CAPACITY = re.compile(r"\b(?:8|16|32|64)\s*gb\b", re.I)
PSU_NOUN = re.compile(r"\b(strømforsyning|psu|power\s*supply)\b", re.I)
PSU_WATT = re.compile(r"\b[5-9]\d{2}\s*w(?:att)?\b", re.I)
COMPLETE_PC = re.compile(r"\b(gaming|gamer)\s*(pc|computer)|\bstationær\b|\bdesktop\b|\bkomplet\s+pc\b", re.I)
DEFECT = re.compile(r"\b(defekt|delvist\s+defekt|virker\s+ikke|fejl|artifact|artefakt|til\s+dele|reservedele)\b", re.I)


def title_signals(title: str) -> dict[str, bool]:
    gpu, gs = v2.match_rule(title, v2.GPU_RULES)
    cpu, cs = v2.match_rule(title, v2.CPU_RULES)
    return {
        "gpu_model": gs >= 50,
        "cpu_model": cs >= 50,
        "gpu_noun": bool(GPU_NOUN.search(title)),
        "cpu_noun": bool(CPU_NOUN.search(title)),
        "board": bool(BOARD.search(title)),
        "ram": bool(RAM_NOUN.search(title) and RAM_CAPACITY.search(title)),
        "psu": bool(PSU_NOUN.search(title) or PSU_WATT.search(title)),
        "complete_pc": bool(COMPLETE_PC.search(title)),
    }


def classify(title: str, full_text: str, gpu_score: int, cpu_score: int) -> tuple[str | None, str]:
    """Fail closed: listing identity comes from title; description may enrich specs only.

    Search results are broad and DBA descriptions can mention unrelated components. A CPU/GPU
    model found only in description must never turn a RAM/PSU/other listing into that component.
    """
    s = title_signals(title)
    if s["complete_pc"]:
        return None, "COMPLETE_PC_NOT_COMPONENT"
    if s["board"] and s["cpu_model"]:
        return "PLATFORM_BUNDLE", "TITLE_PROVES_BOARD_AND_CPU"
    if s["gpu_model"] and (s["gpu_noun"] or re.search(r"\b(?:rtx|gtx|rx)\s*\d", title, re.I)):
        return "GPU", "TITLE_PROVES_GPU"
    if s["cpu_model"] and (s["cpu_noun"] or re.search(r"\b(?:i[3579][ -]?\d{4,5}|\d{4}x3d|ryzen)\b", title, re.I)):
        return "CPU", "TITLE_PROVES_CPU"
    if s["ram"] and not (s["gpu_model"] or s["cpu_model"] or s["board"] or s["psu"]):
        return "RAM", "TITLE_PROVES_RAM"
    if s["psu"] and not (s["gpu_model"] or s["cpu_model"] or s["board"] or s["ram"]):
        return "PSU", "TITLE_PROVES_PSU"
    return None, "TITLE_IDENTITY_AMBIGUOUS"


def regression() -> dict:
    cases = [
        ("G.Skill Ripjaws V DDR4-8x2 RAM rød 16gb 2022", "CPU", False),
        ("32GB (2x16GB) DDR4 3600 RAM", "CPU", False),
        ("AMD Ryzen 9 7950X3D", "CPU", False),  # unsupported CPU model must not inherit description model
        ("Gigabyte GeForce RTX 3060 Ti", "GPU", True),
        ("RAM, CPU, BUNDKORT, PSU i7-8700", "PLATFORM_BUNDLE", True),
        ("Intel Core i5-9600K + Gigabyte Z390 AORUS PRO + 16GB DDR4", "PLATFORM_BUNDLE", True),
    ]
    results = []
    for title, expected, should_match in cases:
        _, gs = v2.match_rule(title, v2.GPU_RULES)
        _, cs = v2.match_rule(title, v2.CPU_RULES)
        kind, reason = classify(title, title, gs, cs)
        ok = (kind == expected) if should_match else (kind != expected)
        if not ok:
            raise SystemExit(f"Z20 COMPONENT CLASSIFIER REGRESSION FAILED: {title}: {kind}/{reason}")
        results.append({"title": title, "kind": kind, "ok": True})
    return {"ok": True, "cases": results}


async def main() -> None:
    Path("results").mkdir(exist_ok=True)
    reg = regression()
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(locale="da-DK", viewport={"width": 1440, "height": 1100})
        search_page = await context.new_page()
        item_page = await context.new_page()
        try:
            found: dict[str, dict] = {}
            errors: list[dict] = []
            for query in QUERIES:
                try:
                    cards = await discover_cards_by_article(search_page, query)
                except Exception as exc:
                    errors.append({"query": query, "error": type(exc).__name__, "detail": str(exc)[:300]})
                    continue
                for row in cards:
                    if not isinstance(row.get("ask_t0"), int) or row["ask_t0"] > MAX_PRICE:
                        continue
                    old = found.get(row["listing_id"])
                    if old is None:
                        row["source_queries"] = [query]
                        found[row["listing_id"]] = row
                    else:
                        old["source_queries"].append(query)

            opportunities: list[dict] = []
            rejected: list[dict] = []
            for row in sorted(found.values(), key=lambda x: (x["ask_t0"], x["listing_id"])):
                try:
                    t1 = await v4.fetch_jsonld_item_all_scripts(item_page, row["listing_id"])
                except Exception as exc:
                    rejected.append({"listing_id": row["listing_id"], "reason": "T1_FETCH_FAILED", "detail": type(exc).__name__})
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

                title = t1.get("title", "")
                text = f"{title}\n{t1.get('description','')}\n{t1.get('brand','')}\n{t1.get('category','')}"
                gpu, gs = v2.match_rule(text, v2.GPU_RULES)
                cpu, cs = v2.match_rule(text, v2.CPU_RULES)
                kind, evidence = classify(title, text, gs, cs)
                if not kind:
                    rejected.append({"listing_id": row["listing_id"], "reason": evidence, "title": title})
                    continue

                # Re-resolve CPU/GPU from title for identity-critical fields. Description may not
                # supply the component identity because it caused the V10 cross-category failures.
                title_gpu, title_gs = v2.match_rule(title, v2.GPU_RULES)
                title_cpu, title_cs = v2.match_rule(title, v2.CPU_RULES)
                if kind == "GPU":
                    gpu, gs, cpu, cs = title_gpu, title_gs, "Ukendt", 0
                elif kind in {"CPU", "PLATFORM_BUNDLE"}:
                    cpu, cs, gpu, gs = title_cpu, title_cs, "Ukendt", 0
                else:
                    gpu, gs, cpu, cs = "Ukendt", 0, "Ukendt", 0

                condition = "DEFECT_DISCLOSED" if DEFECT.search(text) else "NO_DEFECT_SIGNAL"
                format_class, rationale = v2.classify_format(text)
                opportunities.append({
                    "listing_id": row["listing_id"], "url": t1["canonical_url"], "title": title,
                    "ask_t0": row["ask_t0"], "ask_t1": t1["ask_t1"], "currency": t1["currency_t1"],
                    "price_changed": row["ask_t0"] != t1["ask_t1"], "status": t1["availability_t1"],
                    "kind": kind, "identity_evidence": evidence, "condition": condition,
                    "gpu": gpu, "gpu_score": gs, "cpu": cpu, "cpu_score": cs,
                    "format_evidence": format_class, "format_rationale": rationale,
                    "t0_source": row["t0_source"], "t1_source": t1["t1_source"],
                    "t0_at": row.get("t0_at"), "t1_at": t1.get("t1_at"),
                    "source_queries": sorted(set(row.get("source_queries") or [])),
                })
        finally:
            await search_page.close()
            await item_page.close()
            await context.close()
            await browser.close()

    opportunities.sort(key=lambda r: (r["ask_t1"], -r["gpu_score"], -r["cpu_score"]))
    out = {
        "model_version": "DBA-Z20-PARTS-V2", "generated_at": v2.utcnow(), "gate_passed": True,
        "target_case": "Jonsbo Z20",
        "policy": "Fail-closed component identity: title must prove listing type/model; description can enrich but cannot reclassify. Live same-ID T0/T1 price/status required. Defects are surfaced explicitly.",
        "classifier_regression": reg,
        "counts": {"queries": len(QUERIES), "t0_unique": len(found), "opportunities": len(opportunities), "rejected": len(rejected)},
        "opportunities": opportunities,
        "rejection_reason_counts": dict(Counter(x["reason"] for x in rejected)),
        "search_errors": errors,
    }
    Path("results/z20_parts_latest.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out["counts"], ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
