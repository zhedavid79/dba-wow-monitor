from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from playwright.async_api import async_playwright

import dba_browser_v2 as v2
import dba_browser_v6 as runtime

INPUT = Path("results/wow_a3_latest.json")
OUTPUT = Path("results/z20_donors_latest.json")
MAX_DONORS = 30
T1_CONCURRENCY = 8
T1_TOTAL_DEADLINE_SECONDS = 120

MATX = re.compile(r"\b(?:micro[- ]?atx|m[- ]?atx|matx|b365m|b450m|b550m|a520m|b560m|h510m|h610m|b660m|b650m|a620m|b760m)\b", re.I)
ITX = re.compile(r"\b(?:mini[- ]?itx|miniitx|m[- ]?itx)\b", re.I)
ATX_BOARD_CONTEXT = re.compile(
    r"\b(?:atx|e[- ]?atx|extended[- ]?atx)\b.{0,30}\b(?:bundkort|motherboard|mainboard)\b|"
    r"\b(?:bundkort|motherboard|mainboard)\b.{0,30}\b(?:atx|e[- ]?atx|extended[- ]?atx)\b",
    re.I | re.S,
)
KNOWN_FULL_ATX_BOARD = re.compile(
    r"\b(?:msi\s+z390-a\s+pro|gigabyte\s+z390\s+aorus\s+pro|asus\s+prime\s+z390-a|"
    r"msi\s+z490-a\s+pro|msi\s+z590-a\s+pro|asus\s+prime\s+z690-p|asus\s+prime\s+z790-p)\b",
    re.I,
)
BOARD_MODEL = re.compile(r"\b(?:asus|msi|gigabyte|asrock)\s+[a-z0-9 -]*(?:b365m|b450m|b550m|a520m|b560m|h510m|h610m|b660m|b650m|a620m|b760m|z390|z490|z590|z690|z790)[a-z0-9 .+/-]*", re.I)
PSU_EVIDENCE = re.compile(r"\b(?:corsair|seasonic|be\s*quiet!?|evga|cooler\s*master|nzxt|asus|msi|fsp|super\s*flower)\b.{0,50}\b([5-9]\d{2}|1\d{3})\s*w\b", re.I | re.S)
RAM_DESKTOP = re.compile(r"\b(?:ddr4|ddr5)\b.{0,35}\b(?:2\s*x\s*(?:8|16|32)|16\s*gb|32\s*gb|64\s*gb)\b|\b(?:2\s*x\s*(?:8|16|32)|16\s*gb|32\s*gb|64\s*gb)\b.{0,35}\b(?:ddr4|ddr5)\b", re.I | re.S)
RAM_BAD = re.compile(r"\b(?:so[- ]?dimm|sodimm|lrdimm|rdimm|registered)\b", re.I)
DEFECT = re.compile(r"\b(?:defekt|delvist\s+defekt|virker\s+ikke|artefakt|artifact|til\s+dele|reservedele)\b", re.I)

GPU_SKUS = [
    (re.compile(r"msi.{0,50}rtx\s*3060\s*ti.{0,50}ventus\s*2x|rtx\s*3060\s*ti.{0,50}ventus\s*2x", re.I | re.S), "MSI RTX 3060 Ti Ventus 2X", 235, 52),
    (re.compile(r"(?:gigabyte|aorus).{0,60}rtx\s*3070.{0,60}(?:aorus\s+master|master)|rtx\s*3070.{0,60}aorus\s+master", re.I | re.S), "Gigabyte AORUS RTX 3070 Master", 290, 60),
]


def motherboard_evidence(text: str) -> tuple[str, str | None]:
    model = BOARD_MODEL.search(text)
    model_text = re.sub(r"\s+", " ", model.group(0)).strip() if model else None
    if ITX.search(text): return "COMPATIBLE", model_text
    if MATX.search(text): return "COMPATIBLE", model_text
    if KNOWN_FULL_ATX_BOARD.search(text) or ATX_BOARD_CONTEXT.search(text): return "INCOMPATIBLE", model_text
    return "UNVERIFIED", model_text


def donor_regression() -> dict:
    cases = [
        ("MSI B550M PRO-VDH motherboard, Corsair ATX PSU 650W", "COMPATIBLE"),
        ("Corsair RM650e ATX strømforsyning 650W, motherboard unknown", "UNVERIFIED"),
        ("ATX motherboard ASUS model, RTX 3070", "INCOMPATIBLE"),
        ("MSI Z390-A Pro + i5-9600K", "INCOMPATIBLE"),
        ("B650M motherboard + Ryzen 7600", "COMPATIBLE"),
    ]
    out = []
    for text, expected in cases:
        got, _ = motherboard_evidence(text)
        if got != expected:
            raise SystemExit(f"DONOR BOARD REGRESSION FAILED: {text}: {got} != {expected}")
        out.append({"text": text, "fit": got, "ok": True})
    return {"ok": True, "cases": out}


def gpu_sku(text: str) -> dict:
    for pat, model, length, thickness in GPU_SKUS:
        if pat.search(text):
            return {"status": "PROVEN", "model": model, "length_mm": length, "thickness_mm": thickness}
    return {"status": "UNVERIFIED"}


