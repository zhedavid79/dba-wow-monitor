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
QUERY_TIMEOUT_SECONDS = 12
QUERY_RETRIES = 2
DISCOVERY_CONCURRENCY = 6
DISCOVERY_TOTAL_DEADLINE_SECONDS = 180
T1_TIMEOUT_SECONDS = 15
T1_CONCURRENCY = 8
T1_TOTAL_DEADLINE_SECONDS = 300

GENERIC_PC_QUERIES = {
    "gaming pc", "gamer pc", "gaming computer", "stationær gaming", "gaming bærbar", "gaming laptop",
    "omen gaming", "legion gaming", "nitro gaming", "predator gaming", "sharkgaming", "dutzo", "mm vision", "msi gamer",
    "skal væk gaming", "hurtig handel gaming",
}

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
    gpu, gpu_score = v2.match_rule(text, v2.GPU_RULES)
    cpu, cpu_score = v2.match_rule(text, v2.CPU_RULES)
    complete_hint = bool(COMPLETE_HINT_RE.search(text))
    component_only = bool(COMPONENT_ONLY_RE.search(text))
    queries = set(row.get("source_queries") or ([row.get("query")] if row.get("query") else []))
    generic_pc_source = bool(queries & GENERIC_PC_QUERIES)

    # Fail closed on explicit component identity. This is the key protection against
    # GPU-specific searches flooding T1 with loose cards.
    if component_only:
        tier = 9
    # Strong complete-system evidence: GPU + CPU in the same rendered card.
    elif gpu_score >= 50 and cpu_score >= 50:
        tier = 0
    # Named/OEM complete-PC signals with a suitable GPU.
    elif gpu_score >= 50 and complete_hint:
        tier = 0
    # Preserve generic-PC discovery recall for sparse cards where CPU is not visible at T0.
    elif gpu_score >= 50 and generic_pc_source and int(row.get("ask_t0") or 10**9) <= RESCUE_PRICE_MAX:
        tier = 1
    # Cheap complete-looking systems may hide specs in the item description.
    elif complete_hint and int(row.get("ask_t0") or 10**9) <= RESCUE_PRICE_MAX:
        tier = 1
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


async def discover_one(context, query: str) -> tuple[list[dict], dict | None, int]:
    last_error: dict | None = None
    for attempt in range(1, QUERY_RETRIES + 1):
        page = await context.new_page()
        try:
            rows = await asyncio.wait_for(discover_cards_by_article(page, query), timeout=QUERY_TIMEOUT_SECONDS)
            return rows, None, attempt
        except asyncio.TimeoutError:
            last_error = {
                "query": query,
                "error": "QUERY_TIMEOUT",
                "detail": f"attempt {attempt} exceeded {QUERY_TIMEOUT_SECONDS}s",
            }
        except Exception as exc:
            last_error = {
                "query": query,
                "error": type(exc).__name__,
                "detail": f"attempt {attempt}: {str(exc)[:260]}",
            }
        finally:
            await page.close()
    return [], last_error, QUERY_RETRIES


async def discover_all(context) -> tuple[dict[str, dict], list[dict], dict]:
    queue: asyncio.Queue[str | None] = asyncio.Queue()
    for query in v2.QUERIES:
        queue.put_nowait(query)
    for _ in range(DISCOVERY_CONCURRENCY):
        queue.put_nowait(None)

    found: dict[str, dict] = {}
    errors: list[dict] = []
    completed_queries: set[str] = set()
    lock = asyncio.Lock()

    async def worker(worker_no: int) -> None:
        while True:
            query = await queue.get()
            try:
                if query is None:
                    return
                rows, error, attempts = await discover_one(context, query)
                async with lock:
                    completed_queries.add(query)
                    if error:
                        errors.append(error)
                    for row in rows:
                        existing = found.get(row["listing_id"])
                        if existing is None:
                            row["source_queries"] = [query]
                            found[row["listing_id"]] = row
                        else:
                            existing["source_queries"].append(query)
                    print(json.dumps({
                        "stage": "DISCOVERY_PROGRESS",
                        "worker": worker_no,
                        "completed": len(completed_queries),
                        "total": len(v2.QUERIES),
                        "query": query,
                        "rows": len(rows),
                        "unique_total": len(found),
                        "attempts": attempts,
                        "error": error["error"] if error else None,
                    }, ensure_ascii=False), flush=True)
            finally:
                queue.task_done()

    workers = [asyncio.create_task(worker(i + 1)) for i in range(DISCOVERY_CONCURRENCY)]
    timed_out = False
    try:
        await asyncio.wait_for(queue.join(), timeout=DISCOVERY_TOTAL_DEADLINE_SECONDS)
    except asyncio.TimeoutError:
        timed_out = True
    finally:
        if timed_out:
            for task in workers:
                task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)

    missing = sorted(set(v2.QUERIES) - completed_queries)
    coverage = {
        "query_total": len(v2.QUERIES),
        "query_completed": len(completed_queries),
        "query_failed": len(errors),
        "missing_queries": missing,
        "deadline_exceeded": timed_out,
        "complete": (not timed_out and not missing and not errors),
    }
    return found, errors, coverage


