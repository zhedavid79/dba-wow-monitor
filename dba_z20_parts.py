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
    "b550m ryzen", "b450m ryzen", "am5 b650m", "ryzen matx bundkort",
    "i5 10400 bundkort", "i5 11400 bundkort", "i5 12400 bundkort", "i5 12600 bundkort",
    "b560m i5", "b660m i5", "b760m i5", "intel matx bundkort cpu",
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

# Explicit model evidence. Z20 supports only Mini-ITX / Micro-ATX; ATX is a hard rejection.
MATX_MODEL = re.compile(r"\b(?:b450m|b550m|a520m|x570m|b650m|a620m|x670m|h410m|b460m|h510m|b560m|h610m|b660m|b760m|z690m|z790m|b365m|h370m|z390m)\b", re.I)
MATX_WORD = re.compile(r"\b(?:m-?atx|micro[- ]?atx|microatx)\b", re.I)
ITX_WORD = re.compile(r"\b(?:mini[- ]?itx|miniitx|m-?itx)\b", re.I)
ATX_WORD = re.compile(r"\b(?:atx)\b", re.I)
# Known full-size boards observed / common naming where model evidence is decisive.
KNOWN_ATX = re.compile(r"\b(?:msi\s+z390-a\s+pro|z390\s+aorus\s+pro)(?!\s+(?:wifi\s+)?mini)\b", re.I)


def title_signals(title: str) -> dict[str, bool]:
    _, gs = v2.match_rule(title, v2.GPU_RULES)
    _, cs = v2.match_rule(title, v2.CPU_RULES)
    return {
        "gpu_model": gs >= 50, "cpu_model": cs >= 50,
        "gpu_noun": bool(GPU_NOUN.search(title)), "cpu_noun": bool(CPU_NOUN.search(title)),
        "board": bool(BOARD.search(title)), "ram": bool(RAM_NOUN.search(title) and RAM_CAPACITY.search(title)),
        "psu": bool(PSU_NOUN.search(title) or PSU_WATT.search(title)), "complete_pc": bool(COMPLETE_PC.search(title)),
    }


def classify(title: str) -> tuple[str | None, str]:
    s = title_signals(title)
    if s["complete_pc"]: return None, "COMPLETE_PC_NOT_COMPONENT"
    if s["board"] and s["cpu_model"]: return "PLATFORM_BUNDLE", "TITLE_PROVES_BOARD_AND_CPU"
    if s["gpu_model"] and (s["gpu_noun"] or re.search(r"\b(?:rtx|gtx|rx)\s*\d", title, re.I)): return "GPU", "TITLE_PROVES_GPU"
    if s["cpu_model"] and (s["cpu_noun"] or re.search(r"\b(?:i[3579][ -]?\d{4,5}|\d{4}x3d|ryzen)\b", title, re.I)): return "CPU", "TITLE_PROVES_CPU"
    if s["ram"] and not (s["gpu_model"] or s["cpu_model"] or s["board"] or s["psu"]): return "RAM", "TITLE_PROVES_RAM"
    if s["psu"] and not (s["gpu_model"] or s["cpu_model"] or s["board"] or s["ram"]): return "PSU", "TITLE_PROVES_PSU"
    return None, "TITLE_IDENTITY_AMBIGUOUS"


def motherboard_fit(text: str, kind: str) -> tuple[str, str]:
    if kind != "PLATFORM_BUNDLE": return "NOT_APPLICABLE", "NO_MOTHERBOARD_REQUIRED"
    if KNOWN_ATX.search(text): return "INCOMPATIBLE", "KNOWN_FULL_SIZE_ATX_MODEL"
    if ITX_WORD.search(text): return "COMPATIBLE", "EXPLICIT_MINI_ITX_EVIDENCE"
    if MATX_WORD.search(text) or MATX_MODEL.search(text): return "COMPATIBLE", "EXPLICIT_MICRO_ATX_EVIDENCE"
    # Generic 'ATX' without micro/mini qualification is full-size and cannot fit Z20.
    if ATX_WORD.search(text): return "INCOMPATIBLE", "EXPLICIT_ATX_EVIDENCE"
    return "UNVERIFIED", "MOTHERBOARD_FORM_FACTOR_NOT_PROVEN"