def platform_upgradeability(cpu: str, text: str) -> str:
    t = text.lower()
    if any(x in t for x in ("b650", "a620", "x670", "am5")) or any(x in cpu for x in ("7500F", "7600", "7700", "7800X3D", "7900", "7950", "9600X", "9700X", "9800X3D")): return "EXCELLENT"
    if any(x in t for x in ("b450", "b550", "x570", "am4")): return "GOOD"
    if any(x in t for x in ("b660", "b760", "z690", "z790", "lga1700")): return "GOOD"
    if any(x in cpu for x in ("10400", "10700", "11400", "11700")): return "LIMITED"
    if any(x in cpu for x in ("8600", "8700", "9600", "9700")): return "POOR"
    return "UNVERIFIED"


async def resolve_all(context, seeds: list[dict]) -> tuple[dict[str, dict | None], list[dict], dict]:
    sem = asyncio.Semaphore(T1_CONCURRENCY)

    async def one(seed: dict):
        async with sem:
            t1, error = await runtime.fetch_t1_one(context, str(seed["listing_id"]))
            return str(seed["listing_id"]), t1, error

    tasks = [asyncio.create_task(one(seed)) for seed in seeds]
    timed_out = False
    try:
        results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=T1_TOTAL_DEADLINE_SECONDS)
    except asyncio.TimeoutError:
        timed_out = True
        for task in tasks: task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        results = []

    by_id: dict[str, dict | None] = {}; errors: list[dict] = []; completed = set()
    for lid, t1, error in results:
        completed.add(lid); by_id[lid] = t1
        if error: errors.append(error)
    expected = {str(s["listing_id"]) for s in seeds}; missing = sorted(expected - completed)
    coverage = {"candidate_total": len(seeds), "candidate_completed": len(completed), "candidate_fetch_errors": len(errors), "missing_listing_ids": missing, "deadline_exceeded": timed_out, "complete": not timed_out and not missing}
    return by_id, errors, coverage


async def main() -> None:
    reg = donor_regression()
    doc = json.loads(INPUT.read_text(encoding="utf-8"))
    seeds = []
    for r in doc.get("ranked") or []:
        if str(r.get("form_factor") or "").upper() == "DESKTOP": seeds.append(r)
    for r in doc.get("potential_sweet_spots_unresolved") or []:
        if int(r.get("ask_t1") or 10**9) <= 5000: seeds.append(r)
    seen = set(); seeds = [x for x in seeds if not (x["listing_id"] in seen or seen.add(x["listing_id"]))][:MAX_DONORS]

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(locale="da-DK", viewport={"width": 1440, "height": 1100})
        donors = []
        try:
            t1_by_id, t1_errors, coverage = await resolve_all(context, seeds)
            if not coverage["complete"]:
                raise SystemExit(f"DONOR DATA GATE FAILED — T1 coverage incomplete: {json.dumps(coverage, ensure_ascii=False)}")
            for seed in seeds:
                t1 = t1_by_id.get(str(seed["listing_id"]))
                if not t1 or not t1.get("identity_ok") or not t1.get("active_t1"): continue
                if not isinstance(t1.get("ask_t1"), int) or t1.get("currency_t1") != "DKK": continue
                text = f"{t1.get('title','')}\n{t1.get('description','')}\n{t1.get('brand','')}\n{t1.get('category','')}"
                gpu, gs = v2.match_rule(text, v2.GPU_RULES); cpu, cs = v2.match_rule(text, v2.CPU_RULES)
                mb_fit, mb_model = motherboard_evidence(text)
                sku = gpu_sku(text)
                psu = PSU_EVIDENCE.search(text)
                ram_ok = bool(RAM_DESKTOP.search(text)) and not bool(RAM_BAD.search(text))
                donors.append({
                    "listing_id": seed["listing_id"], "url": t1["canonical_url"], "title": t1["title"],
                    "ask_t1": t1["ask_t1"], "currency": t1["currency_t1"], "status": t1["availability_t1"],
                    "gpu": gpu, "gpu_score": gs, "gpu_sku": sku, "cpu": cpu, "cpu_score": cs,
                    "motherboard_fit": mb_fit, "motherboard_model_evidence": mb_model,
                    "upgradeability": platform_upgradeability(cpu, text),
                    "desktop_ram_evidence": ram_ok,
                    "psu_evidence": re.sub(r"\s+", " ", psu.group(0)).strip() if psu else None,
                    "condition": "DEFECT_DISCLOSED" if DEFECT.search(text) else "NO_DEFECT_SIGNAL",
                    "t1_source": t1["t1_source"], "t1_at": t1.get("t1_at"),
                })
        finally:
            await context.close(); await browser.close()

    donors.sort(key=lambda r: (r["ask_t1"], -r["gpu_score"], -r["cpu_score"]))
    out = {
        "model_version": "DBA-Z20-DONOR-RESOLVER-V2", "generated_at": v2.utcnow(), "gate_passed": True,
        "policy": "Re-fetch live donor PCs with bounded parallel T1 and complete coverage. Expose only explicit component evidence. ATX PSU text cannot prove an ATX motherboard. Unknown motherboard/GPU SKU remains unresolved and never becomes proven fit.",
        "classifier_regression": reg,
        "coverage": coverage,
        "t1_diagnostics": t1_errors,
        "count": len(donors), "donors": donors,
    }
    OUTPUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"donors": len(donors), "compatible_mb": sum(x["motherboard_fit"] == "COMPATIBLE" for x in donors), "exact_gpu": sum(x["gpu_sku"]["status"] == "PROVEN" for x in donors), "coverage_complete": coverage["complete"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__": asyncio.run(main())