async def fetch_t1_one(context, listing_id: str) -> tuple[dict | None, dict | None]:
    page = await context.new_page()
    try:
        item = await asyncio.wait_for(
            v4.fetch_jsonld_item_all_scripts(page, listing_id),
            timeout=T1_TIMEOUT_SECONDS,
        )
        return item, None
    except asyncio.TimeoutError:
        return None, {
            "listing_id": listing_id,
            "result": "T1_TIMEOUT",
            "detail": f"T1 fetch exceeded {T1_TIMEOUT_SECONDS}s",
        }
    except Exception as exc:
        return None, {
            "listing_id": listing_id,
            "result": "fetch_error",
            "detail": f"{type(exc).__name__}: {str(exc)[:240]}",
        }
    finally:
        await page.close()


async def fetch_all_t1(context, candidates: list[dict]) -> tuple[dict[str, dict | None], list[dict], dict]:
    queue: asyncio.Queue[dict | None] = asyncio.Queue()
    for row in candidates:
        queue.put_nowait(row)
    for _ in range(T1_CONCURRENCY):
        queue.put_nowait(None)

    results: dict[str, dict | None] = {}
    diagnostics: list[dict] = []
    completed_ids: set[str] = set()
    lock = asyncio.Lock()

    async def worker(worker_no: int) -> None:
        while True:
            row = await queue.get()
            try:
                if row is None:
                    return
                lid = str(row["listing_id"])
                t1, error = await fetch_t1_one(context, lid)
                async with lock:
                    results[lid] = t1
                    completed_ids.add(lid)
                    if error:
                        diagnostics.append(error)
                    completed = len(completed_ids)
                    if completed == 1 or completed % 20 == 0 or completed == len(candidates):
                        print(json.dumps({
                            "stage": "T1_PROGRESS",
                            "worker": worker_no,
                            "completed": completed,
                            "total": len(candidates),
                            "errors": len(diagnostics),
                        }, ensure_ascii=False), flush=True)
            finally:
                queue.task_done()

    workers = [asyncio.create_task(worker(i + 1)) for i in range(T1_CONCURRENCY)]
    timed_out = False
    try:
        await asyncio.wait_for(queue.join(), timeout=T1_TOTAL_DEADLINE_SECONDS)
    except asyncio.TimeoutError:
        timed_out = True
    finally:
        if timed_out:
            for task in workers:
                task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)

    expected_ids = {str(r["listing_id"]) for r in candidates}
    missing_ids = sorted(expected_ids - completed_ids)
    coverage = {
        "candidate_total": len(candidates),
        "candidate_completed": len(completed_ids),
        "candidate_fetch_errors": len(diagnostics),
        "missing_listing_ids": missing_ids,
        "deadline_exceeded": timed_out,
        # A fetch error is a per-listing objective rejection, not a coverage hole, if the
        # attempt completed. Missing IDs/global timeout are coverage failures.
        "complete": (not timed_out and not missing_ids),
    }
    return results, diagnostics, coverage