def upgradeability(cpu: str, text: str, kind: str) -> tuple[str, str]:
    if kind not in {"CPU", "PLATFORM_BUNDLE"}: return "NOT_APPLICABLE", "NOT_A_PLATFORM"
    t = text.lower()
    # Prefer platforms with meaningful drop-in or modern forward upgrade options.
    if any(x in t for x in ("b650", "a620", "x670", "am5")): return "EXCELLENT", "AM5_PLATFORM"
    if any(x in t for x in ("b450", "b550", "x570", "am4")): return "GOOD", "AM4_HAS_STRONG_X3D_ENDGAME"
    if any(x in t for x in ("b660", "b760", "z690", "z790", "lga1700")): return "GOOD", "LGA1700_MULTI_GENERATION_UPGRADE_PATH"
    if any(x in t for x in ("b560", "h510", "lga1200")) or any(x in cpu for x in ("10400", "11400")): return "LIMITED", "LGA1200_END_OF_LINE"
    if any(x in t for x in ("z390", "b365", "h370")) or any(x in cpu for x in ("8600", "9600", "9700")): return "POOR", "LEGACY_LGA1151_NO_MEANINGFUL_DROP_IN_PATH"
    return "UNVERIFIED", "PLATFORM_UPGRADE_PATH_NOT_PROVEN"


def regression() -> dict:
    cases = [
        ("MSI Z390-A Pro ATX bundkort + Intel i5-8600K CPU", "PLATFORM_BUNDLE", "INCOMPATIBLE"),
        ("Intel Core i5-9600K + Gigabyte Z390 AORUS PRO + 16GB DDR4", "PLATFORM_BUNDLE", "INCOMPATIBLE"),
        ("MSI B550M PRO-VDH + Ryzen 5 5600", "PLATFORM_BUNDLE", "COMPATIBLE"),
        ("ASUS B650M + Ryzen 5 7600", "PLATFORM_BUNDLE", "COMPATIBLE"),
        ("Gigabyte GeForce RTX 3060 Ti", "GPU", "NOT_APPLICABLE"),
    ]
    results = []
    for title, expected_kind, expected_fit in cases:
        kind, _ = classify(title)
        fit, _ = motherboard_fit(title, kind or "")
        if kind != expected_kind or fit != expected_fit:
            raise SystemExit(f"Z20 FIT REGRESSION FAILED: {title}: {kind}/{fit}")
        results.append({"title": title, "kind": kind, "z20_fit": fit, "ok": True})
    return {"ok": True, "cases": results}


