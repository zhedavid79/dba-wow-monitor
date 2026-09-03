from __future__ import annotations

import asyncio
import json
import re
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

GPU_ONLY = re.compile(r"\b(grafikkort|gpu|geforce|radeon|rtx|rx\s*\d{4})\b", re.I)
BOARD = re.compile(r"\b(bundkort|motherboard|b[3456]\d{2}[a-z-]*|h[3456]\d{2}[a-z-]*|z[3456]\d{2}[a-z-]*|a[3456]\d{2}[a-z-]*)\b", re.I)
RAM = re.compile(r"\b(16|32|64)\s*gb\b.{0,30}\b(ddr4|ddr5|ram)\b|\b(ddr4|ddr5)\b.{0,30}\b(16|32|64)\s*gb\b", re.I | re.S)
PSU = re.compile(r"\b(strømforsyning|psu|power supply)\b|\b[5-9]\d{2}\s*w\b", re.I)


def classify(text: str, gpu_score: int, cpu_score: int) -> str | None:
    board = bool(BOARD.search(text))
    ram = bool(RAM.search(text))
    if board and cpu_score > 0:
        return "PLATFORM_BUNDLE"
    if gpu_score >= 50 and GPU_ONLY.search(text):
        return "GPU"
    if cpu_score >= 50:
        return "CPU"
    if ram:
        return "RAM"
    if PSU.search(text):
        return "PSU"
    return None


async def main() -> None:
    Path("results").mkdir(exist_ok=True)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(locale="da-DK", viewport={"width": 1440, "height": 1100})
        search_page = await context.new_page()
        item_page = await context.new_page()
        try:
            found: dict[str, dict] = {}
            errors = []
            for query in QUERIES:
                try:
                    cards = await discover_cards_by_article(search_page, query)
                except Exception as exc:
                    errors.append({"query": query, "error": type(exc).__name__})
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

            opportunities = []
            for row in sorted(found.values(), key=lambda x: (x["ask_t0"], x["listing_id"])):
                try:
                    t1 = await v4.fetch_jsonld_item_all_scripts(item_page, row["listing_id"])
                except Exception:
                    continue
                if not t1 or not t1.get("identity_ok") or not t1.get("active_t1"):
                    continue
                if not isinstance(t1.get("ask_t1"), int) or t1.get("currency_t1") != "DKK":
                    continue
                text = f"{t1.get('title','')}\n{t1.get('description','')}\n{t1.get('brand','')}\n{t1.get('category','')}"
                gpu, gs = v2.match_rule(text, v2.GPU_RULES)
                cpu, cs = v2.match_rule(text, v2.CPU_RULES)
                kind = classify(text, gs, cs)
                if not kind:
                    continue
                format_class, rationale = v2.classify_format(text)
                opportunities.append({
                    "listing_id": row["listing_id"], "url": t1["canonical_url"], "title": t1["title"],
                    "ask_t0": row["ask_t0"], "ask_t1": t1["ask_t1"], "currency": t1["currency_t1"],
                    "status": t1["availability_t1"], "kind": kind, "gpu": gpu, "gpu_score": gs,
                    "cpu": cpu, "cpu_score": cs, "format_evidence": format_class,
                    "format_rationale": rationale, "t0_source": row["t0_source"], "t1_source": t1["t1_source"],
                    "source_queries": sorted(set(row.get("source_queries") or [])),
                })
        finally:
            await search_page.close(); await item_page.close(); await context.close(); await browser.close()

    opportunities.sort(key=lambda r: (r["ask_t1"], -r["gpu_score"], -r["cpu_score"]))
    out = {
        "model_version": "DBA-Z20-PARTS-V1", "generated_at": v2.utcnow(), "gate_passed": True,
        "target_case": "Jonsbo Z20", "policy": "Live T0/T1 verified component, bundle and PSU opportunities; no compatibility is inferred from missing evidence.",
        "counts": {"queries": len(QUERIES), "t0_unique": len(found), "opportunities": len(opportunities)},
        "opportunities": opportunities, "search_errors": errors,
    }
    Path("results/z20_parts_latest.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out["counts"], ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