async def main() -> None:
    Path("results").mkdir(exist_ok=True)
    regression = v2.fixture_regression()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(locale="da-DK", viewport={"width": 1440, "height": 1100})
        try:
            found, search_errors, discovery_coverage = await discover_all(context)
            print(json.dumps({
                "stage": "DISCOVERY_COMPLETE",
                "t0_unique": len(found),
                "coverage": discovery_coverage,
            }, ensure_ascii=False), flush=True)

            # A fully reliable report requires all configured discovery queries to complete.
            if not discovery_coverage["complete"]:
                diagnostic = {
                    "model_version": "DBA-WOW-BROWSER-HIGH-RECALL-V9",
                    "generated_at": v2.utcnow(),
                    "gate_passed": False,
                    "failure": "DISCOVERY_COVERAGE_INCOMPLETE",
                    "discovery_coverage": discovery_coverage,
                    "search_errors": search_errors,
                }
                Path("results/wow_a3_gate_failure.json").write_text(json.dumps(diagnostic, ensure_ascii=False, indent=2), encoding="utf-8")
                raise SystemExit("PRICE DATA GATE FAILED — complete DBA discovery coverage not achieved")

            candidates = sorted((r for r in found.values() if should_t1(r)), key=discovery_priority)
            t1_by_id, t1_diagnostics, t1_coverage = await fetch_all_t1(context, candidates)
            print(json.dumps({
                "stage": "T1_COMPLETE",
                "t0_to_t1": len(candidates),
                "coverage": t1_coverage,
            }, ensure_ascii=False), flush=True)

            if not t1_coverage["complete"]:
                diagnostic = {
                    "model_version": "DBA-WOW-BROWSER-HIGH-RECALL-V9",
                    "generated_at": v2.utcnow(),
                    "gate_passed": False,
                    "failure": "T1_COVERAGE_INCOMPLETE",
                    "discovery_coverage": discovery_coverage,
                    "t1_coverage": t1_coverage,
                    "t1_diagnostics": t1_diagnostics,
                }
                Path("results/wow_a3_gate_failure.json").write_text(json.dumps(diagnostic, ensure_ascii=False, indent=2), encoding="utf-8")
                raise SystemExit("PRICE DATA GATE FAILED — complete T1 candidate coverage not achieved")

            source_gate = None
            gate_attempts: list[dict] = list(t1_diagnostics)
            for row in candidates:
                t1 = t1_by_id.get(row["listing_id"])
                if not t1:
                    if not any(x.get("listing_id") == row["listing_id"] for x in gate_attempts):
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
                    "model_version": "DBA-WOW-BROWSER-HIGH-RECALL-V9",
                    "generated_at": v2.utcnow(),
                    "gate_passed": False,
                    "failure": "NO_VERIFIED_T0_T1_PAIR",
                    "counts": {"queries": len(v2.QUERIES), "t0_unique": len(found), "t0_to_t1": len(candidates)},
                    "gate_attempts": gate_attempts[:200],
                    "search_errors": search_errors,
                    "discovery_coverage": discovery_coverage,
                    "t1_coverage": t1_coverage,
                }
                Path("results/wow_a3_gate_failure.json").write_text(json.dumps(diagnostic, ensure_ascii=False, indent=2), encoding="utf-8")
                raise SystemExit("PRICE DATA GATE FAILED — no live rendered-card + same-ID Product JSON pair verified")

            ranked: list[dict] = []
            unresolved: list[dict] = []
            rejected: list[dict] = []

            for row in candidates:
                t1 = t1_by_id.get(row["listing_id"])
                if not t1:
                    diagnostic = next((x for x in t1_diagnostics if x.get("listing_id") == row["listing_id"]), None)
                    rejected.append({
                        "listing_id": row["listing_id"],
                        "reason": "T1_FETCH_FAILED",
                        "detail": diagnostic.get("detail", diagnostic.get("result")) if diagnostic else "no_product_json",
                    })
                    continue
                if not t1.get("identity_ok"):
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
            await context.close()
            await browser.close()

    class_order = {"SWEET SPOT": 0, "ACCEPTABLE": 1, "OVERKILL": 2}
    ranked.sort(key=lambda r: (r["ask_t1"], class_order.get(r["performance_class"], 9), -r["gpu_score"], -r["cpu_score"]))
    unresolved.sort(key=lambda r: (r["ask_t1"], r["listing_id"]))

    output = {
        "model_version": "DBA-WOW-BROWSER-HIGH-RECALL-V9",
        "generated_at": v2.utcnow(),
        "gate_passed": True,
        "retrieval_method": "Rendered same-listing DBA card T0 + same-ID DBA Product JSON T1",
        "ranking_policy": "Verified complete PCs clearing the WoW performance gate are ranked strictly price-first. Cheap unresolved complete systems remain visible but unranked.",
        "runtime_policy": {
            "query_timeout_seconds": QUERY_TIMEOUT_SECONDS,
            "query_retries": QUERY_RETRIES,
            "discovery_concurrency": DISCOVERY_CONCURRENCY,
            "discovery_total_deadline_seconds": DISCOVERY_TOTAL_DEADLINE_SECONDS,
            "t1_timeout_seconds": T1_TIMEOUT_SECONDS,
            "t1_concurrency": T1_CONCURRENCY,
            "t1_total_deadline_seconds": T1_TOTAL_DEADLINE_SECONDS,
            "candidate_cap": None,
        },
        "coverage": {
            "discovery": discovery_coverage,
            "t1": t1_coverage,
        },
        "source_gate": source_gate,
        "price_binding_regression": regression,
        "counts": {
            "queries": len(v2.QUERIES),
            "t0_unique": len(found),
            "t0_to_t1": len(candidates),
            "ranked": len(ranked),
            "potential_sweet_spot_unresolved": len(unresolved),
            "rejected": len(rejected),
            "search_timeouts_or_errors": len(search_errors),
            "t1_timeouts_or_errors": len(t1_diagnostics),
        },
        "ranked": ranked,
        "potential_sweet_spots_unresolved": unresolved,
        "rejected": rejected,
        "rejection_reason_counts": dict(Counter(x.get("reason", "UNKNOWN") for x in rejected)),
        "search_errors": search_errors,
        "t1_diagnostics": t1_diagnostics,
    }
    Path("results/wow_a3_latest.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# FULDT PÅLIDELIG DBA-PRISRAPPORT — WoW Classic/Cataclysm",
        "",
        f"Generated: {output['generated_at']}",
        f"Retrieval: {output['retrieval_method']}",
        f"Discovery coverage: {discovery_coverage['query_completed']}/{discovery_coverage['query_total']}",
        f"T1 coverage: {t1_coverage['candidate_completed']}/{t1_coverage['candidate_total']}",
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

    print(json.dumps({
        "gate": True,
        "t0_unique": len(found),
        "t0_to_t1": len(candidates),
        "ranked": len(ranked),
        "unresolved": len(unresolved),
        "rejected": len(rejected),
        "search_errors": len(search_errors),
        "t1_diagnostics": len(t1_diagnostics),
        "discovery_coverage_complete": discovery_coverage["complete"],
        "t1_coverage_complete": t1_coverage["complete"],
    }, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