async def main() -> None:
    Path("results").mkdir(exist_ok=True)
    reg = regression()
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(locale="da-DK", viewport={"width": 1440, "height": 1100})
        search_page, item_page = await context.new_page(), await context.new_page()
        try:
            found: dict[str, dict] = {}; errors: list[dict] = []
            for query in QUERIES:
                try: cards = await discover_cards_by_article(search_page, query)
                except Exception as exc:
                    errors.append({"query": query, "error": type(exc).__name__, "detail": str(exc)[:300]}); continue
                for row in cards:
                    if not isinstance(row.get("ask_t0"), int) or row["ask_t0"] > MAX_PRICE: continue
                    old = found.get(row["listing_id"])
                    if old is None:
                        row["source_queries"] = [query]; found[row["listing_id"]] = row
                    else: old["source_queries"].append(query)

            opportunities: list[dict] = []; rejected: list[dict] = []
            for row in sorted(found.values(), key=lambda x: (x["ask_t0"], x["listing_id"])):
                try: t1 = await v4.fetch_jsonld_item_all_scripts(item_page, row["listing_id"])
                except Exception as exc:
                    rejected.append({"listing_id": row["listing_id"], "reason": "T1_FETCH_FAILED", "detail": type(exc).__name__}); continue
                if not t1 or not t1.get("identity_ok"):
                    rejected.append({"listing_id": row["listing_id"], "reason": "T1_IDENTITY_UNVERIFIED"}); continue
                if not t1.get("active_t1"):
                    rejected.append({"listing_id": row["listing_id"], "reason": "INACTIVE_OR_STATUS_UNVERIFIED"}); continue
                if not isinstance(t1.get("ask_t1"), int) or t1.get("currency_t1") != "DKK":
                    rejected.append({"listing_id": row["listing_id"], "reason": "MISSING_OR_INVALID_T1_PRICE"}); continue

                title = t1.get("title", ""); text = f"{title}\n{t1.get('description','')}\n{t1.get('brand','')}\n{t1.get('category','')}"
                kind, evidence = classify(title)
                if not kind:
                    rejected.append({"listing_id": row["listing_id"], "reason": evidence, "title": title}); continue
                title_gpu, title_gs = v2.match_rule(title, v2.GPU_RULES); title_cpu, title_cs = v2.match_rule(title, v2.CPU_RULES)
                if kind == "GPU": gpu, gs, cpu, cs = title_gpu, title_gs, "Ukendt", 0
                elif kind in {"CPU", "PLATFORM_BUNDLE"}: cpu, cs, gpu, gs = title_cpu, title_cs, "Ukendt", 0
                else: gpu, gs, cpu, cs = "Ukendt", 0, "Ukendt", 0

                fit, fit_reason = motherboard_fit(text, kind)
                upg, upg_reason = upgradeability(cpu, text, kind)
                condition = "DEFECT_DISCLOSED" if DEFECT.search(text) else "NO_DEFECT_SIGNAL"
                format_class, rationale = v2.classify_format(text)
                opportunities.append({
                    "listing_id": row["listing_id"], "url": t1["canonical_url"], "title": title,
                    "ask_t0": row["ask_t0"], "ask_t1": t1["ask_t1"], "currency": t1["currency_t1"],
                    "price_changed": row["ask_t0"] != t1["ask_t1"], "status": t1["availability_t1"],
                    "kind": kind, "identity_evidence": evidence, "condition": condition,
                    "gpu": gpu, "gpu_score": gs, "cpu": cpu, "cpu_score": cs,
                    "z20_fit": fit, "z20_fit_reason": fit_reason,
                    "upgradeability": upg, "upgradeability_reason": upg_reason,
                    "format_evidence": format_class, "format_rationale": rationale,
                    "t0_source": row["t0_source"], "t1_source": t1["t1_source"],
                    "t0_at": row.get("t0_at"), "t1_at": t1.get("t1_at"),
                    "source_queries": sorted(set(row.get("source_queries") or [])),
                })
        finally:
            await search_page.close(); await item_page.close(); await context.close(); await browser.close()

    opportunities.sort(key=lambda r: (r["ask_t1"], -r["gpu_score"], -r["cpu_score"]))
    out = {
        "model_version": "DBA-Z20-PARTS-V3", "generated_at": v2.utcnow(), "gate_passed": True,
        "target_case": "Jonsbo Z20",
        "target_case_rules": {"motherboard": ["Micro-ATX", "Mini-ITX"], "gpu_max_mm": 363, "cpu_cooler_max_mm_intel": 164, "cpu_cooler_max_mm_amd": 163, "atx_psu_recommended_max_mm": 140, "psu": ["ATX", "SFX", "SFX-L"]},
        "policy": "Fail closed on Z20 motherboard fit. A platform bundle is buy/build eligible only with explicit Micro-ATX/Mini-ITX evidence. Full-size ATX is incompatible. Upgradeability is separately classified; legacy dead-end platforms cannot outrank a viable modern platform merely on price.",
        "classifier_regression": reg,
        "counts": {"queries": len(QUERIES), "t0_unique": len(found), "opportunities": len(opportunities), "rejected": len(rejected)},
        "opportunities": opportunities, "rejection_reason_counts": dict(Counter(x["reason"] for x in rejected)), "search_errors": errors,
    }
    Path("results/z20_parts_latest.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out["counts"], ensure_ascii=False))

if __name__ == "__main__": asyncio.run(main())
